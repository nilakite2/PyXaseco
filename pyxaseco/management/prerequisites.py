"""Explicit prerequisite actions; imports and inspection never install or start services."""

import hashlib
import base64
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import urllib.request
from uuid import uuid4
import zipfile

from .config_store import ManagementError, file_lock


ASSETS = {
    'python': {'name': 'python-3.14.7-amd64.zip', 'version': '3.14.7',
        'url': 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.zip',
        'sha256': 'ac1a727a71738e11de80b76e975f9b8a258aea6412bfc31696b929d59c6aafd0'},
    'mariadb': {'name': 'mariadb-11.8.9-winx64.msi', 'version': '11.8.9',
        'url': 'https://archive.mariadb.org/mariadb-11.8.9/winx64-packages/mariadb-11.8.9-winx64.msi',
        'sha256': '372822572baa7f429b9068d583336a9e46b109c12bb0b24eb66dbeb6ad0a563e'},
}


def shared_root():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) if os.name == 'nt' else Path(
        os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    return base / 'PyXaseco'


def managed_python_default():
    return shared_root() / 'Runtimes' / ('Python-' + ASSETS['python']['version']) / 'python.exe'


def package_root():
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return root.parent if root.suffix == '.zip' else root


def asset(component, *, package=None, cache=None):
    from .installation import safe_path
    specification = ASSETS[component]
    bundled = Path(package or package_root()) / 'prerequisites' / specification['name']
    if bundled.is_file():
        result = safe_path(bundled)
    else:
        directory = safe_path(cache or shared_root() / 'Prerequisites')
        directory.mkdir(parents=True, exist_ok=True)
        result = directory / specification['name']
        with file_lock(directory / '.download.lock'):
            if not result.exists():
                temporary = directory / ('.download-' + uuid4().hex)
                try:
                    digest, size = hashlib.sha256(), 0
                    with urllib.request.urlopen(specification['url'], timeout=30) as source, temporary.open('xb') as target:
                        if not source.geturl().startswith('https://'):
                            raise ManagementError('Prerequisite downloads require HTTPS')
                        while data := source.read(1024 * 1024):
                            size += len(data)
                            if size > 256 * 1024 * 1024:
                                raise ManagementError('Prerequisite download exceeds its size limit')
                            digest.update(data)
                            target.write(data)
                    if digest.hexdigest() != specification['sha256']:
                        raise ManagementError('Prerequisite checksum does not match the pinned official package')
                    temporary.rename(result)
                finally:
                    temporary.unlink(missing_ok=True)
    if hashlib.sha256(result.read_bytes()).hexdigest() != specification['sha256']:
        raise ManagementError('Prerequisite package changed; obtain the matching official version')
    return result


def selected_python(python):
    if not str(python or '').strip():
        raise ManagementError('No Python is selected. Choose "Install a shared PyXaseco Python runtime" in setup, '
                              'or browse to an existing python.exe.')
    executable = Path(python).expanduser().absolute()
    if not executable.is_file():
        raise ManagementError('Python was not found at the selected location. If using the shared runtime, '
                              'it will be installed after Review installation and Install reviewed configuration. '
                              'You do not need to check its libraries first.')
    if (executable.name.lower() == 'pyxasecoadministrator.exe'
            or getattr(sys, 'frozen', False) and executable.resolve() == Path(sys.executable).resolve()):
        raise ManagementError('The Administrator Console is not the Python program used by controllers. '
                              'Choose the shared PyXaseco Python runtime instead.')
    return executable


def worker(python, request, *, source=None, timeout=30):
    from .installation import _run
    python = selected_python(python)
    root = Path(source or package_root())
    path = root / 'controller-payload.zip'
    if not path.is_file():
        path = root
    code = 'import sys; sys.path.insert(0,sys.argv[1]); from pyxaseco.management.bootstrap import main; raise SystemExit(main())'
    result = _run([str(python), '-I', '-B', '-c', code, str(path)], timeout=timeout,
                  capture=True, input_text=json.dumps(request), allow_failure=True)
    try:
        report = json.loads(result)
    except (ValueError, TypeError) as exc:
        raise ManagementError('Selected Python could not run prerequisite checks; check interpreter and permissions') from exc
    if 'error' in report:
        raise ManagementError(report['error'])
    return report


def dependency_report(python, requirements, *, source=None):
    return worker(python, {'action': 'dependencies', 'requirements': str(requirements)}, source=source)


def packaged_requirements():
    root = package_root()
    if (root / 'controller-payload.zip').is_file():
        with zipfile.ZipFile(root / 'controller-payload.zip') as archive:
            return archive.read('requirements.txt').decode('utf-8')
    return (root / 'requirements.txt').read_text(encoding='utf-8')


def ensure_dependencies(python, requirements, *, install=False, source=None):
    from .installation import _run
    report = dependency_report(python, requirements, source=source)
    if not report['supported']:
        raise ManagementError('The controller requires Python 3.12 or newer')
    if install and not report['ready']:
        if not report['isolated']:
            raise ManagementError('Library installation is restricted to an isolated controller environment, never global Python')
        _run([str(python), '-I', '-m', 'pip', 'install', '--disable-pip-version-check',
              '--no-input', '--only-binary=:all:', '-r', str(requirements)], timeout=600)
        report = dependency_report(python, requirements, source=source)
        if not report['ready']:
            raise ManagementError('Required libraries still fail version/import checks after installation')
        _run([str(python), '-I', '-m', 'pip', 'check'], timeout=30)
    return report


def database_action(python, environment, *, create=False, admin_user='', admin_password='', schema=None, source=None):
    settings = {key: value for key, value in environment.items() if key.startswith('DB_')}
    settings.update(admin_user=admin_user, admin_password=admin_password)
    return worker(python, {'action': 'database', 'settings': settings, 'create': create, 'schema': str(schema) if schema else None},
                  source=source, timeout=90)


def _signature(path, publisher):
    from .installation import _run
    powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # The path is data, never interpolated into the PowerShell program.
    code = '$ErrorActionPreference="Stop"; $p=[Console]::In.ReadToEnd(); $s=Get-AuthenticodeSignature -LiteralPath $p; [pscustomobject]@{Status=$s.Status.ToString();Signer=$s.SignerCertificate.Subject}|ConvertTo-Json -Compress'
    encoded = base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    report = json.loads(_run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            timeout=30, capture=True, input_text=str(Path(path).absolute())))
    if report['Status'] != 'Valid' or publisher not in (report.get('Signer') or ''):
        raise ManagementError('Prerequisite publisher signature is invalid or unexpected')


