"""Preview and move known generated files with the controller stopped."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .config_store import (
    LEGACY_MAINTENANCE, OUTBOX_NAME, OUTBOX_SUFFIXES, RUNTIME_LOCK, ManagementError,
    data_path, maintenance_area, outbox_path,
)
from .installation import safe_path
from .instances import controller_root
from .operations import ManagementOperations
from .release_manifest import package_path


@dataclass(frozen=True)
class Move:
    source: Path
    target: Path


def _plan(root):
    pending = safe_path(maintenance_area(root) / 'active.json')
    if pending.exists():
        raise ManagementError('Finish or recover the pending maintenance operation before migrating data')
    moves, skipped = [], []

    def add(source, target, *, directory=False):
        source = safe_path(source)
        if not source.exists():
            return
        if not source.is_relative_to(root) or not target.is_relative_to(root):
            raise ManagementError('Migration must stay inside the controller folder')
        if not (source.is_dir() if directory else source.is_file()):
            raise ManagementError('Unexpected generated data type: ' + str(source))
        if target.exists():
            raise ManagementError('Migration destination already exists: ' + str(target))
        moves.append(Move(source, target))

    for legacy, target in (
        (LEGACY_MAINTENANCE, ('management', 'maintenance')),
        ('.server-cleanup', ('backups', 'server-cleanup')),
        ('backups/dbtools', ('backups', 'dbtools')),
    ):
        add(root / legacy, data_path(root, *target), directory=True)

    outbox_path(root)  # Validate old/new database and sidecars before moving any data.
    state = safe_path(root / 'state')
    if state.is_dir():
        names = {path.name for path in state.iterdir()}
        outbox_files = {OUTBOX_NAME + suffix for suffix in (*OUTBOX_SUFFIXES, '.lock')}
        if names and names <= outbox_files:
            # Rename the group together so SQLite never loses its WAL on interruption.
            for name in names:
                if not safe_path(state / name).is_file():
                    raise ManagementError('Unexpected record outbox entry: ' + name)
            add(state, data_path(root, 'state'), directory=True)
        elif names & outbox_files:
            skipped.append('state/: contains other files; the existing record outbox was left in place')

    def scan(parent):
        relative = parent.relative_to(root).parts
        add(parent / '.management-backups',
            data_path(root, 'backups', 'legacy-configuration', *relative), directory=True)
        for entry in sorted(parent.glob('.*.lock')):
            if entry.name in (RUNTIME_LOCK, '.pyxaseco-launcher.lock'):
                continue
            name = '/'.join((*relative, entry.name[1:-5]))
            if name not in ('.env', 'installation.json', 'management.toml'):
                try:
                    package_path(name, {'id': 'controller', 'kind': 'controller', 'filename': 'full-release.zip'})
                except ManagementError:
                    continue
            add(entry, data_path(root, 'locks', 'legacy', *relative, entry.name))

    scan(root)
    for tree in ('apps', 'pyxaseco', 'database'):
        for current, dirs, _files in os.walk(safe_path(root / tree)):
            parent = Path(current)
            dirs[:] = sorted(name for name in dirs if not name.startswith('.')
                             and name not in ('__pycache__', 'player_huds')
                             and not (parent / name).is_symlink() and not (parent / name).is_junction())
            scan(parent)
    return moves, skipped


def migrate_data(folder, *, apply=False):
    root = controller_root(safe_path(folder))
    if not apply:
        moves, skipped = _plan(root)
    else:
        with ManagementOperations(root)._offline(True):
            moves, skipped = _plan(root)
            moved = []
            try:
                for move in moves:
                    move.target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    if safe_path(move.target).exists():
                        raise ManagementError('Migration destination appeared: ' + str(move.target))
                    safe_path(move.source).rename(move.target)
                    moved.append(move)
            except (OSError, ManagementError):
                for move in reversed(moved):
                    if move.source.exists():
                        raise ManagementError('Migration interrupted; new and old files are retained for review')
                    try:
                        move.target.rename(move.source)
                    except OSError as error:
                        raise ManagementError('Migration could not be reversed; moved files are retained for review') from error
                raise
    return {
        'applied': apply,
        'moves': [{'from': move.source.relative_to(root).as_posix(),
                   'to': move.target.relative_to(root).as_posix()} for move in moves],
        'skipped': skipped,
    }
