"""Offline management operations; no controller, app or provider imports."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import re
from pathlib import Path
import tomllib

from .app_policy import MANAGEABLE_STANDALONE_APPS, PROTECTED_STANDALONE_APPS, RELOADABLE_APPS
from .config_store import ConfigStore, ManagementError, edit_toml, runtime_lock, update_file
from .instances import configured_endpoint, controller_root, read_dotenv
from .editing import edit_dotenv, origin_hints, secret_key


@dataclass(frozen=True)
class AppInfo:
    id: str
    name: str
    configured_enabled: bool
    runtime_loaded: bool | None
    reload_declared: bool
    restart_required: bool
    protected: bool
    dependencies: tuple[str, ...]
    aliases: tuple[str, ...]
    metadata_error: str | None = None


def _metadata(path: Path) -> tuple[dict, bool]:
    return metadata_from_source(path.read_text(encoding='utf-8-sig'))


def metadata_from_source(source: str) -> tuple[dict, bool]:
    # Literal evaluation deliberately never imports or executes custom apps.
    module = ast.parse(source)
    value = None
    for node in module.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == 'APP_METADATA' for target in targets):
            value = node.value
            break
    data = ast.literal_eval(value) if value is not None else None
    if not isinstance(data, dict):
        raise ManagementError('APP_METADATA must be a literal table for offline validation')
    reloadable = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'reload_runtime'
                     for node in module.body)
    return data, reloadable


def _loadout(data: dict) -> tuple[list[str], list[str]]:
    loadout = data.get('loadout', {})
    enabled, disabled = loadout.get('enabled', []), loadout.get('disabled', [])
    for rows in (enabled, disabled):
        if not isinstance(rows, list) or any(not isinstance(row, str) or not re.fullmatch(r'app/[A-Za-z0-9_]+', row) for row in rows):
            raise ManagementError('Loadout must contain app/<name> lists')
        if len(rows) != len(set(rows)):
            raise ManagementError('Duplicate app in loadout')
    if set(enabled).intersection(disabled):
        raise ManagementError('App cannot be both enabled and disabled')
    return enabled, disabled


class ManagementOperations:
    def __init__(self, root: str | Path):
        self.root = controller_root(root)
        self.config = ConfigStore(self.root)

    def apps(self, loadout: dict | None = None, *, sources: dict | None = None) -> list[AppInfo]:
        if loadout is None:
            loadout = tomllib.loads((self.root / 'apps.toml').read_text(encoding='utf-8'))
        enabled, disabled = _loadout(loadout)
        names = {entry.split('/')[1] for entry in enabled + disabled}
        names.update(path.parent.name for path in (self.root / 'apps').glob('*/app.py')
                     if path.resolve().is_relative_to(self.root))
        sources = sources or {}
        names.update(parts[1] for name in sources
                     if len(parts := name.split('/')) == 3 and parts[0] == 'apps' and parts[2] == 'app.py')
        result = []
        for name in sorted(names):
            metadata, declares_reload, error = {}, False, None
            try:
                source = self.root / 'apps' / name / 'app.py'
                if not source.resolve().is_relative_to(self.root):
                    raise ManagementError('App source resolves outside the installation')
                key = f'apps/{name}/app.py'
                if key in sources:
                    if sources[key] is None:
                        raise ManagementError('App would be removed by the incoming release')
                    metadata, declares_reload = metadata_from_source(sources[key].decode('utf-8-sig'))
                else:
                    metadata, declares_reload = _metadata(source)
                if str(metadata.get('id', name)) != name:
                    raise ManagementError('App folder and metadata ID disagree')
                for field in ('depends_on', 'entries', 'provides'):
                    values = metadata.get(field, [])
                    if not isinstance(values, (list, tuple)) or any(not isinstance(item, str) for item in values):
                        raise ManagementError('Metadata dependency and alias fields must be string lists')
            except (OSError, SyntaxError, ValueError, TypeError):
                error = 'Missing, invalid or dynamic app metadata; not executed'
            aliases = (name, 'app/' + name, 'apps.' + name,
                       *metadata.get('entries', []), *metadata.get('provides', [])) if not error else ()
            result.append(AppInfo(name, str(metadata.get('display_name') or name), 'app/' + name in enabled,
                                  None, name in RELOADABLE_APPS and declares_reload, True,
                                  name in PROTECTED_STANDALONE_APPS,
                                  tuple(metadata.get('depends_on', [])) if not error else (),
                                  tuple(aliases), error))
        return result

    def validate(self, loadout: dict | None = None, *, sources: dict | None = None) -> dict:
        apps = self.apps(loadout, sources=sources)
        active = [app for app in apps if app.configured_enabled]
        available = {alias for app in active if not app.metadata_error for alias in app.aliases}
        errors = []
        for app in active:
            if app.metadata_error:
                errors.append(f'{app.id}: {app.metadata_error}')
            errors.extend(f'{app.id}: missing dependency {dep}' for dep in app.dependencies if dep not in available)
        return {'valid': not errors, 'errors': errors,
                'scope': 'TOML loadout and statically declared dependencies; no app startup or network checks'}

    def inspect(self) -> dict:
        host, port = configured_endpoint(self.root)
        return {'controller': str(self.root), 'configured_xmlrpc': {'host': host, 'port': port},
                'runtime_status': 'unknown (offline inspection only)',
                'apps': [asdict(app) for app in self.apps()], 'validation': self.validate()}

    def _offline(self, confirmed: bool):
        if not confirmed:
            raise ManagementError('Confirm the controller is stopped with --offline before writing')
        # An old, unmodified main.py cannot participate in the runtime lock.
        source = (self.root / 'main.py').read_text(encoding='utf-8-sig')
        if 'MANAGEMENT_RUNTIME_LOCK = 1' not in source:
            raise ManagementError('Read-only: this installation lacks the management runtime-lock entrypoint')
        return runtime_lock(self.root)

    def set_config(self, relative: str, path: tuple[str, ...], value, *, expected: str,
                   offline: bool = False):
        if self.config.path(relative).name == 'apps.toml':
            raise ManagementError('Use app-state for loadout changes so dependency/core checks are applied')
        with self._offline(offline):
            return self._save_config(relative, path, value, expected=expected)

    def validate_config_edit(self, relative: str, path: tuple[str, ...], value, *, expected: str):
        file = self.config.path(relative)
        if file.name == 'apps.toml':
            raise ManagementError('Use app-state for loadout changes')
        text, current = self.config.read(relative)
        if current != expected:
            raise ManagementError('Configuration changed since it was read; refresh before saving')
        if file.name == '.env':
            edit_dotenv(text, path, value)
            return
        old = tomllib.loads(text)
        for key in path:
            if not isinstance(old, dict) or key not in old:
                raise ManagementError('Edits require an existing setting')
            old = old[key]
        geometry = (len(file.relative_to(self.root).parts) == 3 and file.name == 'app_defaults.toml'
                    and path[-1] in {'pos_x', 'pos_y', 'x', 'y', 'width', 'height', 'row_height', 'offset_x', 'offset_y'})
        numeric_compatible = ((type(old) is float and type(value) is int)
                              or (geometry and type(old) is int and type(value) is float))
        if type(value) is not type(old) and not numeric_compatible:
            raise ManagementError('Value must retain the existing TOML type, including legacy string flags')
        if file.name == 'config.toml' and path in {('tmserver', 'port'), ('database', 'port')}:
            if type(value) is not int or not 1 <= value <= 65535:
                raise ManagementError('Port must be an integer between 1 and 65535')
        if file.name == 'config.toml' and path == ('tmserver', 'timeout') and value <= 0:
            raise ManagementError('XML-RPC timeout must be positive')
        edit_toml(text, path, value)

    def _save_config(self, relative, path, value, *, expected):
        """Caller owns offline exclusion OR runtime queue ordering."""
        self.validate_config_edit(relative, path, value, expected=expected)
        if self.config.path(relative).name == '.env':
            return update_file(self.config.path(relative), lambda text: edit_dotenv(text, path, value), expected=expected)
        return self.config.set_toml(relative, path, value, expected=expected)

    def backups(self, relative):
        file = self.config.path(relative)
        directory = file.parent / '.management-backups'
        if directory.is_symlink():
            raise ManagementError('Unsafe backup directory')
        return [path.name for path in sorted(directory.glob(file.name + '.*.bak'), reverse=True)
                if path.is_file() and not path.is_symlink()][:30]

    def restore_config(self, relative, backup, *, expected, offline=False):
        with self._offline(offline):
            return self._restore_config(relative, backup, expected=expected)

    def _restore_config(self, relative, backup, *, expected):
        file = self.config.path(relative)
        if file.name == 'apps.toml':
            raise ManagementError('Use app-state for loadout changes, not a whole-file restore')
        if backup not in self.backups(relative):
            raise ManagementError('Select an existing recent backup belonging to this file')
        saved = file.parent / '.management-backups' / backup
        if saved.stat().st_size > 4 * 1024 * 1024:
            raise ManagementError('Backup exceeds editing limit')
        text = saved.read_bytes().decode('utf-8')
        if file.suffix == '.toml':
            tomllib.loads(text)
        return update_file(file, lambda _old: text, expected=expected)

    def set_app_state(self, app_id: str, enabled: bool, *, expected: str, offline: bool = False):
        if app_id not in MANAGEABLE_STANDALONE_APPS or app_id in PROTECTED_STANDALONE_APPS:
            raise ManagementError('This app is protected or not managed as an optional standalone app')
        with self._offline(offline):
            return self._save_app_state(app_id, enabled, expected=expected)

    def _save_app_state(self, app_id, enabled, *, expected):
        if app_id not in MANAGEABLE_STANDALONE_APPS or app_id in PROTECTED_STANDALONE_APPS:
            raise ManagementError('This app is protected or not managed as an optional standalone app')
        if type(enabled) is not bool:
            raise ManagementError('App state must be a boolean')
        def transform(text):
            data = tomllib.loads(text)
            active, inactive = _loadout(data)
            info = next((app for app in self.apps(data) if app.id == app_id), None)
            if info is None or info.metadata_error:
                raise ManagementError('App must already be installed with readable static metadata')
            entry = 'app/' + app_id
            active = [item for item in active if item != entry]
            inactive = [item for item in inactive if item != entry]
            (active if enabled else inactive).append(entry)
            result = edit_toml(text, ('loadout', 'enabled'), active)
            return edit_toml(result, ('loadout', 'disabled'), inactive)
        def check(text):
            result = self.validate(tomllib.loads(text))
            if not result['valid']:
                raise ManagementError('; '.join(result['errors']))
        return update_file(self.root / 'apps.toml', transform, expected=expected, validator=check)


def masked(data):
    if isinstance(data, dict):
        return {key: masked(value) if isinstance(value, dict) else '********' if secret_key((key,)) else masked(value)
                for key, value in data.items()}
    if isinstance(data, list):
        return [masked(item) for item in data]
    return data


def read_config(operations: ManagementOperations, relative: str) -> dict:
    text, stamp = operations.config.read(relative)
    data = read_dotenv(operations.config.path(relative)) if relative == '.env' else tomllib.loads(text)
    return {'revision': stamp, 'values': masked(data), 'notes': origin_hints(relative)}