def install_managed_python(destination=None, *, package=None, cache=None):
    from .installation import _run, safe_path
    if os.name != 'nt':
        raise ManagementError('On Linux use the OS Python and the optional python3-venv prerequisite action')
    executable = safe_path(destination or managed_python_default())
    root = executable.parent
    if executable.name.lower() != 'python.exe':
        raise ManagementError('Managed runtime location must end with python.exe')
    root.parent.mkdir(parents=True, exist_ok=True)
    archive = asset('python', package=package, cache=cache)
    with file_lock(root.parent / '.python-install.lock'):
        if root.exists():
            marker = root / 'pyxaseco-runtime.json'
            if (not marker.is_file() or json.loads(marker.read_text()).get('sha256') != ASSETS['python']['sha256']
                    or not executable.is_file()):
                raise ManagementError('Managed runtime target is occupied; select the existing interpreter instead')
            _signature(executable, 'Python Software Foundation')
            _run([str(executable), '-I', '-c', 'import venv, ensurepip; print("ready")'], timeout=15)
            return {'python': str(executable), 'created': False}
        temporary = root.parent / ('.python-install-' + uuid4().hex)
        temporary.mkdir(mode=0o700)
        try:
            blob = archive.read_bytes()
            if hashlib.sha256(blob).hexdigest() != ASSETS['python']['sha256']:
                raise ManagementError('Managed runtime archive changed')
            with zipfile.ZipFile(io.BytesIO(blob)) as source:
                members = source.infolist()
                if len(members) > 30000 or sum(item.file_size for item in members) > 512 * 1024 * 1024:
                    raise ManagementError('Managed Python archive exceeds extraction limits')
                names = set()
                for item in members:
                    relative = PurePosixPath(item.filename)
                    if (relative.is_absolute() or '..' in relative.parts or '\\' in item.filename
                            or any(':' in part for part in relative.parts) or stat.S_ISLNK(item.external_attr >> 16)
                            or item.filename.casefold() in names):
                        raise ManagementError('Unsafe managed Python archive entry')
                    names.add(item.filename.casefold())
                    target = temporary.joinpath(*relative.parts)
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open('xb') as stream:
                            stream.write(source.read(item))
            _signature(temporary / 'python.exe', 'Python Software Foundation')
            _run([str(temporary / 'python.exe'), '-I', '-c', 'import venv, ensurepip, pip; print("ready")'], timeout=30)
            (temporary / 'pyxaseco-runtime.json').write_text(json.dumps(ASSETS['python'], indent=2) + '\n')
            temporary.rename(root)
            return {'python': str(executable), 'created': True}
        finally:
            if temporary.exists():
                safe_path(temporary)
                for path in temporary.rglob('*'):
                    safe_path(path)
                shutil.rmtree(temporary)


