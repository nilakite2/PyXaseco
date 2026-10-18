"""Bounded record snapshots, with optional dedicated SQLite retention.

No endpoint retries occur here. A send must be marked before external I/O;
interrupted or ambiguous sends become uncertain and need app reconciliation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4


logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    import sqlite3


class OutboxFull(RuntimeError):
    pass


class OutboxBusy(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RetainedRecord:
    record_id: str
    owner: str
    dedupe_key: str
    payload_json: str
    state: str
    created_at: float


class RecordOutbox:
    durable = True

    def __init__(self, path: Path | None, *, max_records: int = 10000,
                 max_payload_bytes: int = 64 * 1024 * 1024):
        if not 1 <= max_records <= 100000 or not 1 <= max_payload_bytes <= 1024 ** 3:
            raise ValueError('invalid outbox retention limits')
        self.path = Path(path) if path is not None else None
        self.max_records, self.max_payload_bytes = max_records, max_payload_bytes
        self._executor: ThreadPoolExecutor | None = None
        self._connection: sqlite3.Connection | None = None
        self._lock_file = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._closing = False
        self._pending_io = 0

    async def _call(self, operation, *args):
        # Keep cancellation from allowing close/reopen to race an unfinished SQL
        # transaction. SQLite operations have a short lock timeout; no HTTP here.
        if self._closed or self._closing:
            raise RuntimeError('record outbox is closed')
        if self._pending_io >= 64:
            raise OutboxBusy('record outbox I/O admission limit reached')
        self._pending_io += 1
        try:
            async with self._lock:
                if self._closed or self._closing:
                    raise RuntimeError('record outbox is closed')
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='record-outbox')
                future = asyncio.get_running_loop().run_in_executor(self._executor, self._execute, operation, args)
                return await self._await_io(future)
        finally:
            self._pending_io -= 1

    @staticmethod
    async def _await_io(future):
        cancelled = False
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                cancelled = True
        result = future.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    def _claim_storage(self):
        lock_file = self.path.with_suffix(self.path.suffix + '.lock').open('a+b')
        try:
            if lock_file.seek(0, os.SEEK_END) == 0:
                lock_file.write(b'0')
                lock_file.flush()
            lock_file.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError('record outbox is already owned by another process') from error
        except BaseException:
            lock_file.close()
            raise
        self._lock_file = lock_file

    def _execute(self, operation, args):
        import sqlite3

        if self.path is None:
            raise RuntimeError('durable record retention requires a storage path')
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._claim_storage()
            connection = None
            try:
                connection = sqlite3.connect(self.path, timeout=0.25)
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1):
                    raise RuntimeError('unsupported record outbox schema version')
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA synchronous=FULL')
                with connection:
                    connection.execute('''CREATE TABLE IF NOT EXISTS records (
                        record_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                        dedupe_key TEXT NOT NULL, payload_json TEXT NOT NULL,
                        payload_bytes INTEGER NOT NULL, state TEXT NOT NULL,
                        created_at REAL NOT NULL, UNIQUE(owner, dedupe_key)
                    )''')
                    connection.execute('CREATE INDEX IF NOT EXISTS records_owner_state ON records(owner, state)')
                    connection.execute('PRAGMA user_version=1')
                    connection.execute("UPDATE records SET state='uncertain' WHERE state='sending'")
                self._connection = connection
            except BaseException:
                if connection is not None:
                    connection.close()
                self._lock_file.close()
                self._lock_file = None
                raise
        return operation(self._connection, *args)

    async def retain(self, owner: str, dedupe_key: str, payload) -> str:
        if not owner or len(owner) > 64 or not dedupe_key or len(dedupe_key) > 256:
            raise ValueError('invalid retained record identity')
        text = json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True)
        size = len(text.encode('utf-8'))
        if size > 1024 * 1024:
            raise ValueError('retained record payload exceeds 1 MiB; retain replay paths, not replay bytes')
        return await self._call(self._retain, owner, dedupe_key, text, size)

    def _retain(self, connection, owner, key, text, size):
        with connection:
            existing = connection.execute(
                'SELECT record_id, payload_json FROM records WHERE owner=? AND dedupe_key=?', (owner, key),
            ).fetchone()
            if existing is not None:
                if existing[1] != text:
                    raise ValueError('retained record key already has a different payload')
                return existing[0]
            count, used = connection.execute(
                'SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0) FROM records',
            ).fetchone()
            while count >= self.max_records or used + size > self.max_payload_bytes:
                # Successful history must not block new results on a healthy
                # busy server. Required/ambiguous records are never evicted.
                oldest = connection.execute(
                    "SELECT record_id, payload_bytes FROM records WHERE state='delivered' "
                    "ORDER BY created_at, record_id LIMIT 1",
                ).fetchone()
                if oldest is None:
                    raise OutboxFull('record outbox retention limit reached')
                connection.execute("DELETE FROM records WHERE record_id=? AND state='delivered'", (oldest[0],))
                count -= 1
                used -= oldest[1]
            record_id = uuid4().hex
            connection.execute('INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)',
                               (record_id, owner, key, text, size, 'pending', time.time()))
            return record_id

    async def list(self, owner: str, *, state: str = 'pending', limit: int = 100,
                   offset: int = 0) -> list[RetainedRecord]:
        if (state not in ('pending', 'sending', 'uncertain', 'delivered', 'failed')
                or not 1 <= limit <= 1000 or not 0 <= offset <= self.max_records):
            raise ValueError('invalid outbox query')
        return await self._call(self._list, owner, state, limit, offset)

    @staticmethod
    def _list(connection, owner, state, limit, offset):
        rows = connection.execute('''SELECT record_id, owner, dedupe_key, payload_json,
                                     state, created_at FROM records WHERE owner=? AND state=?
                                     ORDER BY created_at, record_id LIMIT ? OFFSET ?''', (owner, state, limit, offset))
        return [RetainedRecord(*row) for row in rows]

    async def transition(self, record_id: str, *, expected: str, target: str) -> bool:
        allowed = {
            'pending': {'sending', 'failed'},
            'sending': {'delivered', 'uncertain', 'failed'},
            # Returning to pending requires the app to have reconciled the
            # outcome or verified the endpoint's idempotency contract.
            'uncertain': {'pending', 'delivered', 'failed'},
            'failed': {'pending'},
        }
        if target not in allowed.get(expected, set()):
            raise ValueError('invalid record outbox transition')
        return await self._call(self._transition, record_id, expected, target)

    @staticmethod
    def _transition(connection, record_id, expected, target):
        with connection:
            cursor = connection.execute('UPDATE records SET state=? WHERE record_id=? AND state=?',
                                        (target, record_id, expected))
            return cursor.rowcount == 1

    async def prune_delivered(self, *, older_than: float) -> int:
        """Explicit retention cleanup; pending/uncertain/failed rows survive."""
        return await self._call(self._prune, older_than)

    @staticmethod
    def _prune(connection, cutoff):
        with connection:
            cursor = connection.execute("DELETE FROM records WHERE state='delivered' AND created_at<?", (cutoff,))
            return cursor.rowcount

    async def close(self) -> None:
        self._closing = True
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._executor is not None:
                try:
                    future = asyncio.get_running_loop().run_in_executor(self._executor, self._close_storage)
                    await self._await_io(future)
                finally:
                    self._executor.shutdown(wait=False)
                    self._executor = None

    def _close_storage(self):
        try:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
        finally:
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None


class MemoryRecordOutbox(RecordOutbox):
    """Same delivery contract without files, SQLite connections or I/O workers."""

    durable = False

    def __init__(self, **limits):
        super().__init__(None, **limits)
        self._records: dict[str, tuple[RetainedRecord, int]] = {}
        self._identities: dict[tuple[str, str], str] = {}
        self._payload_bytes = 0

    async def _call(self, operation, *args):
        async with self._lock:
            if self._closed or self._closing:
                raise RuntimeError('record outbox is closed')
            return operation(self._records, *args)

    def _drop(self, record_id):
        record, size = self._records.pop(record_id)
        self._identities.pop((record.owner, record.dedupe_key))
        self._payload_bytes -= size

    def _retain(self, records, owner, key, text, size):
        existing = self._identities.get((owner, key))
        if existing is not None:
            if records[existing][0].payload_json != text:
                raise ValueError('retained record key already has a different payload')
            return existing
        count, used = len(records), self._payload_bytes
        if size > self.max_payload_bytes:
            raise OutboxFull('record outbox retention limit reached')
        evict = []
        # Decide the full eviction first, so rejected admission changes nothing.
        delivered = []
        if count >= self.max_records or used + size > self.max_payload_bytes:
            delivered = sorted((row for row in records.values() if row[0].state == 'delivered'),
                               key=lambda row: (row[0].created_at, row[0].record_id))
        for record, old_size in delivered:
            if count < self.max_records and used + size <= self.max_payload_bytes:
                break
            evict.append(record.record_id)
            count -= 1
            used -= old_size
        if count >= self.max_records or used + size > self.max_payload_bytes:
            raise OutboxFull('record outbox retention limit reached')
        for record_id in evict:
            self._drop(record_id)
        record_id = uuid4().hex
        records[record_id] = (RetainedRecord(record_id, owner, key, text, 'pending', time.time()), size)
        self._identities[owner, key] = record_id
        self._payload_bytes += size
        return record_id

    @staticmethod
    def _list(records, owner, state, limit, offset):
        rows = sorted((record for record, _size in records.values()
                       if record.owner == owner and record.state == state),
                      key=lambda record: (record.created_at, record.record_id))
        return rows[offset:offset + limit]

    @staticmethod
    def _transition(records, record_id, expected, target):
        entry = records.get(record_id)
        if entry is None or entry[0].state != expected:
            return False
        records[record_id] = (replace(entry[0], state=target), entry[1])
        return True

    def _prune(self, records, cutoff):
        expired = [record.record_id for record, _size in records.values()
                   if record.state == 'delivered' and record.created_at < cutoff]
        for record_id in expired:
            self._drop(record_id)
        return len(expired)

    async def close(self):
        self._closing = True
        async with self._lock:
            if self._closed:
                return
            unresolved = [record for record, _size in self._records.values()
                          if record.state != 'delivered']
            if unresolved:
                logger.warning('Closing memory-only delivery with %d unresolved submissions; '
                               'they will not survive restart. Existing replay files are not deleted.',
                               len(unresolved))
            self._records.clear()
            self._identities.clear()
            self._payload_bytes = 0
            self._closed = True


def create_record_outbox(path: Path, durable: bool | None = None) -> RecordOutbox:
    """Default to memory, but never silently abandon existing durable storage."""
    if path.exists():
        if durable is False:
            raise RuntimeError('Existing record outbox must be reconciled and archived before '
                               'disabling durable_record_delivery; no state was deleted')
        if durable is None:
            logger.warning('Existing record outbox detected; preserving durable delivery. '
                           'Review pending/uncertain submissions before switching to memory.')
        return RecordOutbox(path)
    if durable:
        logger.info('Durable record delivery enabled')
        return RecordOutbox(path)
    logger.info('Record delivery uses memory only; queued submissions do not survive process exit')
    return MemoryRecordOutbox()
