"""Complete app-default snapshots before program-file replacement."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from .config_store import ManagementError, revision
from .installation import safe_path, _write


def _defaults(root):
    result = {}
    apps = safe_path(root / 'apps')
    if not apps.is_dir():
        raise ManagementError('App configuration backup requires the apps folder')

    def failed(error):
        raise error

    for directory, folders, files in os.walk(apps, followlinks=False, onerror=failed):
        for folder in folders:
            safe_path(Path(directory) / folder)
        if 'app_defaults.toml' in files:
            path = safe_path(Path(directory) / 'app_defaults.toml')
            if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise ManagementError('An app_defaults.toml file cannot be safely backed up')
            name = path.relative_to(root).as_posix()
            result[name] = path
    return result


def backup_app_defaults(root, destination, release):
    """Failure aborts the caller before program writes. Existing snapshots are never merged."""
    root, destination = safe_path(root), safe_path(destination)
    if not re.fullmatch('[A-Za-z0-9._-]{1,100}', release):
        raise ManagementError('Invalid configuration backup release label')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = safe_path(destination / (stamp + '-' + release))
    if folder.is_relative_to(root / 'apps'):
        raise ManagementError('Backup destination must be outside the apps tree')
    paths = _defaults(root)
    folder.mkdir(parents=True, mode=0o700, exist_ok=False)
    hashes, total = {}, 0
    for name, source in paths.items():
        data = source.read_bytes()
        total += len(data)
        if len(data) > 16 * 1024 * 1024 or total > 128 * 1024 * 1024 or len(paths) > 4096:
            raise ManagementError('App configuration backup exceeds its safety limits')
        target = safe_path(folder / name)
        _write(target, data, private=True)
        digest = revision(data)
        if revision(target.read_bytes()) != digest:
            raise ManagementError('App configuration backup verification failed')
        hashes[name] = digest
    current = _defaults(root)
    if set(current) != set(paths) or any(revision(path.read_bytes()) != hashes[name] for name, path in current.items()):
        raise ManagementError('App configuration changed during backup; review and retry the update')
    manifest = {'schema': 1, 'created_utc': stamp, 'release': release, 'files': hashes}
    _write(folder / 'backup.json', (json.dumps(manifest, indent=2) + '\n').encode(), private=True)
    return {'folder': str(folder), 'files': len(hashes), 'release': release}
