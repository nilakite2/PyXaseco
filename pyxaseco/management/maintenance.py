"""Stopped-controller, ownership-checked program maintenance. Never manages DB data."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from uuid import uuid4

from .config_store import ManagementError, file_lock, revision
from .credentials import protect_token
from .installation import PLATFORM, _write, payload_path, read_payload, safe_path
from .instances import Instance
from .operations import ManagementOperations
from .services import ServiceAdapter, ServicePlan


RECEIPT = 'installation.json'
AREA = '.management-maintenance'
GUARD = 'pyxaseco/management/config_store.py'
LIMIT = 16 * 1024 * 1024


def configuration_file(name):
    return name.endswith('.toml') or name == '.env.example'


def _json(data):
    return (json.dumps(data, sort_keys=True, indent=2) + '\n').encode()


def _bytes(path):
    safe_path(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise ManagementError('Maintenance input is not a regular file within the size limit')
    return path.read_bytes()


def _hash(data):
    return revision(data) if data is not None else None


def _replace(path, data, expected, *, lock_path=None):
    """Atomic binary program-file replacement; config edits use ConfigStore instead."""
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(safe_path(lock_path) if lock_path is not None else path.with_name('.' + path.name + '.lock')):
        before = _bytes(path)
        if _hash(before) != expected:
            raise ManagementError('A maintenance target changed; nothing was overwritten at that path')
        if data is None:
            path.unlink(missing_ok=True)
            return
        fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode) if before is not None else 0o600)
            if _hash(_bytes(path)) != expected:
                raise ManagementError('External editor changed a maintenance target; refresh')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class Maintenance:
    def __init__(self, instance: Instance, *, service_probe=None):
        self.instance = instance
        self.root = safe_path(instance.controller)
        if not self.root.is_dir():
            raise ManagementError('Controller/data folder no longer exists')
        self.area = self.root / AREA
        safe_path(self.area)
        self.service_probe = service_probe or self._service_status

    def _service_status(self):
        plan = ServicePlan.from_instance(self.instance, platform=PLATFORM)
        return ServiceAdapter(plan).status('controller')

    def _check_service(self, uninstall=False):
        status = self.service_probe()
        if status.get('registered') is False:
            return
        if uninstall:
            raise ManagementError('Remove the controller OS service explicitly before removing its program files')
        if status.get('registered') is not True or status.get('state') != 'stopped':
            raise ManagementError('Controller OS service must be confirmed stopped; unknown is not stopped')

    def _path(self, name):
        if name != RECEIPT:
            payload_path(name)
        return safe_path(self.root / name)

    def _receipt(self):
        raw = _bytes(self.root / RECEIPT)
        if raw is None:
            raise ManagementError('No ownership receipt. Review explicit baseline adoption first')
        receipt = json.loads(raw)
        if (receipt.get('schema') != 2 or receipt.get('instance_id') != self.instance.id
                or safe_path(receipt.get('controller', '')) != self.root):
            raise ManagementError('Ownership receipt missing/old or belongs to another installation; explicit adoption required')
        for field in ('owned_files', 'payload_files'):
            entries = receipt.get(field)
            if (not isinstance(entries, dict) or len(entries) > 4096
                    or len(entries) != len({name.casefold() for name in entries})):
                raise ManagementError('Invalid ownership inventory')
            for name, digest in entries.items():
                payload_path(name)
                if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise ManagementError('Invalid ownership checksum')
                if field == 'owned_files' and configuration_file(name):
                    raise ManagementError('Mutable configuration cannot be owned as replaceable program code')
        if any(receipt['payload_files'].get(name) != digest for name, digest in receipt['owned_files'].items()):
            raise ManagementError('Owned program checksum differs from its recorded release inventory')
        return receipt, raw

    @contextmanager
    def _locked(self, *, recovery=None):
        # Bypass the runtime pending-marker guard only here, while retaining the OS lock.
        with file_lock(self.root / '.pyxaseco-runtime.lock'):
            self._check_service()
            active = _bytes(self.area / 'active.json')
            if active is not None and (recovery is None or json.loads(active).get('id') != recovery):
                raise ManagementError('A pending maintenance transaction must be rolled back first')
            yield

    def _plan(self, action, payload=None, digest=None):
        receipt, raw = self._receipt()
        if receipt.get('state') != 'installed':
            raise ManagementError('Program files are removed; use the retained uninstall rollback first')
        owned = receipt['owned_files']
        preserved, conflicts, snapshots, changes = [], [], {}, {}
        for name, old in owned.items():
            current = _bytes(self._path(name))
            snapshots[name] = _hash(current)
            if _hash(current) != old:
                (preserved if action == 'uninstall' else conflicts).append(name)
        if action == 'upgrade':
            guard = payload.get(GUARD, b'')
            if b'MANAGEMENT_MAINTENANCE_LOCK = 1' not in guard:
                raise ManagementError('Upgrade payload lacks interrupted-maintenance startup protection')
            old_apps = {name.split('/')[1] for name in receipt['payload_files'] if name.startswith('apps/')}
            custom = {path.name for path in (self.root / 'apps').iterdir() if path.is_dir() and path.name not in old_apps}
            for name, data in payload.items():
                if name.startswith('apps/') and name.split('/')[1] in custom:
                    conflicts.append(name)
                    continue
                current = _bytes(self._path(name))
                snapshots[name] = _hash(current)
                if configuration_file(name):
                    # Existing values AND intentionally deleted old config remain the operator's choice.
                    if current is not None or name in receipt['payload_files']:
                        preserved.append(name)
                    else:
                        changes[name] = data
                    continue
                if current is not None and name not in owned:
                    conflicts.append(name)
                elif _hash(current) != revision(data):
                    changes[name] = data
            for name, old in owned.items():
                if name not in payload and snapshots[name] == old:
                    changes[name] = None
        else:
            self._check_service(uninstall=True)
            for name, old in owned.items():
                if snapshots[name] == old:
                    changes[name] = None
        after = dict(receipt)
        if action == 'upgrade':
            after.update(payload_sha256=digest, payload_files={name: revision(data) for name, data in payload.items()},
                owned_files={name: revision(data) for name, data in payload.items() if not configuration_file(name)})
        else:
            after.update(state='uninstalled', owned_files={})
        changes[RECEIPT] = _json(after)
        snapshots[RECEIPT] = revision(raw)
        review = revision(_json({'action': action, 'instance': self.instance.id, 'root': str(self.root),
            'snapshots': snapshots, 'after': {name: _hash(data) for name, data in changes.items()}}))
        validation = ManagementOperations(self.root).validate(sources=changes) if action == 'upgrade' else {'errors': []}
        plan = {'review': review, 'action': action, 'controller': str(self.root),
            'changes': [{'file': name, 'action': 'remove' if data is None else 'write'} for name, data in changes.items()],
            'preserved': sorted(set(preserved)), 'conflicts': sorted(set(conflicts)),
            'validation_errors': validation['errors'], 'can_apply': not conflicts and not validation['errors'],
            'warnings': ['No database, dedicated-server file, .env, custom app, venv, credential, log or record-state deletion.',
                'Changed requirements are saved, not installed. Review incoming defaults separately.',
                'Inventory entry and recovery backups remain available after program removal.']}
        return plan, changes, snapshots

    def preview(self, action, *, payload=None, sha256=None):
        if action not in {'upgrade', 'uninstall'}:
            raise ManagementError('Expected upgrade or uninstall')
        incoming = read_payload(payload, sha256) if action == 'upgrade' else None
        with self._locked():
            return self._plan(action, incoming, sha256)[0]

    def _save(self, path, value):
        _replace(path, _json(value), _hash(_bytes(path)))
        protect_token(path)

    def _journal(self, identity):
        if not re.fullmatch('[0-9a-f]{32}', identity):
            raise ManagementError('Select a valid transaction ID')
        folder = safe_path(self.area / identity)
        raw = _bytes(folder / 'transaction.json')
        if raw is None:
            raise ManagementError('Transaction was not found')
        record = json.loads(raw)
        if (record.get('schema') != 1 or record.get('id') != identity
                or record.get('instance_id') != self.instance.id
                or record.get('controller') != str(self.root)
                or record.get('action') not in {'upgrade', 'uninstall', 'adopt'}):
            raise ManagementError('Transaction does not belong to this installation')
        if record.get('state') not in {'prepared', 'committed', 'rolling-back', 'rolled-back'}:
            raise ManagementError('Unknown transaction state')
        if not isinstance(record.get('changes'), list) or len(record['changes']) > 4097:
            raise ManagementError('Invalid transaction change inventory')
        seen = set()
        for entry in record['changes']:
            name = entry['file']
            self._path(name)
            if name.casefold() in seen:
                raise ManagementError('Duplicate transaction path')
            seen.add(name.casefold())
            for key in ('before', 'after'):
                if entry[key] is not None and not re.fullmatch('[0-9a-f]{64}', entry[key]):
                    raise ManagementError('Invalid transaction checksum')
            if configuration_file(name) and entry['before'] is not None:
                raise ManagementError('Transaction may not replace an existing config file')
            if entry['before'] is not None:
                saved = _bytes(folder / 'before' / name)
                if _hash(saved) != entry['before']:
                    raise ManagementError('Recovery backup checksum mismatch; original files were not changed')
        return folder, record

    def transactions(self):
        if not self.area.exists():
            return []
        result = []
        for folder in sorted(self.area.iterdir(), key=lambda path: path.name):
            if re.fullmatch('[0-9a-f]{32}', folder.name) and folder.is_dir():
                if not (folder / 'transaction.json').exists():
                    continue  # An interrupted backup preparation changed no installed files.
                _folder, record = self._journal(folder.name)
                result.append({key: record[key] for key in ('id', 'action', 'state', 'created_ns')})
        return sorted(result, key=lambda item: item['created_ns'], reverse=True)

    def _commit(self, action, changes, snapshots, *, defaults=None, release='upgrade'):
        identity = uuid4().hex
        safe_path(self.area)
        self.area.mkdir(mode=0o700, exist_ok=True)
        folder = self.area / identity
        folder.mkdir(mode=0o700)
        # Guard code first for an upgrade; remove main.py first for an uninstall.
        first = GUARD if action == 'upgrade' else 'main.py'
        names = sorted(changes, key=lambda name: (name != first, name == RECEIPT, name))
        record = {'schema': 1, 'id': identity, 'instance_id': self.instance.id,
            'controller': str(self.root), 'action': action, 'state': 'prepared',
            'created_ns': time.time_ns(), 'changes': []}
        if action == 'upgrade':
            from .config_backup import backup_app_defaults
            record['app_defaults_backup'] = backup_app_defaults(self.root, folder / 'configuration', release)
        for name in names:
            before = _bytes(self._path(name))
            if _hash(before) != snapshots[name]:
                raise ManagementError('A file changed after review; installation files were not modified')
            if before is not None:
                _write(folder / 'before' / name, before, private=True)
            record['changes'].append({'file': name, 'before': _hash(before), 'after': _hash(changes[name])})
        for name, data in (defaults or {}).items():
            if configuration_file(name):
                _write(folder / 'defaults' / name, data, private=True)
        self._save(folder / 'transaction.json', record)
        self._save(self.area / 'active.json', {'id': identity})
        try:
            for entry in record['changes']:
                _replace(self._path(entry['file']), changes[entry['file']], entry['before'])
            record['state'] = 'committed'
            self._save(folder / 'transaction.json', record)
            (self.area / 'active.json').unlink()
        except Exception as exc:
            raise ManagementError('Maintenance stopped before completion. Startup is blocked; review transaction '
                + identity + ' and use rollback. Backups and data were retained.') from exc
        return {'transaction': identity, 'state': 'committed', 'action': action, 'started': False,
                'defaults': str(folder / 'defaults') if defaults else None,
                'app_defaults_backup': record.get('app_defaults_backup')}

    def apply(self, action, *, reviewed, payload=None, sha256=None):
        if action not in {'upgrade', 'uninstall'}:
            raise ManagementError('Expected upgrade or uninstall')
        incoming = read_payload(payload, sha256) if action == 'upgrade' else None
        with self._locked():
            plan, changes, snapshots = self._plan(action, incoming, sha256)
            if plan['review'] != reviewed or not plan['can_apply']:
                raise ManagementError('Review is stale or contains code/custom-app conflicts; nothing changed')
            release = 'upgrade-' + sha256[:12] if action == 'upgrade' else action
            if incoming:
                text = incoming.get('pyxaseco/core/aseco.py', b'').decode('utf-8-sig')
                match = re.search(r"(?m)^PYXASECO_VERSION\s*=\s*['\"]([A-Za-z0-9._-]{1,60})['\"]", text)
                if match:
                    release = match.group(1) + '-' + sha256[:12]
            return self._commit(action, changes, snapshots, defaults=incoming, release=release)

    def adopt(self, *, payload, sha256, reviewed=None):
        incoming = read_payload(payload, sha256)
        with self._locked():
            raw = _bytes(self.root / RECEIPT)
            old = json.loads(raw) if raw else {}
            if old.get('schema') == 2:
                raise ManagementError('An ownership receipt already exists; adoption cannot reset its history')
            if old.get('instance_id') not in (None, self.instance.id):
                raise ManagementError('Old receipt belongs to another installation')
            if old.get('controller') and safe_path(old['controller']) != self.root:
                raise ManagementError('Old receipt belongs to another controller folder')
            if old.get('payload_sha256') and old['payload_sha256'].lower() != sha256.lower():
                raise ManagementError('Use the original payload SHA256 recorded by this older installation for adoption')
            if 'MANAGEMENT_RUNTIME_LOCK = 1' not in (self.root / 'main.py').read_text(encoding='utf-8-sig'):
                raise ManagementError('Baseline adoption requires the runtime-lock entrypoint')
            owned, unknown, snapshots = {}, [], {}
            for name, data in incoming.items():
                current = _bytes(self._path(name))
                snapshots[name] = _hash(current)
                if not configuration_file(name):
                    if _hash(current) == revision(data):
                        owned[name] = revision(data)
                    else:
                        unknown.append(name)
            receipt = {'schema': 2, 'state': 'installed', 'instance_id': self.instance.id,
                'controller': str(self.root), 'python': self.instance.python, 'mode': old.get('mode', 'adopted'),
                'payload_sha256': sha256, 'payload_files': {name: revision(data) for name, data in incoming.items()},
                'owned_files': owned, 'dependencies_installed': old.get('dependencies_installed', False),
                'service_plan': old.get('service_plan')}
            stamp = revision(_json({'snapshots': snapshots, 'receipt': _hash(raw), 'new': receipt}))
            if reviewed is None:
                return {'review': stamp, 'action': 'adopt', 'matching_program_files': len(owned),
                    'unowned': sorted(unknown), 'changes': [RECEIPT], 'configuration_changed': False}
            if reviewed != stamp:
                raise ManagementError('Baseline adoption inputs changed; review again')
            return self._commit('adopt', {RECEIPT: _json(receipt)}, {RECEIPT: _hash(raw)})

    def rollback(self, identity, *, reviewed=None):
        with self._locked(recovery=identity):
            folder, record = self._journal(identity)
            if record['state'] == 'rolled-back':
                raise ManagementError('This transaction is already rolled back')
            snapshots, conflicts = {}, []
            for entry in record['changes']:
                current = _hash(_bytes(self._path(entry['file'])))
                snapshots[entry['file']] = current
                if current not in (entry['before'], entry['after']):
                    conflicts.append(entry['file'])
            # Prevent an older transaction undoing a later committed release.
            receipt = next((entry for entry in record['changes'] if entry['file'] == RECEIPT), None)
            if record['state'] == 'committed' and receipt and snapshots[RECEIPT] != receipt['after']:
                conflicts.append(RECEIPT)
            stamp = revision(_json({'record': record, 'snapshots': snapshots}))
            plan = {'review': stamp, 'action': 'rollback', 'transaction': identity,
                    'conflicts': sorted(set(conflicts)), 'can_apply': not conflicts,
                    'changes': [entry['file'] for entry in record['changes']], 'database_restored': False}
            if reviewed is None:
                return plan
            if reviewed != stamp or conflicts:
                raise ManagementError('Rollback is stale or a changed file would be lost; no restore was attempted')
            self._save(self.area / 'active.json', {'id': identity})
            try:
                record['state'] = 'rolling-back'
                self._save(folder / 'transaction.json', record)
                # Reverse commit order: restore old guard last, and restore removed main.py last.
                for entry in reversed(record['changes']):
                    current = _hash(_bytes(self._path(entry['file'])))
                    if current == entry['before']:
                        continue
                    saved = _bytes(folder / 'before' / entry['file']) if entry['before'] is not None else None
                    _replace(self._path(entry['file']), saved, entry['after'])
                record['state'] = 'rolled-back'
                self._save(folder / 'transaction.json', record)
                (self.area / 'active.json').unlink()
            except Exception as exc:
                raise ManagementError('Rollback is incomplete; startup remains blocked. Keep the recovery files.') from exc
            return {'transaction': identity, 'state': 'rolled-back', 'started': False, 'database_restored': False}


def main(argv=None):
    import argparse
    from .instances import InstanceRegistry
    parser = argparse.ArgumentParser(description='Stopped-instance program maintenance; no data/database removal')
    parser.add_argument('--registry')
    parser.add_argument('--instance', required=True)
    parser.add_argument('action', choices=('upgrade', 'uninstall', 'adopt', 'rollback', 'transactions'))
    parser.add_argument('--payload')
    parser.add_argument('--sha256')
    parser.add_argument('--transaction')
    parser.add_argument('--apply', metavar='REVIEW_HASH')
    args = parser.parse_args(argv)
    try:
        manager = Maintenance(InstanceRegistry(args.registry).get(args.instance))
        if args.action == 'transactions':
            result = manager.transactions()
        elif args.action == 'rollback':
            result = manager.rollback(args.transaction or '', reviewed=args.apply)
        elif args.action == 'adopt':
            result = manager.adopt(payload=args.payload, sha256=args.sha256, reviewed=args.apply)
        else:
            options = {'payload': args.payload, 'sha256': args.sha256}
            result = manager.apply(args.action, reviewed=args.apply, **options) if args.apply else manager.preview(args.action, **options)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, ManagementError) else f'Maintenance failed ({type(exc).__name__}); input contents omitted'
        print(json.dumps({'error': message}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