def database_services():
    from .installation import _run
    if os.name != 'nt':
        done = subprocess.run(['/usr/bin/systemctl', 'show', 'mariadb.service', '--property=LoadState,ActiveState'],
                              capture_output=True, text=True, timeout=5)
        return [{'name': 'mariadb', 'state': 'running' if 'ActiveState=active' in done.stdout else 'stopped'}] if 'LoadState=loaded' in done.stdout else []
    powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    code = "@(Get-CimInstance Win32_Service | Where-Object {$_.PathName -match 'mariadbd|mysqld'} | Select-Object @{n='name';e={$_.Name}},@{n='state';e={$_.State.ToLowerInvariant()}})|ConvertTo-Json -Compress"
    result = _run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', code], timeout=15, capture=True)
    data = json.loads(result) if result.strip() else []
    return [data] if isinstance(data, dict) else data or []


def installed_database_product():
    if os.name != 'nt':
        return False
    import winreg
    # A stopped/missing service does not prove MariaDB itself is absent.
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 0, winreg.KEY_READ | view) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, index)) as item:
                                name = winreg.QueryValueEx(item, 'DisplayName')[0]
                                if 'mariadb' in name.lower() or 'mysql server' in name.lower():
                                    return True
                        except OSError:
                            continue
            except OSError:
                continue
    return False


def _elevated_windows(file, parameters):
    import ctypes
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('mask', wintypes.ULONG), ('window', wintypes.HWND),
            ('verb', wintypes.LPCWSTR), ('file', wintypes.LPCWSTR), ('parameters', wintypes.LPCWSTR),
            ('directory', wintypes.LPCWSTR), ('show', ctypes.c_int), ('instance', wintypes.HINSTANCE),
            ('list', ctypes.c_void_p), ('class_name', wintypes.LPCWSTR), ('key', wintypes.HKEY),
            ('hotkey', wintypes.DWORD), ('icon', wintypes.HANDLE), ('process', wintypes.HANDLE)]
    shell, kernel = ctypes.WinDLL('shell32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(Info)]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = Info(); info.size = ctypes.sizeof(info); info.mask = 0x40
    info.verb = 'runas'; info.file = str(file); info.parameters = subprocess.list2cmdline(parameters); info.show = 1
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise ManagementError('Administrator approval was cancelled or the prerequisite could not start')
    try:
        if kernel.WaitForSingleObject(info.process, 1800000) != 0:
            raise ManagementError('Prerequisite installer is still running; inspect it before retrying')
        code = wintypes.DWORD(); kernel.GetExitCodeProcess(info.process, ctypes.byref(code))
        if code.value not in {0, 3010}:
            raise ManagementError('Prerequisite action failed or was cancelled (exit ' + str(code.value) + ')')
        return {'completed': True, 'restart_required': code.value == 3010}
    finally:
        kernel.CloseHandle(info.process)


def install_database_service(*, package=None, cache=None):
    if database_services() or installed_database_product():
        raise ManagementError('An existing MySQL/MariaDB installation was found. Reuse it; no second server was installed')
    if os.name == 'nt':
        path = asset('mariadb', package=package, cache=cache)
        _signature(path, 'MariaDB')
        executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/msiexec.exe'
        # Use vendor UI: root password is never put in argv, logs, presets or environment.
        return _elevated_windows(executable, ['/i', str(path), 'SERVICENAME=PyXasecoMariaDB'])
    return install_linux_packages('mariadb')


def install_linux_packages(component):
    packages = {'python': ['python3-venv'], 'mariadb': ['mariadb-server']}
    if os.name == 'nt' or component not in packages:
        raise ManagementError('Unsupported OS prerequisite choice')
    command = ['/usr/bin/apt-get', 'install', '--yes', '--no-upgrade', *packages[component]]
    if os.geteuid() != 0:
        if not Path('/usr/bin/pkexec').is_file():
            raise ManagementError('Install the OS prerequisite using apt with administrator privileges; pkexec is unavailable')
        command.insert(0, '/usr/bin/pkexec')
    done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=1200)
    if done.returncode:
        raise ManagementError('OS prerequisite installation failed or was cancelled; inspect the package manager')
    return {'completed': True, 'packages': packages[component]}


def start_database_service(name):
    services = database_services()
    if name not in {item['name'] for item in services}:
        raise ManagementError('Select an existing database service from a fresh inspection')
    if os.name == 'nt':
        executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/sc.exe'
        return _elevated_windows(executable, ['start', name])
    done = subprocess.run(['/usr/bin/pkexec', '/usr/bin/systemctl', 'start', name],
                          capture_output=True, timeout=60)
    if done.returncode:
        raise ManagementError('Database service start failed or was cancelled')
    return {'completed': True}
