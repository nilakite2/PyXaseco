"""Back up, compare and copy approved files. Restart remains the owner's //pyres."""

from __future__ import annotations

import difflib
import ast
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from .config_backup import backup_app_defaults
from .config_store import ManagementError, file_lock, revision
from .credentials import protect_token
from .installation import safe_path, _write
from .maintenance import _bytes, _replace, configuration_file
from .release_manifest import read_json, validate_archive


LEDGER = '.management-maintenance/file-releases.json'


def _hash(data):
    return revision(data) if data is not None else None


class FileUpdates:
    def __init__(self, root):
        self.root = safe_path(root)
        self.area = safe_path(self.root / '.management-maintenance')

    def _ledger(self):
        raw = _bytes(safe_path(self.root / LEDGER))
        data = read_json(raw) if raw is not None else {'schema': 1, 'controller': str(self.root), 'packages': {}}
        if (not isinstance(data, dict) or data.get('schema') != 1 or data.get('controller') != str(self.root)
                or not isinstance(data.get('packages'), dict)):
            raise ManagementError('Invalid local update history; keep it and review before updating')
        from .release_manifest import PUBLIC_APPS, package_path, version, FILE_LIMIT
        import re
        for identity, entry in data['packages'].items():
            if identity != 'controller' and identity not in PUBLIC_APPS:
                raise ManagementError('Unknown package in local update history')
            if not isinstance(entry, dict) or not isinstance(entry.get('files'), dict) or len(entry['files']) > 4096:
                raise ManagementError('Invalid local update inventory')
            version(entry.get('version'))
            for name, item in entry['files'].items():
                package_path(name, {'id': identity, 'kind': 'controller' if identity == 'controller' else 'app'})
                if (not isinstance(item, dict) or not isinstance(item.get('sha256'), str)
                        or not re.fullmatch('[0-9a-f]{64}', item['sha256'])
                        or type(item.get('size')) is not int or not 0 <= item['size'] <= FILE_LIMIT):
                    raise ManagementError('Invalid local update checksum')
        return data, raw

    def preview(self, package, blob, *, force=False):
        validate_archive(blob, package)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for name in package['files']:
                if name.endswith('.py'):
                    try:
                        ast.parse(archive.read(name), filename=name)
                    except (SyntaxError, ValueError) as error:
                        raise ManagementError('Invalid Python source in release: ' + name) from error
                elif name.endswith('.toml'):
                    import tomllib
                    try:
                        tomllib.loads(archive.read(name).decode('utf-8-sig'))
                    except (ValueError, UnicodeError) as error:
                        raise ManagementError('Invalid TOML configuration in release: ' + name) from error
        ledger, raw = self._ledger()
        previous = ledger['packages'].get(package['id'], {}).get('files', package.get('baseline', {}).get('files', {}))
        rows, snapshots = [], {LEDGER: _hash(raw)}
        for name in sorted(set(package['files']) | set(previous)):
            # Only paths authenticated by a package inventory may be considered.
            from .release_manifest import package_path
            package_path(name, package)
            current = _bytes(safe_path(self.root / name))
            before = _hash(current)
            snapshots[name] = before
            target = package['files'].get(name)
            old = previous.get(name)
            if target is None and configuration_file(name):
                action = 'preserve_config'
            elif target is not None and before == target['sha256']:
                action = 'unchanged'
            elif configuration_file(name) and (current is not None or old is not None):
                action = 'preserve_config'
            elif target is None and current is None:
                action = 'unchanged'
            elif current is None and old is None:
                action = 'add'
            elif old is not None and before == old['sha256']:
                action = 'replace' if target else 'remove'
            else:
                action = 'force_replace' if force and target else 'force_remove' if force else 'keep_modified'
            rows.append({'file': name, 'action': action, 'before': before,
                         'after': target['sha256'] if target else None})
        loadout = _bytes(safe_path(self.root / 'apps.toml')) if package['kind'] == 'app' else None
        if package['kind'] == 'app':
            snapshots['apps.toml'] = _hash(loadout)
        plan = {'package': package['id'], 'version': package['version'], 'force': force, 'files': rows,
                'ledger_before': _hash(raw), 'loadout_before': _hash(loadout),
                'modified': sum(row['action'] in {'keep_modified', 'force_replace', 'force_remove'} for row in rows),
                'review': revision(json.dumps({'root': str(self.root), 'package': package,
                    'snapshots': snapshots, 'force': force}, sort_keys=True).encode())}
        return plan

    def apply(self, package, blob, *, reviewed=None, force=False, confirmed=False):
        if confirmed is not True:
            raise ManagementError('Confirm file replacement first; no files changed')
        safe_path(self.area).mkdir(mode=0o700, exist_ok=True)
        with file_lock(safe_path(self.area / 'file-update.lock')):
            active = safe_path(self.area / 'active.json')
            if active.exists():
                raise ManagementError('A previous maintenance operation needs recovery first')
            plan = self.preview(package, blob, force=force)
            if reviewed is not None and reviewed != plan['review']:
                raise ManagementError('Files or release changed since review; open the review again')
            identity = uuid4().hex
            folder = safe_path(self.area / 'file-updates' / identity)
            folder.mkdir(parents=True, mode=0o700)
            backup = backup_app_defaults(self.root, folder / 'configuration', package['id'] + '-' + package['version'])
            ledger, ledger_raw = self._ledger()
            if _hash(ledger_raw) != plan['ledger_before']:
                raise ManagementError('Update history changed during backup; review again')
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                incoming = {name: archive.read(name) for name in package['files']}
            before_files, changes = {}, {}
            for row in plan['files']:
                name, action = row['file'], row['action']
                current = _bytes(safe_path(self.root / name))
                if _hash(current) != row['before']:
                    raise ManagementError('A file changed during backup; review again before copying')
                if action not in {'unchanged', 'preserve_config'}:
                    if current is not None:
                        _write(safe_path(folder / 'before' / name), current, private=True)
                    before_files[name] = current
                    difference = ''.join(difflib.unified_diff(
                        (current or b'').decode('utf-8', errors='replace').splitlines(keepends=True),
                        incoming.get(name, b'').decode('utf-8', errors='replace').splitlines(keepends=True),
                        fromfile='existing/' + name, tofile='release/' + name))
                    _write(safe_path(folder / 'diffs' / (name + '.diff')), difference.encode(), private=True)
                if action in {'add', 'replace', 'remove', 'force_replace', 'force_remove'}:
                    changes[name] = incoming.get(name)
            for name, data in incoming.items():
                if configuration_file(name):
                    _write(safe_path(folder / 'incoming-defaults' / name), data, private=True)
            if package['kind'] == 'app':
                import tomllib
                from .config_store import edit_toml
                original = _bytes(safe_path(self.root / 'apps.toml'))
                if _hash(original) != plan['loadout_before']:
                    raise ManagementError('App loadout changed during backup; review again')
                text = (original or b'').decode('utf-8')
                loadout = tomllib.loads(text).get('loadout', {})
                enabled, disabled = loadout.get('enabled', []), loadout.get('disabled', [])
                if not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
                           for items in (enabled, disabled)):
                    raise ManagementError('Invalid apps.toml loadout; no code changed')
                entry = 'app/' + package['id']
                if entry not in enabled and entry not in disabled:
                    before_files['apps.toml'] = original
                    changes['apps.toml'] = edit_toml(text, ('loadout', 'disabled'), disabled + [entry]).encode()
                    if original is not None:
                        _write(folder / 'before/apps.toml', original, private=True)
            ledger['packages'][package['id']] = {'version': package['version'], 'sha256': package['sha256'], 'files': package['files']}
            changes[LEDGER] = (json.dumps(ledger, indent=2) + '\n').encode()
            before_files[LEDGER] = ledger_raw
            report = dict(plan, backup=backup, state='prepared', copied=[])
            def save_report():
                path = folder / 'report.json'
                _replace(path, (json.dumps(report, indent=2) + '\n').encode(), _hash(_bytes(path)))
                protect_token(path)
            save_report()
            _replace(active, json.dumps({'id': identity, 'kind': 'file-update'}).encode(), None)
            protect_token(active)
            copied = []
            try:
                for name, data in changes.items():
                    _replace(safe_path(self.root / name), data, _hash(before_files.get(name)))
                    copied.append(name)
                report.update(state='copied', copied=copied)
                save_report()
                active.unlink()
            except Exception as error:
                try:
                    for name in reversed(copied):
                        _replace(safe_path(self.root / name), before_files.get(name), _hash(changes[name]))
                    report.update(state='rolled-back', copied=copied)
                    save_report()
                    active.unlink()
                except Exception:
                    report.update(state='recovery-required', copied=copied)
                    save_report()
                raise ManagementError('File update failed; keep the backup and report at ' + str(folder)) from error
            return {'package': package['id'], 'version': package['version'], 'report': str(folder / 'report.json'),
                    'copied': len(copied) - 1, 'kept_modified': sum(row['action'] == 'keep_modified' for row in plan['files']),
                    'restart_required': len(copied) > 1, 'started': False}
