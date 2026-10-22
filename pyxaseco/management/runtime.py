"""Bounded controller-owned operations applied between game callback batches."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
import re
import time
from uuid import uuid4

from .config_store import ManagementError
from .operations import ManagementOperations, read_config
from .reload import can_reload, reload_app
from .protocol import TERMINAL


logger = logging.getLogger(__name__)
KINDS = {'config.read', 'config.validate', 'config.write', 'config.backups', 'config.restore', 'app.state', 'app.reload',
         'controller.stop', 'controller.restart'}


class QueueFull(ManagementError):
    pass


class RuntimeManagement:
    def __init__(self, aseco, identity: dict, *, queue_size=16, history_size=128):
        if not 1 <= queue_size <= 16 or not queue_size < history_size <= 128:
            raise ManagementError('Invalid operation queue/history bounds')
        self.aseco = aseco
        self.root = Path(aseco._base_dir).resolve()
        self.identity = identity
        self.operations = ManagementOperations(self.root)
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.history_size = history_size
        self.history = OrderedDict()
        self.pending = None
        self.worker = None
        self.catalog_task = None
        self.catalog = []
        self.catalog_ready = False
        self.catalog_at = 0.0
        self.snapshot_at = 0.0
        self.snapshot = {}
        self.closing = False
        self._snapshot()

    def context(self) -> dict:
        return {'run_id': self.aseco._run_id,
                'mode': getattr(getattr(self.aseco.server, 'gameinfo', None), 'mode', None),
                'phase': 'score' if self.aseco.score_phase else 'warmup' if self.aseco.warmup_phase else 'race',
                'map_generation': getattr(self.aseco, '_map_generation', 0)}

    def _snapshot(self):
        from pyxaseco.core.aseco import PYXASECO_VERSION
        server = self.aseco.server
        players = list(server.players.all())
        self.snapshot = {'protocol': 1, 'instance_id': self.identity['instance_id'],
                         'context': self.context(), 'controller_version': PYXASECO_VERSION,
                         'starting': self.aseco.startup_phase, 'closing': self.closing,
                         'uptime_seconds': max(0, int(time.time() - self.aseco.uptime)),
                         'server_name': getattr(server, 'name', ''),
                         'track_name': getattr(server.challenge, 'name', ''),
                         'track_uid': getattr(server.challenge, 'uid', ''),
                         'players': sum(not p.isspectator for p in players),
                         'spectators': sum(bool(p.isspectator) for p in players),
                         'connection': bool(self.aseco.client.is_connected()),
                         'database_health': 'not probed', 'optional_provider_health': 'not probed',
                         'sampled_at': time.time()}
        self.snapshot_at = time.monotonic()

    def status(self):
        return {**self.snapshot, 'closing': self.closing,
                'queued_operations': self.queue.qsize(), 'busy': self.pending is not None}

    def apps(self):
        loaded = set(self.aseco.active_apps)
        started = set(getattr(getattr(self.aseco, '_app_manager', None), '_started_apps', []))
        return [{'id': row.id, 'name': row.name, 'configured_enabled': row.configured_enabled,
                 'runtime_loaded': row.id in loaded, 'runtime_started': row.id in started,
                 'reload_supported': can_reload(self.aseco, row.id),
                 'pending_restart': row.configured_enabled != (row.id in loaded),
                 'protected': row.protected, 'dependencies': list(row.dependencies),
                 'metadata_error': row.metadata_error} for row in self.catalog]

    @staticmethod
    def _public(operation):
        return {key: value for key, value in operation.items() if key not in {'payload', 'digest'}}

    def get(self, operation_id):
        operation = self.history.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        return self._public(operation)

    def submit(self, payload: dict, request_id: str | None = None):
        if self.closing:
            raise QueueFull('Controller is shutting down')
        if (not isinstance(payload, dict) or not isinstance(payload.get('kind'), str)
                or payload['kind'] not in KINDS):
            raise ManagementError('Unsupported management operation')
        if 'apply' in payload and type(payload['apply']) is not bool:
            raise ManagementError('apply must be a boolean')
        operation_id = request_id or uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', operation_id):
            raise ManagementError('Request ID must contain 32 lowercase hexadecimal characters')
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode('utf-8')
        if len(encoded) > 16384:
            raise ManagementError('Operation body exceeds 16 KiB')
        digest = hashlib.sha256(encoded).hexdigest()
        if operation_id in self.history:
            previous = self.history[operation_id]
            if previous['digest'] != digest:
                raise ManagementError('Request ID was already used for a different operation')
            return self._public(previous)
        if self.queue.full():
            raise QueueFull('Management operation queue is full')
        while len(self.history) >= self.history_size:
            completed = next((key for key, op in self.history.items() if op['state'] in TERMINAL), None)
            if completed is None:
                raise QueueFull('Management operation history is full')
            del self.history[completed]
        operation = {'id': operation_id, 'run_id': self.aseco._run_id, 'kind': payload['kind'],
                     'state': 'queued', 'submitted_at': time.time(), 'digest': digest,
                     'payload': json.loads(encoded), 'result': None}
        self.history[operation_id] = operation
        self.queue.put_nowait(operation)
        logger.info('Local management queued %s operation=%s operator=%s', payload['kind'], operation_id,
                    self.identity['operator'])
        return self._public(operation)

    def mark_closing(self):
        self.closing = True

    def _finish(self, operation, state, result):
        try:
            size = len(json.dumps(result, allow_nan=False).encode('utf-8'))
        except (ValueError, TypeError, RecursionError):
            size = 245761
        if size > 245760:
            result = {'error': 'Result cannot fit the bounded JSON response; inspect this file locally',
                      'saved': result.get('saved', False)}
            state = 'failed' if not result['saved'] else 'saved-not-applied'
        operation.update(state=state, result=result, completed_at=time.time())
        operation.pop('payload', None)
        logger.info('Local management %s operation=%s kind=%s', state, operation['id'], operation['kind'])

    def _edit_arguments(self, payload):
        relative, path, expected = payload.get('file'), payload.get('path'), payload.get('revision')
        if not isinstance(relative, str) or not isinstance(path, list) or not 1 <= len(path) <= 16:
            raise ManagementError('Supply a relative config file and explicit TOML path segments')
        if any(not isinstance(key, str) or not key or len(key) > 200 for key in path):
            raise ManagementError('Invalid TOML setting path')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ManagementError('Supply the revision returned by config.read')
        file = self.operations.config.path(relative).relative_to(self.root)
        if file.as_posix() in {'management.toml', 'apps/management_bridge/app_defaults.toml'}:
            raise ManagementError('Bridge identity/listener settings require an offline edit and restart')
        return file.as_posix(), tuple(path), payload['value'], expected

    def _work(self, payload):
        kind = payload['kind']
        if kind == 'config.read':
            if not isinstance(payload.get('file'), str):
                raise ManagementError('Supply a config file')
            return read_config(self.operations, payload['file'])
        if kind == 'config.backups':
            return {'backups': self.operations.backups(payload['file'])}
        if kind == 'config.restore':
            file, _path, _value, expected = self._edit_arguments({**payload, 'path': ['restore'], 'value': None})
            saved = self.operations._restore_config(file, payload['backup'], expected=expected)
            parts = Path(file).parts
            app_id = parts[1] if len(parts) == 3 and parts[0] == 'apps' else None
            return {**asdict(saved), 'saved': True, 'file': file, 'app_id': app_id,
                    'item_key': None, 'runtime_applied': False}
        if kind in {'config.write', 'config.validate'}:
            file, path, value, expected = self._edit_arguments(payload)
            if kind == 'config.validate':
                self.operations.validate_config_edit(file, path, value, expected=expected)
                return {'valid': True, 'saved': False}
            saved = self.operations._save_config(file, path, value, expected=expected)
            parts = Path(file).parts
            app_id = parts[1] if len(parts) == 3 and parts[0] == 'apps' else None
            item_key = '.'.join(path[1:3]) if app_id == 'ui' and len(path) > 2 and path[1] == 'scoretable_lists' else path[1] if app_id == 'ui' and len(path) > 1 else None
            return {**asdict(saved), 'saved': True, 'file': file, 'path': list(path),
                    'app_id': app_id, 'item_key': item_key, 'runtime_applied': False}
        if kind == 'app.state':
            app_id, enabled, expected = payload.get('app'), payload.get('enabled'), payload.get('revision')
            if not isinstance(app_id, str) or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ManagementError('Supply an app and apps.toml revision')
            saved = self.operations._save_app_state(app_id, enabled, expected=expected)
            return {**asdict(saved), 'saved': True, 'restart_required': True, 'runtime_applied': False}
        raise ManagementError('Unsupported filesystem operation')

    async def _complete_worker(self):
        operation, self.pending = self.pending, None
        task, self.worker = self.worker, None
        try:
            result = task.result()
        except ManagementError as exc:
            self._finish(operation, 'failed', {'error': str(exc), 'saved': False})
            return
        except Exception as exc:
            self._finish(operation, 'failed', {'error': 'Configuration operation failed; input details omitted',
                                              'error_type': type(exc).__name__, 'saved': 'unknown'})
            return
        payload = operation['payload']
        if operation['kind'] in {'config.write', 'config.restore'}:
            result['restart_required'] = True
            if payload.get('context') is not None and payload['context'] != self.context():
                result['error'] = 'Saved, but mode/phase/map changed before apply; refresh before reloading'
                self._finish(operation, 'saved-not-applied', result)
                return
            if payload.get('apply', True) and result.get('app_id') and can_reload(self.aseco, result['app_id']):
                try:
                    result['runtime_applied'] = await reload_app(self.aseco, result['app_id'], result['item_key'])
                    result['restart_required'] = not result['runtime_applied']
                except Exception as exc:
                    result['error'] = 'Saved on disk, but runtime reload failed; refresh before retrying'
                    result['error_type'] = type(exc).__name__
                    self._finish(operation, 'saved-not-applied', result)
                    self.catalog_at = 0
                    return
            result['applied_context'] = self.context() if result.get('runtime_applied') else None
        self._finish(operation, 'completed', result)
        if operation['kind'] in {'config.write', 'config.restore', 'app.state'}:
            self.catalog_at = 0

    async def tick(self):
        if self.closing:
            return
        now = time.monotonic()
        if now - self.snapshot_at >= 1:
            self._snapshot()
        if self.catalog_task is not None and self.catalog_task.done():
            try:
                self.catalog = self.catalog_task.result()
                self.catalog_ready = True
            except Exception:
                logger.warning('Local management app inventory refresh failed; previous snapshot retained')
            self.catalog_task = None
        if self.catalog_task is None and (not self.catalog_at or now - self.catalog_at > 5):
            self.catalog_at = now
            self.catalog_task = asyncio.create_task(asyncio.to_thread(self.operations.apps))
        if getattr(self.aseco, '_callback_backlog', None):
            return
        if self.worker is not None:
            if self.worker.done():
                await self._complete_worker()
            return
        if self.queue.empty():
            return
        operation = self.queue.get_nowait()
        operation['state'] = 'running'
        payload = operation['payload']
        expected_context = payload.get('context')
        if expected_context is not None and expected_context != self.context():
            self._finish(operation, 'failed', {'error': 'Mode/phase/map context changed; refresh before editing'})
            return
        try:
            kind = operation['kind']
            if kind == 'app.reload':
                app_id = payload.get('app')
                if not isinstance(app_id, str) or not can_reload(self.aseco, app_id):
                    raise ManagementError('This app is not loaded or does not support runtime reload')
                applied = await reload_app(self.aseco, app_id)
                self._finish(operation, 'completed', {'runtime_applied': applied, 'restart_required': not applied})
            elif kind in {'controller.stop', 'controller.restart'}:
                self._finish(operation, 'accepted', {'completion': 'Confirm via OS status and the next run identity'})
                if kind == 'controller.restart':
                    await self.aseco.restart()
                else:
                    await self.aseco.shutdown(stop_server=False)
            else:
                self.pending = operation
                self.worker = asyncio.create_task(asyncio.to_thread(self._work, payload))
        except ManagementError as exc:
            self._finish(operation, 'failed', {'error': str(exc)})
        except Exception as exc:
            self._finish(operation, 'failed', {'error': 'Runtime action failed; inspect controller logs',
                                              'error_type': type(exc).__name__})

    async def close(self):
        self.mark_closing()
        if self.worker is not None:
            task, operation = self.worker, self.pending
            self.worker = self.pending = None
            try:
                async with asyncio.timeout(5):
                    result = await asyncio.shield(task)
                self._finish(operation, 'saved-not-applied', {'completion': 'Runtime stopped before apply',
                                                              'result': result})
            except Exception:
                self._finish(operation, 'saved-not-applied', {'completion': 'Indeterminate; re-read config after restart'})
                task.add_done_callback(lambda finished: finished.exception() if not finished.cancelled() else None)
        if self.catalog_task:
            self.catalog_task.cancel()
            await asyncio.gather(self.catalog_task, return_exceptions=True)
            self.catalog_task = None
        while not self.queue.empty():
            self._finish(self.queue.get_nowait(), 'cancelled', {'completion': 'Not started before shutdown'})
