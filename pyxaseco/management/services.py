"""Per-installation service definitions and explicit, non-shell OS operations."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from .config_store import ManagementError
from .instances import Instance


WINSW_VERSION = '2.12.0'


@dataclass(frozen=True)
class ServicePlan:
    instance_id: str
    name: str
    platform: str
    controller: str
    config: str
    python: str
    dedicated: str | None
    controller_service: str
    dedicated_service: str
    owns_dedicated: bool = False
    user: str = ''
    automatic: bool = False
    dedicated_args: tuple[str, ...] = (
        '/game_settings=MatchSettings/MatchSettings.txt', '/dedicated_cfg=dedicated_cfg.txt',
    )

    @classmethod
    def from_instance(cls, instance: Instance, *, platform: str, manage_dedicated=False,
                      user='', automatic=False):
        if platform not in ('windows', 'linux'):
            raise ManagementError('Service platform must be windows or linux')
        if manage_dedicated and not instance.dedicated:
            raise ManagementError('Dedicated executable must be registered before managing it')
        user = user or ('LocalService' if platform == 'windows' else 'pyxaseco-' + instance.id[:12])
        if platform == 'windows' and user != 'LocalService':
            raise ManagementError('Initial Windows adapter uses LocalService, never LocalSystem')
        if platform == 'linux' and (not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', user) or user == 'root'):
            raise ManagementError('Supply an existing non-root Linux service user')
        return cls(instance.id, instance.name, platform, instance.controller, instance.config,
                   instance.python, instance.dedicated, instance.controller_service,
                   instance.dedicated_service, manage_dedicated, user, automatic)

    @classmethod
    def read(cls, path: str | Path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.pop('schema', None) != 1:
            raise ManagementError('Unsupported service plan schema')
        data['dedicated_args'] = tuple(data.get('dedicated_args', ()))
        plan = cls(**data)
        plan.validate()
        return plan

    def validate(self):
        if type(self.owns_dedicated) is not bool or type(self.automatic) is not bool:
            raise ManagementError('Service ownership/startup flags must be booleans')
        if not re.fullmatch(r'[0-9a-f]{32}', self.instance_id):
            raise ManagementError('Invalid instance identity in service plan')
        if self.platform not in ('windows', 'linux'):
            raise ManagementError('Unsupported service platform')
        if self.controller_service != 'PyXaseco-' + self.instance_id or self.dedicated_service != 'TMF-' + self.instance_id:
            raise ManagementError('Service names must belong to this instance')
        if self.platform == 'windows' and self.user != 'LocalService':
            raise ManagementError('Windows runtime account must be LocalService')
        if self.platform == 'linux' and (not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', self.user) or self.user == 'root'):
            raise ManagementError('Invalid Linux service account')
        for value in (self.controller, self.config, self.python, self.dedicated or '', self.name, *self.dedicated_args):
            if any(ord(char) < 32 for char in value):
                raise ManagementError('Service paths/arguments may not contain control characters')
            if self.platform == 'windows' and '%' in value:
                raise ManagementError('WinSW paths may not contain environment-expansion markers')
        root = Path(self.controller).resolve()
        if Path(self.config).resolve().parent != root:
            raise ManagementError('Service config must belong to the controller installation')
        if not all(Path(value).is_absolute() for value in (self.python, self.controller, self.config)):
            raise ManagementError('Services require absolute executable and controller paths')
        if self.owns_dedicated and (not self.dedicated or not Path(self.dedicated).is_absolute()):
            raise ManagementError('Managed dedicated server requires an absolute executable path')

    def service_name(self, target: str) -> str:
        if target == 'controller':
            return self.controller_service
        if target == 'dedicated' and self.owns_dedicated:
            return self.dedicated_service
        raise ManagementError('This component is not managed by the service plan')


def _unit_quote(text: str, *, command=False) -> str:
    escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if command:
        escaped = escaped.replace('$', '$$')
    return '"' + escaped + '"'


def render_systemd(plan: ServicePlan, plan_path: Path, target: str) -> str:
    name = plan.service_name(target)
    root = Path(plan.controller)
    if target == 'controller':
        command = [plan.python, '-u', '-B', str(root / 'main.py'), plan.config,
                   '--supervised', '--service-plan', str(plan_path)]
        working = root
    else:
        command = [plan.dedicated, *plan.dedicated_args, '/nodaemon']
        working = Path(plan.dedicated).parent
    order = f'After={plan.dedicated_service}.service\n' if target == 'controller' and plan.owns_dedicated else ''
    return (f'[Unit]\nDescription=PyXaseco {target} {plan.instance_id}\n{order}'
            'StartLimitIntervalSec=300\nStartLimitBurst=5\n\n[Service]\nType=exec\n'
            f'User={plan.user}\nWorkingDirectory={_unit_quote(str(working))}\n'
            f'ExecStart={" ".join(_unit_quote(str(arg), command=True) for arg in command)}\n'
            'Restart=on-failure\nRestartSec=10\nTimeoutStopSec=60\nKillMode=control-group\n'
            'KillSignal=SIGTERM\nUMask=0077\nNoNewPrivileges=yes\nPrivateTmp=yes\n'
            + ('RestartPreventExitStatus=78\n' if target == 'controller' else '')
            + '\n[Install]\nWantedBy=multi-user.target\n')


def render_winsw(plan: ServicePlan, plan_path: Path, target: str) -> str:
    name = plan.service_name(target)
    root = Path(plan.controller)
    node = ET.Element('service')
    def add(key, text):
        ET.SubElement(node, key).text = str(text)
    add('id', name)
    add('name', 'PyXaseco ' + target + ' ' + plan.instance_id)
    add('description', 'Managed PyXaseco installation ' + plan.instance_id)
    if target == 'controller':
        add('executable', plan.python)
        add('startarguments', subprocess.list2cmdline([
            '-u', '-B', str(root / 'main.py'), plan.config,
            '--supervised', '--service-plan', str(plan_path)]))
        add('stopexecutable', plan.python)
        add('stoparguments', subprocess.list2cmdline([
            '-B', '-m', 'pyxaseco.management', 'service-signal', '--folder', str(root), '--timeout', '50']))
        add('workingdirectory', root)
    else:
        add('executable', plan.dedicated)
        add('arguments', subprocess.list2cmdline(list(plan.dedicated_args)))
        add('workingdirectory', Path(plan.dedicated).parent)
    add('startmode', 'Automatic' if plan.automatic else 'Manual')
    add('stoptimeout', '60sec')
    add('stopparentprocessfirst', 'true')
    account = ET.SubElement(node, 'serviceaccount')
    ET.SubElement(account, 'domain').text = 'NT AUTHORITY'
    ET.SubElement(account, 'user').text = 'LocalService'
    # Only query/stop for the runtime account; no service creation/configuration rights.
    add('securityDescriptor', 'D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;LCWP;;;LS)')
    ET.SubElement(node, 'onfailure', action='restart', delay='10sec')
    if target == 'dedicated':
        ET.SubElement(node, 'onfailure', action='restart', delay='30sec')
        ET.SubElement(node, 'onfailure', action='none')
    add('resetfailure', '1hour')
    add('logpath', plan_path.parent / 'logs')
    ET.SubElement(node, 'log', mode='roll')
    ET.indent(node)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(node, encoding='unicode') + '\n'


def prepare_bundle(plan: ServicePlan, destination: str | Path) -> Path:
    """Write reviewable artifacts only; never install, elevate or start services."""
    plan.validate()
    destination = Path(destination).resolve()
    if plan.platform == 'windows' and '%' in str(destination):
        raise ManagementError('WinSW bundle directory may not contain expansion markers')
    if destination.exists():
        raise ManagementError('Service output already exists; choose a new directory')
    destination.mkdir(parents=True, mode=0o700)
    plan_path = destination / 'service-plan.json'
    plan_path.write_text(json.dumps({'schema': 1, **asdict(plan)}, indent=2) + '\n', encoding='utf-8')
    targets = ['controller', 'dedicated'] if plan.owns_dedicated else ['controller']
    for target in targets:
        name = plan.service_name(target)
        if plan.platform == 'windows':
            (destination / (name + '.xml')).write_text(render_winsw(plan, plan_path, target), encoding='utf-8')
        else:
            (destination / (name + '.service')).write_text(render_systemd(plan, plan_path, target), encoding='utf-8')
    if plan.platform == 'linux' and plan.owns_dedicated:
        unit = plan.dedicated_service + '.service'
        rule = ('polkit.addRule(function(action, subject) {\n'
                '  if (action.id === "org.freedesktop.systemd1.manage-units" &&\n'
                f'      subject.user === {json.dumps(plan.user)} &&\n'
                f'      action.lookup("unit") === {json.dumps(unit)} &&\n'
                '      action.lookup("verb") === "stop") return polkit.Result.YES;\n'
                '});\n')
        (destination / ('50-pyxaseco-' + plan.instance_id + '.rules')).write_text(rule, encoding='utf-8')
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in destination.iterdir() if path.is_file()}
    (destination / 'bundle-manifest.json').write_text(json.dumps({
        'schema': 1, 'winsw_version': WINSW_VERSION if plan.platform == 'windows' else None,
        'files': manifest}, indent=2) + '\n', encoding='utf-8')
    return plan_path


class ServiceAdapter:
    """Control only the instance named in an explicitly supplied service plan."""

    def __init__(self, plan: ServicePlan, *, runner=None):
        plan.validate()
        self.plan = plan
        self.runner = runner or subprocess.run

    def _run(self, command, timeout=65):
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=timeout,
                                 shell=False, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagementError('Service operation failed or timed out; inspect OS service status') from exc
        if result.returncode:
            raise ManagementError(f'OS service operation failed (code {result.returncode}); check permissions and registration')
        return result.stdout

    def status(self, target: str) -> dict:
        name = self.plan.service_name(target)
        if self.plan.platform == 'linux':
            text = self._run(['systemctl', '--no-ask-password', 'show', name + '.service',
                              '--property=LoadState,ActiveState,SubState,MainPID,Result,UnitFileState'], timeout=3)
            values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
            return {'service': name, 'registered': values.get('LoadState') == 'loaded',
                    'state': values.get('ActiveState', 'unknown'), 'detail': values.get('SubState', ''),
                    'pid': values.get('MainPID', '0'), 'result': values.get('Result', ''),
                    'startup': values.get('UnitFileState', 'unknown'), 'runtime_ready': 'unknown'}
        # QueryServiceStatusEx is locale-independent; do not scrape translated sc.exe text.
        return _windows_status(name)

    def action(self, target: str, action: str, *, confirmed: bool = False):
        if action not in {'start', 'stop', 'restart', 'enable', 'disable'}:
            raise ManagementError('Unsupported service action')
        if not confirmed:
            raise ManagementError('Service changes require --confirm; status/preparation are read-only')
        if self.plan.platform != ('windows' if os.name == 'nt' else 'linux'):
            raise ManagementError('Service plan targets another operating system')
        if target == 'both':
            if not self.plan.owns_dedicated:
                raise ManagementError('Dedicated service is not owned by this installation')
            if action == 'restart':
                self.action('both', 'stop', confirmed=True)
                return self.action('both', 'start', confirmed=True)
            targets = ('controller', 'dedicated') if action in {'stop', 'disable'} else ('dedicated', 'controller')
            for component in targets:
                self.action(component, action, confirmed=True)
            return {'action': action, 'components': list(targets)}
        name = self.plan.service_name(target)
        if self.plan.platform == 'linux':
            self._run(['systemctl', '--no-ask-password', action, name + '.service'])
        else:
            executable = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/sc.exe')
            if action == 'restart':
                self.action(target, 'stop', confirmed=True)
                return self.action(target, 'start', confirmed=True)
            if action in {'enable', 'disable'}:
                self._run([executable, 'config', name, 'start=', 'auto' if action == 'enable' else 'demand'])
            else:
                state = self.status(target)
                wanted = 'running' if action == 'start' else 'stopped'
                if state['state'] != wanted:
                    self._run([executable, action, name])
                deadline = time.monotonic() + 60
                while self.status(target)['state'] != wanted:
                    if time.monotonic() >= deadline:
                        raise ManagementError('Service transition timed out; no forced process termination issued')
                    time.sleep(.2)
        return {'action': action, 'service': name, 'os_request_completed': True,
                'runtime_ready': 'unknown (OS running does not prove controller readiness)'}


def _windows_status(name: str) -> dict:
    if os.name != 'nt':
        raise ManagementError('Windows service status requires Windows')
    import ctypes
    from ctypes import wintypes
    class Status(ctypes.Structure):
        _fields_ = [(key, wintypes.DWORD) for key in (
            'service_type', 'state', 'accepted', 'exit_code', 'specific_exit',
            'checkpoint', 'wait_hint', 'pid', 'flags')]
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenSCManagerW.restype = wintypes.HANDLE
    api.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenServiceW.restype = wintypes.HANDLE
    api.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    api.QueryServiceStatusEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    manager = api.OpenSCManagerW(None, None, 1)
    if not manager:
        raise ManagementError('Cannot query Windows service manager')
    try:
        service = api.OpenServiceW(manager, name, 4)
        if not service:
            if ctypes.get_last_error() == 1060:
                return {'service': name, 'registered': False, 'state': 'not-installed', 'runtime_ready': 'unknown'}
            raise ManagementError('Cannot query Windows service; access denied or unavailable')
        try:
            status, size = Status(), wintypes.DWORD()
            if not api.QueryServiceStatusEx(service, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(size)):
                raise ManagementError('Windows service status query failed')
            states = {1: 'stopped', 2: 'start-pending', 3: 'stop-pending', 4: 'running',
                      5: 'continue-pending', 6: 'pause-pending', 7: 'paused'}
            return {'service': name, 'registered': True, 'state': states.get(status.state, 'unknown'),
                    'pid': status.pid, 'exit_code': status.exit_code,
                    'specific_exit': status.specific_exit, 'runtime_ready': 'unknown', 'startup': 'unknown'}
        finally:
            api.CloseServiceHandle(service)
    finally:
        api.CloseServiceHandle(manager)


class ManagedLifecycle:
    def __init__(self, plan: ServicePlan):
        self.plan = plan
        self.manages_dedicated = plan.owns_dedicated

    async def stop_dedicated(self):
        return await asyncio.to_thread(ServiceAdapter(self.plan).action, 'dedicated', 'stop', confirmed=True)
