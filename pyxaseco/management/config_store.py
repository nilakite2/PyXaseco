"""Locked, revision-checked configuration writes without third-party dependencies."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib
from uuid import uuid4


MANAGEMENT_MAINTENANCE_LOCK = 1
DATA_DIR = '.pyxaseco-data'
LEGACY_MAINTENANCE = '.management-maintenance'
RUNTIME_LOCK = '.pyxaseco-runtime.lock'
OUTBOX_NAME = 'record_outbox.sqlite3'
OUTBOX_SUFFIXES = ('', '-wal', '-shm', '-journal')


class ManagementError(ValueError):
    """An operation was refused without intentionally changing configuration."""


def data_path(root: Path, *parts: str) -> Path:
    """Resolve a controller-owned path without following links inside the instance."""
    root = Path(root).resolve()
    target = root / DATA_DIR / Path(*parts)
    if '..' in target.parts or not target.is_relative_to(root / DATA_DIR):
        raise ManagementError('Generated data path must stay inside the instance')
    for path in (target, *target.parents):
        if path == root:
            break
        if path.is_symlink() or path.is_junction():
            raise ManagementError('Generated data paths may not pass through links or junctions')
    return target


def generated_directory(root: Path, legacy: str, *parts: str) -> Path:
    """Use the old directory until an offline migration moves it as a unit."""
    root = Path(root).resolve()
    old = root / legacy
    new = data_path(root, *parts)
    for path in (old, new):
        if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)
               if parent.is_relative_to(root)) or (path.exists() and not path.is_dir()):
            raise ManagementError('Unsafe generated data directory: ' + str(path))
    if old.exists() and new.exists():
        raise ManagementError('Both old and new generated data directories exist: ' + legacy)
    return old if old.exists() else new


def maintenance_area(root: Path) -> Path:
    return generated_directory(root, LEGACY_MAINTENANCE, 'management', 'maintenance')


def cleanup_backup_directory(root: Path) -> Path:
    return generated_directory(root, '.server-cleanup', 'backups', 'server-cleanup')


def outbox_path(root: Path) -> Path:
    # Keep SQLite sidecars with the database until the offline migration.
    primary = data_path(root, 'state', OUTBOX_NAME)
    legacy = Path(root).resolve() / 'state' / primary.name
    if legacy.parent.is_symlink() or legacy.parent.is_junction():
        raise ManagementError('Unsafe legacy record outbox directory')
    for database in (legacy, primary):
        group = tuple(database.with_name(database.name + suffix) for suffix in OUTBOX_SUFFIXES)
        if any(path.is_symlink() or path.is_junction() or (path.exists() and not path.is_file()) for path in group):
            raise ManagementError('Unsafe record outbox file')
        if not group[0].exists() and any(path.exists() for path in group[1:]):
            raise ManagementError('Record outbox sidecar exists without its database')
    if legacy.exists() and primary.exists():
        raise ManagementError('Both old and new record outboxes exist; reconcile before starting')
    return legacy if legacy.exists() else primary


def controller_config_root(path: Path) -> Path | None:
    # Generic writers also serve the external installation registry.
    parents = (path.parent, *path.parents[1:]) if 'apps' in path.parts else (path.parent,)
    for root in parents:
        relative = path.relative_to(root)
        if (len(relative.parts) == 1 or relative.parts[0] == 'apps') and (
                (root / 'config.toml').is_file() and (root / 'apps.toml').is_file()):
            return root
    return None


def managed_lock_path(root: Path, path: Path, *, adjacent=True) -> Path:
    relative = path.relative_to(Path(root).resolve())
    filename = '.' + relative.name + '.lock' if adjacent else relative.name
    folder = relative.parts[:-1]
    if folder[:1] == (DATA_DIR,):
        folder = folder[1:]
    return data_path(root, 'locks', *folder, filename)


def config_backup_directory(root: Path, path: Path, *, legacy=False) -> Path:
    group = 'legacy-configuration' if legacy else 'configuration'
    return data_path(root, 'backups', group, *path.relative_to(Path(root).resolve()).parts[:-1])


def instance_lock(root: Path, path: Path, *, adjacent=True):
    lock = managed_lock_path(root, path, adjacent=adjacent)
    lock.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    return file_lock(lock)


def revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@contextmanager
def file_lock(path: Path):
    """Nonblocking OS lock. Keep the lock file: deleting it introduces races."""
    if path.is_symlink() or path.is_junction():
        raise ManagementError('Lock files may not be symbolic links')
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    handle = os.fdopen(fd, 'r+b')
    locked = False
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(fd).st_size == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ManagementError('Installation or configuration is busy; retry after it stops') from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ManagementError('Installation or configuration is busy; retry after it stops') from exc
        locked = True
        yield
    finally:
        if locked:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        handle.close()


@contextmanager
def runtime_lock(root: Path):
    with file_lock(root / RUNTIME_LOCK):
        pending = maintenance_area(root) / 'active.json'
        if pending.exists() or pending.is_symlink() or pending.is_junction():
            raise ManagementError('Interrupted maintenance is pending; review and roll back before starting or editing')
        yield


@dataclass(frozen=True)
class WriteResult:
    revision: str
    backup: str | None
    changed: bool


def update_file(path: Path, transform, *, expected: str | None = None,
                validator=None, backup: bool = True, root: Path | None = None) -> WriteResult:
    """Transform under a shared lock; never silently overwrite a stale snapshot."""
    path = Path(path).absolute()
    if path.is_symlink() or path.is_junction():
        raise ManagementError('Configuration files may not be symbolic links')
    root = Path(root).resolve() if root is not None else controller_config_root(path)
    lock = instance_lock(root, path) if root is not None else file_lock(path.with_name('.' + path.name + '.lock'))
    with lock:
        existed = path.exists()
        before = path.read_bytes() if existed else b''
        if len(before) > 4 * 1024 * 1024:
            raise ManagementError('Configuration exceeds the 4 MiB editing limit')
        old_revision = revision(before)
        if expected is not None and expected != old_revision:
            raise ManagementError('Configuration changed since it was read; refresh before saving')
        after = transform(before.decode('utf-8'))
        if not isinstance(after, str):
            raise TypeError('Configuration transform must return text')
        encoded = after.encode('utf-8')
        if len(encoded) > 4 * 1024 * 1024:
            raise ManagementError('Configuration exceeds the 4 MiB editing limit')
        if validator is not None:
            validator(after)
        if encoded == before and existed:
            return WriteResult(old_revision, None, False)
        mode = stat.S_IMODE(path.stat().st_mode) if existed else 0o600
        backup_path = None
        if backup and existed:
            directory = config_backup_directory(root, path) if root is not None else path.parent / '.management-backups'
            if directory.is_symlink():
                raise ManagementError('Backup directory may not be a symbolic link')
            directory.mkdir(parents=root is not None, mode=0o700, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup_path = directory / f'{path.name}.{stamp}.{uuid4().hex[:8]}.bak'
            with backup_path.open('xb') as saved:
                os.chmod(backup_path, 0o600)
                saved.write(before)
                saved.flush()
                os.fsync(saved.fileno())
        fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            # POSIX mode preservation; Windows replacements inherit the directory ACL.
            os.chmod(temporary, mode)
            if path.is_symlink() or path.exists() != existed or (existed and path.read_bytes() != before):
                raise ManagementError('External editor changed configuration during save; refresh')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return WriteResult(revision(encoded), str(backup_path) if backup_path else None, True)


def format_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return '[' + ', '.join(format_value(item) for item in value) + ']'
    raise ManagementError('Supported values are strings, booleans, finite numbers and arrays')


def _key(value: str) -> str:
    return value if re.fullmatch(r'[A-Za-z0-9_-]+', value) else json.dumps(value)


def _syntax(text: str):
    """Yield characters outside TOML strings, skipping comment contents."""
    index = 0
    while index < len(text):
        char = text[index]
        if char in ('"', "'"):
            delimiter = char * 3 if text.startswith(char * 3, index) else char
            index += len(delimiter)
            while index < len(text):
                if char == '"' and text[index] == '\\':
                    index += 2
                elif text.startswith(delimiter, index):
                    index += len(delimiter)
                    if len(delimiter) == 3:
                        while index < len(text) and text[index] == char:
                            index += 1
                    break
                else:
                    index += 1
            continue
        yield index, char
        if char == '#':
            newline = text.find('\n', index)
            index = len(text) if newline < 0 else newline
        else:
            index += 1


def _statements(text: str):
    start, depth = 0, 0
    for index, char in _syntax(text):
        if char in '[{':
            depth += 1
        elif char in ']}':
            depth -= 1
        elif char == '\n' and depth == 0:
            yield start, index + 1, text[start:index + 1]
            start = index + 1
    if start < len(text):
        yield start, len(text), text[start:]


def _leaf_path(data: dict) -> tuple[str, ...]:
    parts = []
    while isinstance(data, dict) and len(data) == 1:
        name, data = next(iter(data.items()))
        parts.append(name)
    return tuple(parts)


def edit_toml(text: str, path: tuple[str, ...], value) -> str:
    """Edit one scalar/array while retaining unrelated text and comments."""
    if not path or not all(isinstance(key, str) and key for key in path):
        raise ManagementError('Setting path must contain nonempty keys')
    original = tomllib.loads(text)
    wanted = deepcopy(original)
    node = wanted
    for key in path[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise ManagementError('Setting parent is not a TOML table')
    node[path[-1]] = value
    encoded = format_value(value)
    section, insertion, match = (), None, None
    newline = '\r\n' if '\r\n' in text else '\n'
    for start, end, statement in _statements(text):
        stripped = statement.lstrip()
        if stripped.startswith('['):
            if section == path[:-1] and insertion is None:
                insertion = start
            # Array-of-table members require a raw-document edit instead.
            section = None if stripped.startswith('[[') else _leaf_path(tomllib.loads(statement))
            continue
        if not stripped or stripped.startswith('#') or section is None:
            continue
        equals = next((i for i, char in _syntax(statement) if char == '='), None)
        if equals is None:
            continue
        local_path = _leaf_path(tomllib.loads(statement[:equals] + '= 0'))
        if (*section, *local_path) != path:
            continue
        begin = equals + 1
        while begin < len(statement) and statement[begin] in ' \t':
            begin += 1
        finish, depth = len(statement), 0
        comments = []
        for i, char in _syntax(statement[begin:]):
            offset = begin + i
            if char == '#' and depth == 0:
                finish = offset
                break
            if char == '#':
                comments.append(statement[offset:statement.find('\n', offset)].rstrip('\r'))
            elif char in '[{':
                depth += 1
            elif char in ']}':
                depth -= 1
        finish = len(statement[:finish].rstrip())
        replacement = encoded
        if comments and isinstance(value, list):
            replacement = '[' + newline + ''.join('    ' + c + newline for c in comments)
            replacement += ''.join('    ' + format_value(item) + ',' + newline for item in value) + ']'
        match = (start + begin, start + finish, replacement)
        break
    if match:
        begin, finish, replacement = match
        result = text[:begin] + replacement + text[finish:]
    else:
        # Insert before the following table, or append an explicitly named table.
        section_exists = path[:-1] == ()
        for _start, _end, statement in _statements(text):
            stripped = statement.lstrip()
            if stripped.startswith('[') and not stripped.startswith('[['):
                section_exists |= _leaf_path(tomllib.loads(statement)) == path[:-1]
        line = _key(path[-1]) + ' = ' + encoded + newline
        if section_exists:
            insertion = len(text) if insertion is None else insertion
            prefix = '' if insertion == 0 or text[:insertion].endswith('\n') else newline
            result = text[:insertion] + prefix + line + text[insertion:]
        else:
            header = '[' + '.'.join(_key(key) for key in path[:-1]) + ']' + newline
            result = text + (newline if text.endswith('\n') else newline * 2) + header + line
    if tomllib.loads(result) != wanted:
        raise ManagementError('Unsupported TOML edit; original file was not changed')
    return result


def remove_toml_value(text: str, path: tuple[str, ...]) -> str:
    """Remove one value while preserving unrelated TOML and comments."""
    if not path or not all(isinstance(key, str) and key for key in path):
        raise ManagementError('Setting path must contain nonempty keys')
    wanted = deepcopy(tomllib.loads(text))
    node = wanted
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, dict) or path[-1] not in node:
        raise ManagementError('Setting does not exist')
    if isinstance(node[path[-1]], dict):
        raise ManagementError('Removing whole tables is not supported')
    del node[path[-1]]
    section = ()
    for start, end, statement in _statements(text):
        stripped = statement.lstrip()
        if stripped.startswith('['):
            section = None if stripped.startswith('[[') else _leaf_path(tomllib.loads(statement))
            continue
        if not stripped or stripped.startswith('#') or section is None:
            continue
        equals = next((i for i, char in _syntax(statement) if char == '='), None)
        if equals is None:
            continue
        local_path = _leaf_path(tomllib.loads(statement[:equals] + '= 0'))
        if (*section, *local_path) == path:
            result = text[:start] + text[end:]
            if tomllib.loads(result) == wanted:
                return result
            break
    raise ManagementError('Unsupported TOML removal; original file was not changed')


class ConfigStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def path(self, relative: str) -> Path:
        candidate = self.root / relative
        path = candidate.resolve()
        if not path.is_relative_to(self.root) or candidate.is_symlink() or path == self.root:
            raise ManagementError('Configuration path must stay inside the installation')
        rel = path.relative_to(self.root)
        allowed = (len(rel.parts) == 1 and (rel.suffix == '.toml' or rel.name == '.env'))
        allowed |= len(rel.parts) == 3 and rel.parts[0] == 'apps' and rel.name == 'app_defaults.toml'
        if not allowed:
            raise ManagementError('Only root configuration and app_defaults.toml files are editable')
        return path

    def read(self, relative: str) -> tuple[str, str]:
        content = self.path(relative).read_bytes()
        if len(content) > 4 * 1024 * 1024:
            raise ManagementError('Configuration exceeds the 4 MiB editing limit')
        return content.decode('utf-8'), revision(content)

    def set_toml(self, relative: str, path: tuple[str, ...], value, *, expected: str,
                 validate=None) -> WriteResult:
        file = self.path(relative)
        if file.suffix != '.toml':
            raise ManagementError('This operation edits TOML only')
        def check(text):
            data = tomllib.loads(text)
            if validate:
                validate(data)
        return update_file(file, lambda text: edit_toml(text, path, value),
                           expected=expected, validator=check, root=self.root)
