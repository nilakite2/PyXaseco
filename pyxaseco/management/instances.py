"""Explicit local instance registration; never import controller/app modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
import tomllib
from uuid import uuid4

from .config_store import ManagementError, update_file


def controller_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not (root / 'main.py').is_file() and (root / 'PyXaseco').is_dir():
        root = root / 'PyXaseco'
    if not all((root / name).exists() for name in ('main.py', 'pyxaseco', 'apps', 'config.toml')):
        raise ManagementError('Expected a PyXaseco controller folder or its dedicated-server parent')
    return root.resolve()


def read_dotenv(path: Path) -> dict[str, str]:
    """Match the controller's simple first-value-wins parser without touching env."""
    result = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            if key.strip():
                result.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return result


def configured_endpoint(root: Path) -> tuple[str, int]:
    env = read_dotenv(root / '.env')
    config = tomllib.loads((root / 'config.toml').read_text(encoding='utf-8'))
    tm = config.get('tmserver', {})
    host = str(env.get('TM_IP') or tm.get('ip') or '127.0.0.1').strip().lower()
    if host in ('localhost', '::1'):
        host = '127.0.0.1'
    port = int(env.get('TM_PORT') or tm.get('port') or 5000)
    if not 1 <= port <= 65535:
        raise ManagementError('XML-RPC port must be between 1 and 65535')
    return host, port


@dataclass(frozen=True)
class Instance:
    id: str
    name: str
    controller: str
    config: str
    python: str
    dedicated: str | None
    controller_service: str
    dedicated_service: str
    service_owned: bool = False


def default_registry() -> Path:
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return base / 'PyXaseco' / 'Administrator' / 'instances.json'


class InstanceRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_registry()

    @staticmethod
    def _decode(text: str) -> list[Instance]:
        data = json.loads(text) if text else {'version': 1, 'instances': []}
        if data.get('version') != 1 or not isinstance(data.get('instances'), list):
            raise ManagementError('Unsupported instance registry format')
        result = [Instance(**row) for row in data['instances']]
        if len({row.id for row in result}) != len(result):
            raise ManagementError('Duplicate IDs in instance registry')
        return result

    def list(self) -> list[Instance]:
        return self._decode(self.path.read_text(encoding='utf-8')) if self.path.exists() else []

    def get(self, identity: str) -> Instance:
        found = [row for row in self.list() if identity in (row.id, row.name)]
        if len(found) != 1:
            raise ManagementError('Instance not found or ambiguous; use the stable instance ID')
        return found[0]

    def register(self, path: str | Path, *, name: str, python: str | Path = sys.executable,
                 dedicated: str | Path | None = None) -> Instance:
        root = controller_root(path)
        if not name.strip() or len(name) > 100 or any(ord(char) < 32 for char in name):
            raise ManagementError('Instance name must be 1-100 printable characters')
        # A Linux venv interpreter is usually a symlink; resolving it loses the venv.
        executable = Path(python).expanduser().absolute()
        if not executable.is_file():
            raise ManagementError('Python executable does not exist')
        if getattr(sys, 'frozen', False) and executable.resolve() == Path(sys.executable).resolve():
            raise ManagementError('Select an external Python interpreter, not the bundled console executable')
        if dedicated is None:
            filename = 'TrackmaniaServer.exe' if os.name == 'nt' else 'TrackmaniaServer'
            candidate = root.parent / filename
            dedicated_path = candidate.resolve() if candidate.is_file() else None
        else:
            dedicated_path = Path(dedicated).expanduser().resolve()
            if not dedicated_path.is_file():
                raise ManagementError('Dedicated-server executable does not exist')
        endpoint = configured_endpoint(root)
        identity = uuid4().hex
        if (root / 'management.toml').exists():
            from .credentials import read_identity
            identity = read_identity(root)['instance_id']
        result = Instance(identity, name.strip(), str(root), str(root / 'config.toml'),
                          str(executable), str(dedicated_path) if dedicated_path else None,
                          'PyXaseco-' + identity, 'TMF-' + identity)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        def add(text):
            instances = self._decode(text)
            for row in instances:
                if row.id == identity:
                    raise ManagementError('This management identity is already registered; do not copy instance credentials')
                other = Path(row.controller).resolve()
                if other == root:
                    raise ManagementError('This controller folder is already registered')
                if row.name.casefold() == name.strip().casefold():
                    raise ManagementError('This instance name is already registered')
                if configured_endpoint(other) == endpoint:
                    raise ManagementError('Another registered controller targets this XML-RPC endpoint')
            instances.append(result)
            return json.dumps({'version': 1, 'instances': [asdict(row) for row in instances]}, indent=2) + '\n'
        update_file(self.path, add, validator=self._decode, backup=True)
        return result
