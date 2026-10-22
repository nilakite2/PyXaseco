"""Fresh-install transactions shared by setup GUI and headless CLI. No server starts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import tomllib
from uuid import uuid4
import xml.etree.ElementTree as ET
import zipfile

from .config_store import ManagementError, file_lock, revision, update_file
from .editing import edit_dotenv
from .instances import InstanceRegistry, configured_endpoint, read_dotenv
from .operations import ManagementOperations


PLATFORM = 'windows' if os.name == 'nt' else 'linux'
ROOT_FILES = frozenset(('main.py', 'config.toml', 'apps.toml', 'adminops.toml',
    'bannedips.toml', 'messages.toml', 'nations.toml', 'settings.toml', '.env.example',
    'requirements.txt', 'requirements-admin.txt', 'PyXaseco.bat', 'PyXasecoAdmin.bat',
    'README.md', 'LICENSE'))
TREES = {'apps': {'.py', '.toml'}, 'pyxaseco': {'.py'}, 'database': {'.sql'},
         'administrator': {'.py', '.png'}}


def safe_path(path):
    """Reject symlinks/junctions before resolving, including existing ancestors."""
    path = Path(path).expanduser().absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ManagementError('Installation paths may not pass through links or junctions')
    return path.resolve()


def payload_path(name):
    parts = PurePosixPath(name).parts
    if (not parts or name != '/'.join(parts) or '\\' in name
            or any(part in {'.', '..'} or any(char in ':*?"<>|' or ord(char) < 32 for char in part) or part.endswith(('.', ' '))
                   or part.startswith('.') for part in parts)
            or any(part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                   *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))} for part in parts)):
        if name != '.env.example':
            raise ManagementError('Unsafe path in controller payload')
    if name in ROOT_FILES:
        return parts
    if (len(parts) < 2 or parts[0] not in TREES or '__pycache__' in parts
            or PurePosixPath(name).suffix not in TREES[parts[0]]):
        raise ManagementError('Unexpected file in controller payload')
    return parts


def read_payload(path, expected):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
        raise ManagementError('Supply the SHA256 from a trusted release/build record')
    file = safe_path(path)
    if file.stat().st_size > 64 * 1024 * 1024:
        raise ManagementError('Controller payload exceeds 64 MiB')
    blob = file.read_bytes()
    if revision(blob) != expected.lower():
        raise ManagementError('Controller payload does not match the reviewed SHA256')
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            if len(entries) > 4096 or sum(item.file_size for item in entries) > 128 * 1024 * 1024:
                raise ManagementError('Controller payload exceeds extraction limits')
            names = [item.filename for item in entries]
            if len({name.casefold() for name in names}) != len(names):
                raise ManagementError('Duplicate/case-colliding payload files')
            manifest = json.loads(archive.read('payload-manifest.json'))
            if manifest.get('schema') != 1 or manifest.get('version') != '1.3':
                raise ManagementError('Unsupported controller payload format')
            hashes = manifest['files']
            if set(names) != set(hashes) | {'payload-manifest.json'}:
                raise ManagementError('Payload inventory differs from its manifest')
            for item in entries:
                if item.filename == 'payload-manifest.json':
                    continue
                payload_path(item.filename)
                if stat.S_ISLNK(item.external_attr >> 16) or item.is_dir():
                    raise ManagementError('Payload may contain regular files only')
                data = archive.read(item)
                if revision(data) != hashes[item.filename]:
                    raise ManagementError('Payload file checksum mismatch')
                result[item.filename] = data
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, ManagementError):
            raise
        raise ManagementError('Invalid controller payload; contents omitted') from exc
    if not ROOT_FILES <= result.keys() or not all(name in result for name in
            ('pyxaseco/__init__.py', 'apps/ui/app.py', 'pyxaseco/management/__main__.py')):
        raise ManagementError('Controller payload is incomplete')
    return result


@dataclass(frozen=True)
class InstallRequest:
    payload: str
    sha256: str
    target: str
    name: str
    python: str
    mode: str = 'existing'
    dedicated_source: str = ''
    environment: dict = field(default_factory=dict, repr=False)
    disabled_apps: tuple[str, ...] = ()
    bridge: bool = False
    create_venv: bool = True
    install_dependencies: bool = False
    service_definitions: bool = False
    service_user: str = ''
    server_port: int = 2350
    p2p_port: int = 3450
    python_mode: str = 'existing'
    dedicated_settings: dict = field(default_factory=dict, repr=False)
    database_mode: str = 'existing'
    database_admin_user: str = ''
    database_admin_password: str = field(default='', repr=False)
    database_user_host: str = 'localhost'


def server_file_stem(name):
    value = name.strip()
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}', value)
            or value.endswith('.') or value.split('.')[0].upper() in {
                'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}):
        raise ManagementError('New-server names must be safe filenames: letters, numbers, spaces, _ . or -, '
                              'starting with a letter/number and not a reserved Windows name')
    return value


def dedicated_source(request):
    return safe_path(request.dedicated_source or Path(request.payload).parent / 'dedicated-template')


def _dedicated_files(root, *, platform=PLATFORM):
    names = ['TrackmaniaServer.exe', 'TrackmaniaServer']
    executable = root / names[0 if platform == 'windows' else 1]
    if not executable.is_file():
        raise ManagementError('Selected dedicated folder lacks this platform executable')
    expected = b'MZ' if platform == 'windows' else b'\x7fELF'
    with executable.open('rb') as stream:
        if stream.read(len(expected)) != expected:
            raise ManagementError('Dedicated executable does not match this platform')
    files = []
    for file in root.iterdir():
        if not file.name.lower().startswith('trackmaniaserver'):
            continue
        safe_path(file)
        if not file.is_file():
            raise ManagementError('Dedicated template server-prefixed entries must be regular files')
        if platform == 'windows' and (file.name == 'TrackmaniaServer' or file.suffix.lower() == '.sh'):
            continue
        if platform == 'linux' and file.suffix.lower() in {'.exe', '.bat', '.cmd'}:
            continue
        files.append(file)
    data = root / 'GameData'
    if not data.is_dir():
        raise ManagementError('Dedicated folder must contain GameData')
    for current, dirs, filenames in os.walk(data, followlinks=False):
        for name in dirs + filenames:
            safe_path(Path(current) / name)
        files.extend(Path(current) / name for name in filenames)
    if (len(files) > 10000 or sum(file.stat().st_size for file in files) > 512 * 1024 * 1024
            or any(not file.is_file() for file in files)):
        raise ManagementError('Dedicated template exceeds the proof installer limits')
    for required in ('GameData/Config/dedicated_cfg.txt', 'GameData/Tracks/MatchSettings/MatchSettings.txt'):
        if not (root / required).is_file():
            raise ManagementError('Dedicated template lacks dedicated_cfg.txt or MatchSettings.txt')
    return files, executable


def _dedicated_destination(relative, stem):
    if relative.name.lower().startswith('trackmaniaserver'):
        return relative.with_name(stem + relative.name[len('TrackmaniaServer'):])
    return relative


def _launch_script(stem, platform=PLATFORM):
    arguments = '/game_settings=MatchSettings/MatchSettings.txt /dedicated_cfg=dedicated_cfg.txt'
    if platform == 'windows':
        return (f'@echo off\r\ncd /d "%~dp0"\r\n"{stem}.exe" {arguments}\r\n').encode('ascii')
    return (f'#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec "./{stem}" {arguments} /nodaemon\n').encode('ascii')


def _rewrite_server_script(data, stem):
    # Match complete executable/script tokens, consuming any existing quotes before quoting spaces.
    text = data.decode('utf-8-sig')
    pattern = r'''(?i)(["']?)(\./)?TrackmaniaServer([A-Za-z0-9_.-]*)\1(?=\s|$)'''
    return re.sub(pattern, lambda match: '"' + (match[2] or '') + stem + match[3] + '"', text).encode('utf-8')


def _validate_new_target(target):
    safe_path(target)
    if not target.parent.is_dir():
        raise ManagementError('The destination parent folder does not exist; choose an existing parent')
    if target.exists():
        if not target.is_dir():
            raise ManagementError('The destination is a file; choose a new or empty folder')
        if next(target.iterdir(), None) is not None:
            raise ManagementError('The destination folder is not empty; choose a new or empty folder')


def preview(request: InstallRequest, registry: InstanceRegistry):
    if request.mode not in ('new', 'existing'):
        raise ManagementError('Select new or existing dedicated-server mode')
    for flag in (request.bridge, request.create_venv, request.install_dependencies, request.service_definitions):
        if type(flag) is not bool:
            raise ManagementError('Installer choices must be booleans')
    if request.install_dependencies and not request.create_venv:
        raise ManagementError('Dependency installation requires an isolated controller environment')
    # Explicit executable selections can be symlinks (normal for Linux Python/venvs).
    # Preserve the venv path; never relax link checks for installation write targets.
    target, python = safe_path(request.target), Path(request.python).expanduser().absolute()
    if request.python_mode not in {'existing', 'managed'}:
        raise ManagementError('Select an existing or managed Python runtime')
    if request.python_mode == 'managed' and os.name != 'nt':
        raise ManagementError('Linux uses the OS Python; install python3-venv through the prerequisite action')
    if request.python_mode == 'managed':
        safe_path(python)
        if python.name.lower() != 'python.exe' or python == target or target in python.parents:
            raise ManagementError('Choose a shared runtime outside the server folder, ending with python.exe')
    if request.python_mode == 'existing':
        from .prerequisites import selected_python
        selected_python(request.python)
    from .dedicated_settings import validate, public
    validate(request.dedicated_settings)
    if request.mode != 'new' and request.dedicated_settings:
        raise ManagementError('Dedicated settings are only applied to a new server; existing server files stay untouched')
    if request.database_mode not in {'existing', 'verify', 'create'}:
        raise ManagementError('Select existing, verify or create database mode')
    if request.database_mode == 'create':
        if not request.database_admin_user or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,253}', request.database_user_host):
            raise ManagementError('Creating a database requires an administrator login and an explicit allowed user host')
    if not request.name.strip() or len(request.name) > 100 or any(ord(char) < 32 for char in request.name):
        raise ManagementError('Supply a printable installation name (1-100 characters)')
    if request.mode == 'new':
        _validate_new_target(target)
        stem = server_file_stem(request.name)
        source = dedicated_source(request)
        files, executable = _dedicated_files(source)
        dedicated = target / _dedicated_destination(executable.relative_to(source), stem)
        dedicated_hashes = {file.relative_to(source).as_posix(): revision(file.read_bytes()) for file in files}
        destinations = [_dedicated_destination(file.relative_to(source), stem).as_posix().casefold() for file in files]
        if len(set(destinations)) != len(destinations):
            raise ManagementError('Renamed dedicated files would collide')
    else:
        if not target.is_dir():
            raise ManagementError('Existing-server mode requires an existing dedicated folder')
        dedicated = target / ('TrackmaniaServer.exe' if PLATFORM == 'windows' else 'TrackmaniaServer')
        if not dedicated.is_file():
            # Also recognize installations previously deployed with their instance name.
            dedicated = target / (server_file_stem(request.name) + ('.exe' if PLATFORM == 'windows' else ''))
            if not dedicated.is_file():
                raise ManagementError('Existing dedicated executable was not found')
        dedicated_hashes = {}
    if (target / 'PyXaseco').exists():
        raise ManagementError('A controller already exists here. Use Program maintenance to upgrade it')
    payload = read_payload(request.payload, request.sha256)
    from .app_policy import MANAGEABLE_STANDALONE_APPS, PROTECTED_STANDALONE_APPS
    if (not isinstance(request.disabled_apps, (tuple, list))
            or any(not isinstance(app, str) or app not in MANAGEABLE_STANDALONE_APPS
                   or app in PROTECTED_STANDALONE_APPS or 'apps/' + app + '/app.py' not in payload
                   for app in request.disabled_apps)):
        raise ManagementError('Initial app choices must be installed, supported optional apps')
    env_text = payload['.env.example'].decode('utf-8')
    for key, value in request.environment.items():
        env_text = edit_dotenv(env_text, (key,), value)
    effective = {}
    for line in env_text.splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            effective.setdefault(key.strip(), value.strip())
    if request.database_mode != 'existing':
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', effective.get('DB_NAME', '')):
            raise ManagementError('Use letters, numbers and underscores for the database name')
        if not 1 <= int(effective.get('DB_PORT') or 3306) <= 65535:
            raise ManagementError('Invalid database port')
    if request.database_mode == 'create':
        user = effective.get('DB_USER', '')
        if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', user)
                or user.lower() in {'root', 'admin', 'mysql', 'mariadb'}):
            raise ManagementError('Creating a database requires a new instance-specific user')
    if not effective.get('TM_PASSWORD') or not effective.get('MASTERADMIN_LOGINS'):
        raise ManagementError('XML-RPC password and at least one MasterAdmin login are required')
    if request.mode == 'new':
        if effective.get('TM_IP') not in ('127.0.0.1', 'localhost', '::1') or effective.get('TM_LOGIN') != 'SuperAdmin':
            raise ManagementError('New local servers require loopback XML-RPC and SuperAdmin')
        ports = [request.server_port, request.p2p_port, int(effective.get('TM_PORT') or 5000)]
        if any(type(port) is not int or not 1 <= port <= 65535 for port in ports) or len(set(ports)) != 3:
            raise ManagementError('Use three distinct valid game, P2P and XML-RPC ports')
        if not effective.get('DEDI_LOGIN') or not effective.get('DEDI_PASSWORD'):
            raise ManagementError('New servers require a TrackMania server-account login and password')
    endpoint = (effective.get('TM_IP', '127.0.0.1').lower(), int(effective.get('TM_PORT') or 5000))
    endpoint = ('127.0.0.1' if endpoint[0] in ('localhost', '::1') else endpoint[0], endpoint[1])
    for instance in registry.list():
        if instance.name.casefold() == request.name.strip().casefold() or configured_endpoint(Path(instance.controller)) == endpoint:
            raise ManagementError('Registered installation already uses that name or XML-RPC endpoint')
    if request.service_definitions:
        from .instances import Instance
        from .services import ServicePlan
        identity = '0' * 32
        item = Instance(identity, request.name, str(target / 'PyXaseco'),
            str(target / 'PyXaseco/config.toml'), str(python), str(dedicated),
            'PyXaseco-' + identity, 'TMF-' + identity)
        ServicePlan.from_instance(item, platform=PLATFORM, manage_dedicated=request.mode == 'new',
                                  user=request.service_user).validate()
    details = asdict(request)
    details['dedicated_hashes'] = dedicated_hashes
    if request.mode == 'new':
        details['target_exists'] = target.exists()
    details['registry_revision'] = revision(registry.path.read_bytes()) if registry.path.exists() else revision(b'')
    stamp = revision(json.dumps(details, sort_keys=True).encode())
    return {'review': stamp, 'mode': request.mode, 'target': str(target), 'controller': str(target / 'PyXaseco'),
        'dedicated': str(dedicated), 'platform': PLATFORM, 'name': request.name.strip(),
        'xmlrpc': f'{endpoint[0]}:{endpoint[1]}', 'payload_files': len(payload),
        'dedicated_files': len(dedicated_hashes), 'disabled_apps': list(request.disabled_apps),
        'dedicated_renames': {name: _dedicated_destination(Path(name), stem).as_posix()
                              for name in dedicated_hashes if Path(name).name.lower().startswith('trackmaniaserver')}
                              if request.mode == 'new' else {},
        'bridge': request.bridge, 'create_venv': request.create_venv,
        'install_dependencies': request.install_dependencies, 'service_definitions': request.service_definitions,
        'python_mode': request.python_mode,
        'dedicated_settings': public(request.dedicated_settings),
        'database': {'mode': request.database_mode, 'host': effective.get('DB_HOST', '127.0.0.1'),
                     'port': effective.get('DB_PORT', '3306'), 'name': effective.get('DB_NAME', ''),
                     'user': effective.get('DB_USER', ''), 'new_user_host': request.database_user_host,
                     'empty_password': not bool(effective.get('DB_PASSWORD'))},
        'changes': ['Create new PyXaseco folder; never merge over an existing controller',
                    'Copy/configure a new dedicated folder' if request.mode == 'new' else 'Leave dedicated files and MatchSettings untouched',
                    'Register in the selected local inventory; game/controller stay stopped',
                    'Create a fresh database and scoped user; initialize fresh tables only' if request.database_mode == 'create'
                        else 'Verify existing database access' if request.database_mode == 'verify' else 'Leave database provisioning to the operator'],
        'warnings': ['Occupied game ports are not probed. Database actions run only on approved apply.',
                     'Service definitions are review artifacts, not installed OS services.',
                     'Pinned requirements need installing before controller startup.' if not request.install_dependencies
                     else 'Approved dependency installation contacts the configured Python package index.']
                    + (['Passwordless database account selected; restrict its access to this computer.']
                       if not effective.get('DB_PASSWORD') else [])}


def _write(path, data, mode=0o600, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        os.chmod(path, mode)
        if private:
            from .credentials import protect_token
            protect_token(path)
        stream.write(data)


def _configure_dedicated(stage, request):
    file = stage / 'GameData/Config/dedicated_cfg.txt'
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(file, parser=parser)
    root = tree.getroot()
    env = request.environment
    replacements = {'masterserver_account/login': env['DEDI_LOGIN'],
        'masterserver_account/password': env['DEDI_PASSWORD'], 'server_options/name': request.name,
        'system_config/xmlrpc_port': env.get('TM_PORT') or '5000', 'system_config/xmlrpc_allowremote': 'False',
        'system_config/server_port': str(request.server_port), 'system_config/server_p2p_port': str(request.p2p_port)}
    for path, text in replacements.items():
        node = root.find(path)
        if node is None:
            raise ManagementError('Dedicated template is missing a required setting')
        node.text = text
    from .dedicated_settings import validate
    for path, value in validate(request.dedicated_settings).items():
        if path.startswith('authorization/'):
            continue
        node = root.find(path)
        if node is None:
            raise ManagementError('Dedicated template lacks setting: ' + path)
        node.text = str(value) if type(value) is not bool else ('True' if value else 'False')
    levels = root.findall('authorization_levels/level')
    if not any(level.findtext('name') == 'SuperAdmin' for level in levels):
        raise ManagementError('Dedicated template lacks SuperAdmin authorization')
    for level in levels:
        # Do not publish the template's well-known Admin/User credentials either.
        role = level.findtext('name')
        password = env['TM_PASSWORD'] if role == 'SuperAdmin' else (
            request.dedicated_settings.get('authorization/' + str(role).lower() + '_password') or uuid4().hex)
        level.find('password').text = password
    tree.write(file, encoding='utf-8', xml_declaration=True)
    os.chmod(file, 0o600)


_SPAWN_LOCK = threading.Lock()


def _spawn(arguments, **options):
    environment = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME'):
        environment.pop(name, None)
    if os.name == 'nt' and not isinstance(arguments, str) and Path(arguments[0]).name.lower() == 'powershell.exe':
        # A parent PowerShell 7 session can export modules incompatible with 5.1.
        environment['PSModulePath'] = str(Path(arguments[0]).parent / 'Modules')
    frozen = getattr(sys, 'frozen', False)
    if frozen:
        original = environment.pop('LD_LIBRARY_PATH_ORIG', '')
        environment.pop('LD_LIBRARY_PATH', None)
        if original:
            environment['LD_LIBRARY_PATH'] = original
        bundle = str(getattr(sys, '_MEIPASS', ''))
        environment['PATH'] = os.pathsep.join(part for part in environment.get('PATH', '').split(os.pathsep)
            if not bundle or not part.casefold().startswith(bundle.casefold()))
    with _SPAWN_LOCK:
        kernel, previous = None, None
        if frozen and os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
            previous = ctypes.create_unicode_buffer(32768)
            kernel.GetDllDirectoryW(len(previous), previous)
            kernel.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(arguments, env=environment, **options)
        finally:
            if kernel:
                kernel.SetDllDirectoryW(previous.value or None)


def _run(arguments, *, timeout, capture=False, input_text=None, allow_failure=False):
    process = None
    try:
        process = _spawn(arguments, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        output, _ = process.communicate(input=input_text, timeout=timeout)
        code = process.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        if process:
            process.kill()
            process.wait()
        raise ManagementError('Python prerequisite/dependency step failed or timed out; command output withheld') from exc
    if code and not allow_failure:
        raise ManagementError('Python prerequisite/dependency step failed; inspect the selected Python/package-index setup')
    return output


def apply(request: InstallRequest, registry: InstanceRegistry, *, reviewed: str):
    target = safe_path(request.target)
    lock_parent = target if request.mode == 'existing' else target.parent
    # Cooperative exclusion; installer targets must be controlled by the local operator.
    with file_lock(lock_parent / '.pyxaseco-install.lock'):
        plan = preview(request, registry)
        if reviewed != plan['review']:
            raise ManagementError('Installation inputs changed after review; preview again')
        python_path = Path(request.python).expanduser().absolute()
        if request.python_mode == 'managed':
            from .prerequisites import install_managed_python
            python_path = Path(install_managed_python(python_path)['python'])
        _run([str(python_path), '-I', '-c', 'import sys; sys.exit(0 if sys.version_info[0] == 3 and sys.version_info[1] >= 12 else 1)'], timeout=15)
        stage = lock_parent / ('.pyxaseco-install-' + uuid4().hex)
        stage.mkdir(mode=0o700)
        published = False
        controller = stage / 'PyXaseco'
        try:
            for name, data in read_payload(request.payload, request.sha256).items():
                _write(controller.joinpath(*payload_path(name)), data)
            env_text = (controller / '.env.example').read_text(encoding='utf-8')
            for key, value in request.environment.items():
                env_text = edit_dotenv(env_text, (key,), value)
            _write(controller / '.env', env_text.encode(), private=True)
            operations = ManagementOperations(controller)
            for app in request.disabled_apps:
                operations.set_app_state(app, False, expected=revision((controller / 'apps.toml').read_bytes()), offline=True)
            if not operations.validate()['valid']:
                raise ManagementError('Initial app loadout does not pass dependency validation')
            if request.bridge:
                from .credentials import initialize_bridge
                initialize_bridge(controller, enable=True, offline=True)
            if request.mode == 'new':
                stem = server_file_stem(request.name)
                source = dedicated_source(request)
                files, executable = _dedicated_files(source)
                for file in files:
                    relative = _dedicated_destination(file.relative_to(source), stem)
                    data = file.read_bytes()
                    script = file.suffix.lower() in {'.bat', '.cmd', '.sh'}
                    if script:
                        data = _rewrite_server_script(data, stem)
                    _write(stage / relative, data, 0o700 if file == executable or script else 0o600,
                           private=file.name == 'dedicated_cfg.txt')
                launcher = stage / (stem + ('.bat' if PLATFORM == 'windows' else '.sh'))
                # Standard launcher is independent of the caller's current directory.
                launcher.write_bytes(_launch_script(stem))
                os.chmod(launcher, 0o700)
                _configure_dedicated(stage, request)
            # Existing files are never replaced, including files created after preview.
            if request.mode == 'new':
                _validate_new_target(target)
                empty_target = target.exists()
                if empty_target:
                    target.rmdir()  # Nonrecursive: refuses if another process adds any entry.
                try:
                    stage.rename(target)
                except OSError:
                    if empty_target and not target.exists():
                        target.mkdir()
                    raise
            else:
                if (target / 'PyXaseco').exists():
                    raise ManagementError('Controller destination appeared during installation')
                controller.rename(target / 'PyXaseco')
            published = True
            controller = target / 'PyXaseco'
            python = python_path
            if request.create_venv:
                env = controller / '.venv-pyxaseco'
                _run([str(python), '-I', '-m', 'venv', str(env)], timeout=120)
                python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            instance = registry.register(controller, name=request.name, python=python, dedicated=plan['dedicated'])
            if PLATFORM == 'windows':
                launcher = controller / 'StartController.bat'
                _write(launcher, b'@echo off\r\ncd /d "%~dp0"\r\n' +
                       ('"' + str(python).replace('%', '%%') + '" main.py %*\r\nif errorlevel 1 pause\r\n').encode('utf-8'))
            else:
                import shlex
                launcher = controller / 'StartController.sh'
                _write(launcher, ('#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec ' +
                       shlex.quote(str(python)) + ' main.py "$@"\n').encode(), 0o700)
            from .prerequisites import ensure_dependencies, database_action
            libraries = ensure_dependencies(python, controller / 'requirements.txt', install=request.install_dependencies)
            database_result = {'ready': None, 'created': False, 'schema_initialized': False}
            if request.database_mode != 'existing':
                environment = {**read_dotenv(controller / '.env'), 'DB_USER_HOST': request.database_user_host}
                database_result = database_action(python, environment, create=request.database_mode == 'create',
                    admin_user=request.database_admin_user, admin_password=request.database_admin_password,
                    schema=controller / 'database/pyxaseco_default_schema.sql')
            definitions = None
            if request.service_definitions:
                from .services import ServicePlan, prepare_bundle
                service = ServicePlan.from_instance(instance, platform=PLATFORM,
                    manage_dedicated=request.mode == 'new', user=request.service_user)
                service.validate()
                definitions = str(prepare_bundle(service, controller / 'service-definitions'))
            from .maintenance import configuration_file
            payload = read_payload(request.payload, request.sha256)
            receipt = {'schema': 2, 'state': 'installed', 'instance_id': instance.id, 'payload_sha256': request.sha256.lower(),
                'mode': request.mode, 'controller': str(controller), 'python': str(python),
                'dedicated': plan['dedicated'],
                'dependencies_installed': request.install_dependencies, 'service_plan': definitions,
                'started': False, 'database_imported': database_result['schema_initialized'],
                'libraries': libraries, 'database': database_result,
                'payload_files': {name: revision(data) for name, data in payload.items()},
                'owned_files': {name: revision((controller / name).read_bytes()) for name in payload
                                if not configuration_file(name)}}
            update_file(controller / 'installation.json', lambda _text: json.dumps(receipt, indent=2) + '\n', backup=False)
            return receipt
        except Exception as exc:
            if published:
                raise ManagementError('Files were installed but a later setup step failed. Nothing was started. '
                    'Inspect the new PyXaseco folder and registry before continuing; existing server files were not replaced.') from exc
            raise
        finally:
            if stage.exists():
                # Never follow a changed junction/link during cleanup.
                safe_path(stage)
                for current, dirs, files in os.walk(stage, followlinks=False):
                    for name in dirs + files:
                        safe_path(Path(current) / name)
                if stage.parent == lock_parent and stage.name.startswith('.pyxaseco-install-'):
                    shutil.rmtree(stage)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='PyXaseco fresh installer (no GUI required)')
    parser.add_argument('--request', required=True, help='Private JSON request file, or - for standard input')
    parser.add_argument('--registry', help='Local instance inventory')
    parser.add_argument('--apply', metavar='REVIEW', help='Apply the exact review hash from a previous preview')
    args = parser.parse_args(argv)
    try:
        if args.request == '-':
            raw = sys.stdin.read(65537)
        else:
            with Path(args.request).open(encoding='utf-8') as stream:
                raw = stream.read(65537)
        if len(raw) > 65536:
            raise ManagementError('Installation request exceeds 64 KiB')
        request = InstallRequest(**json.loads(raw))
        registry = InstanceRegistry(args.registry)
        result = apply(request, registry, reviewed=args.apply) if args.apply else preview(request, registry)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, ManagementError) else f'Installer failed ({type(exc).__name__}); input contents omitted'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
