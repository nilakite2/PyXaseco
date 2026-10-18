"""App-owned background delivery with optional persistence and no ambiguous retries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy

logger = logging.getLogger(__name__)


class PreparationRejected(RuntimeError):
    """Definitive local/read-only rejection; no external write was attempted."""


class PreparationDeferred(RuntimeError):
    """A temporary prerequisite is unavailable; no external write was attempted."""


class RetainedDelivery:
    def __init__(self, aseco, owner, send, apply, *, prepare=None, cleanup=None, on_failure=None, ready=None):
        self.aseco, self.owner = aseco, owner
        self.send, self.apply, self.prepare = send, apply, prepare
        self.cleanup = cleanup
        self.on_failure = on_failure
        self.ready = ready
        self.service = aseco.jobs.service(owner, JobPolicy(capacity=32, deadline_seconds=120))
        self._last_scan = 0.0
        self._warned = False
        self._last_prune = 0.0
        self._failure_warning_at = 0.0
        self._scan_offset = 0
        aseco.register_event('onEverySecond', self.tick)

    async def retain(self, payload, *, map_uid=None):
        context = self.aseco.capture_job_context()
        detached = {'version': 1, 'server_id': context.server_id,
                    'map_uid': context.map_uid if map_uid is None else str(map_uid),
                    'generation': context.map_generation,
                    'run_id': context.run_id, 'payload': payload}
        try:
            await self.aseco.record_outbox.retain(self.owner, uuid4().hex, detached)
        except Exception:
            self.aseco.performance.increment('records.' + self.owner + '.retain_failed')
            logger.error('Cannot retain %s submission; record delivery requires attention', self.owner)
            raise
        self.aseco.performance.increment('records.' + self.owner + '.retained')
        await self.tick(self.aseco)

    async def tick(self, _aseco, _param=None):
        now = time.monotonic()
        if now - self._last_scan < 1 or not self.aseco.jobs.running:
            return
        self._last_scan = now
        outbox = self.aseco.record_outbox
        if now - self._last_prune >= 3600:
            await outbox.prune_delivered(older_than=time.time() - 7 * 86400)
            self._last_prune = now
        records = await outbox.list(self.owner, limit=32, offset=self._scan_offset)
        # A missing replay must not permanently starve later valid submissions.
        # Pending rows are never discarded; the next scan wraps after the end.
        self._scan_offset = self._scan_offset + len(records) if len(records) == 32 else 0
        self._scan_offset = min(self._scan_offset, outbox.max_records)
        for record in records:
            # Keep authentication waits off the queue used to reconnect.
            # The readiness hook is a synchronous, in-memory check only.
            if self.ready is not None and not self.ready():
                break
            data = json.loads(record.payload_json)
            if data['server_id'] != self.aseco.capture_job_context().server_id:
                continue
            job = JobEnvelope.capture(self.aseco.capture_job_context(),
                                      {'record_id': record.record_id})

            async def operation(envelope, retained_json=record.payload_json):
                item = envelope.payload()
                rid, retained = item['record_id'], json.loads(retained_json)
                try:
                    prepared = (await self.prepare(retained['payload'])
                                if self.prepare else retained['payload'])
                except PreparationDeferred:
                    self.aseco.performance.increment('records.' + self.owner + '.deferred')
                    return None
                except PreparationRejected:
                    await outbox.transition(rid, expected='pending', target='failed')
                    self.aseco.performance.increment('records.' + self.owner + '.rejected')
                    raise
                if not await outbox.transition(rid, expected='pending', target='sending'):
                    return None
                try:
                    value = await self.send(prepared)
                    await outbox.transition(rid, expected='sending', target='delivered')
                    self.aseco.performance.increment('records.' + self.owner + '.delivered')
                except BaseException:
                    # Record ambiguity before propagating cancellation. Durable
                    # storage also recovers interrupted sends after process exit.
                    await asyncio.shield(outbox.transition(rid, expected='sending', target='uncertain'))
                    self.aseco.performance.increment('records.' + self.owner + '.uncertain')
                    raise
                if self.cleanup:
                    try:
                        await self.cleanup(retained['payload'])
                    except Exception:
                        logger.warning('%s delivered, but local cleanup requires attention', self.owner)
                return retained, value

            async def completed(result):
                if result.status == 'completed' and result.value is not None:
                    retained, value = result.value
                    context = self.aseco.capture_job_context()
                    current = (retained['run_id'] == context.run_id and
                               retained['generation'] == context.map_generation and
                               retained['map_uid'] == context.map_uid)
                    await self.apply(retained['payload'], value, current)
                elif result.status != 'completed':
                    if self.on_failure:
                        await self.on_failure(result)
                    if time.monotonic() - self._failure_warning_at >= 60:
                        self._failure_warning_at = time.monotonic()
                        logger.warning('%s delivery failed; retained state requires inspection (%s)',
                                       self.owner, result.failure_label)

            self.service.submit(job, operation, completed, current_map=False,
                                dedupe_key=record.record_id, revision_guard=False)
        if not self._warned and await outbox.list(self.owner, state='uncertain', limit=1):
            self._warned = True
            logger.warning('%s has uncertain retained submissions; no automatic resubmission', self.owner)


def delivery(aseco, owner, send, apply, *, prepare=None, cleanup=None, on_failure=None, ready=None):
    key = 'retained_delivery/' + owner
    existing = aseco.services.get(key)
    if existing is None:
        existing = RetainedDelivery(aseco, owner, send, apply, prepare=prepare,
                                   cleanup=cleanup, on_failure=on_failure, ready=ready)
        aseco.services.register(key, existing, owner=owner)
    return existing
