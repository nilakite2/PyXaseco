"""Local bridge bootstrap and credential-file protection; no networking on import."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tomllib
from uuid import uuid4

from .config_store import ManagementError, update_file
from .operations import ManagementOperations


def _windows_api():
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    api.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    return ctypes, wintypes, api, kernel


def protect_token(path: Path, *, service_reader=False):
    if path.is_symlink():
        raise ManagementError('Credential files may not be symbolic links')
    if os.name != 'nt':
        os.chmod(path, 0o600)
        return
    system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
    who = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                         capture_output=True, text=True, timeout=10, check=True)
    sid = next(csv.reader([who.stdout.strip()]))[-1]
    if not re.fullmatch(r'S-1-[0-9-]+', sid):
        raise ManagementError('Cannot identify credential owner')
    ctypes, _types, api, kernel = _windows_api()
    descriptor = ctypes.c_void_p()
    sddl = f'O:{sid}D:P(A;;FA;;;{sid})(A;;FA;;;SY)(A;;FA;;;BA)'
    if service_reader:
        sddl += '(A;;FR;;;LS)'
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ManagementError('Cannot construct credential ACL')
    try:
        if not api.SetFileSecurityW(str(path), 0x80000005, descriptor):
            raise ManagementError('Cannot protect credential file')
    finally:
        kernel.LocalFree(descriptor)


def read_token(root: Path) -> str:
    path = root / '.management-token'
    if path.is_symlink() or path.stat().st_size > 512:
        raise ManagementError('Unsafe credential file')
    if os.name != 'nt':
        # Group-read permits an explicitly provisioned local administrator group.
        if stat.S_IMODE(path.stat().st_mode) & 0o137:
            raise ManagementError('Credential file must not be public, executable or group-writable')
    else:
        ctypes, types, api, kernel = _windows_api()
        length = types.DWORD()
        api.GetFileSecurityW(str(path), 5, None, 0, ctypes.byref(length))
        if not length.value:
            raise ManagementError('Cannot inspect credential ACL')
        buffer = ctypes.create_string_buffer(length.value)
        if not api.GetFileSecurityW(str(path), 5, buffer, length.value, ctypes.byref(length)):
            raise ManagementError('Cannot inspect credential ACL')
        pointer = types.LPWSTR()
        if not api.ConvertSecurityDescriptorToStringSecurityDescriptorW(buffer, 1, 5, ctypes.byref(pointer), None):
            raise ManagementError('Cannot inspect credential security descriptor')
        try:
            descriptor = pointer.value
        finally:
            kernel.LocalFree(ctypes.cast(pointer, ctypes.c_void_p))
        owner = re.search(r'O:(.*?)(?=G:|D:|S:|$)', descriptor)
        allowed = {'SY', 'BA', 'LS', owner.group(1) if owner else ''}
        if 'D:P' not in descriptor:
            raise ManagementError('Credential ACL must disable inherited permissions')
        for ace in re.findall(r'\(([^()]*)\)', descriptor):
            fields = ace.split(';')
            if len(fields) != 6 or fields[0] not in {'A', 'D'}:
                raise ManagementError('Credential ACL contains unsupported access entries')
            if fields[0] == 'A' and fields[-1] not in allowed:
                raise ManagementError('Credential ACL grants access outside the local management principals')
    token = path.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ManagementError('Invalid local management credential')
    return token


def read_identity(root: Path) -> dict:
    file = root / 'management.toml'
    if file.is_symlink() or file.stat().st_size > 4096:
        raise ManagementError('Unsafe management identity file')
    data = tomllib.loads(file.read_text(encoding='utf-8')).get('management', {})
    if (not isinstance(data, dict) or type(data.get('protocol')) is not int or data['protocol'] != 1
            or not re.fullmatch(r'[0-9a-f]{32}', str(data.get('instance_id', '')))):
        raise ManagementError('Run bridge-init to create a valid management identity')
    operator = data.get('operator', 'local-operator')
    if not isinstance(operator, str) or not 1 <= len(operator) <= 80 or any(ord(c) < 32 for c in operator):
        raise ManagementError('Invalid local operator label')
    return {'instance_id': data['instance_id'], 'operator': operator, 'protocol': 1}


def initialize_bridge(root: str | Path, *, instance_id=None, enable=False,
                      offline=False, service_reader=False) -> dict:
    from pyxaseco.toml_tools import move_loadout_entry
    operations = ManagementOperations(root)
    root = operations.root
    if instance_id is not None and not re.fullmatch(r'[0-9a-f]{32}', instance_id):
        raise ManagementError('Invalid registered instance identity')
    with operations._offline(offline):
        identity_file = root / 'management.toml'
        if identity_file.exists():
            identity = read_identity(root)
            if instance_id is not None and identity['instance_id'] != instance_id:
                raise ManagementError('Bridge identity differs from the registered installation')
        else:
            identity = {'instance_id': instance_id or uuid4().hex, 'protocol': 1, 'operator': 'local-operator'}
            text = '[management]\n' + ''.join(f'{key} = {json.dumps(value)}\n' for key, value in identity.items())
            update_file(identity_file, lambda _text: text, validator=tomllib.loads)
            read_identity(root)
        token_file = root / '.management-token'
        created = not token_file.exists()
        if created:
            fd = os.open(token_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                protect_token(token_file, service_reader=service_reader)
                with os.fdopen(fd, 'w', encoding='ascii') as stream:
                    fd = None
                    stream.write(secrets.token_urlsafe(32) + '\n')
            finally:
                if fd is not None:
                    os.close(fd)
        read_token(root)  # Existing credentials are never silently replaced or weakened.
        if enable:
            if not (root / 'apps/management_bridge/app.py').is_file():
                raise ManagementError('Optional management_bridge app is not installed')
            move_loadout_entry(root / 'apps.toml', 'app/management_bridge', True)
    return {'instance_id': identity['instance_id'], 'credential_created': created,
            'enabled_for_next_start': enable, 'started': False, 'token': 'not displayed'}
