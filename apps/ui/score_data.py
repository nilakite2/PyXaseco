"""Generation-owned background score SELECTs; no live state in workers."""

from dataclasses import dataclass
from hashlib import sha256
import json
import logging
import time

import aiomysql

from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.bounded_cache import BoundedCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoreUnavailable:
    error_type: str
    code: int = 0


class ScoreData:
    def __init__(self, aseco):
        self.aseco = aseco
        self.cache = BoundedCache(capacity=128, ttl=60, negative_ttl=10)
        self.failures = BoundedCache(capacity=128, ttl=10)
        self.service = aseco.jobs.service('score_data', JobPolicy(deadline_seconds=60))
        self._retry_at = 0.0
        aseco.register_event('onEverySecond', self.retry)
        for event in ('onNewChallenge', 'onRestartChallenge', 'onRanksUpdated',
                      'onRecordsChanged', 'onTracklistChanged', 'onChallengeListModified'):
            aseco.register_event(event, self.invalidate)

    async def invalidate(self, _aseco, _param=None):
        self.cache.clear()
        self.failures.clear()
        self._retry_at = 0.0
        self.service.invalidate()
        await self.aseco.release_event('onScoreDataReady', None)

    async def retry(self, _aseco, _param=None):
        if self._retry_at and time.monotonic() >= self._retry_at:
            self._retry_at = 0.0
            await self.aseco.release_event('onScoreDataReady', None)

    def request(self, sql, params=()):
        context = self.aseco.capture_job_context()
        fingerprint = sha256(json.dumps([sql, params]).encode()).hexdigest()
        key = context, fingerprint
        cached = self.cache.get(key)
        if cached is not None:
            return list(cached)
        failure = self.failures.get(key)
        if failure is not None:
            self._schedule_retry()
            return failure
        job = JobEnvelope.capture(context, {'sql': sql, 'params': params})
        async def operation(envelope):
            p = envelope.payload()
            try:
                pool = await localdb_get_pool(self.aseco)
                if not pool:
                    return ScoreUnavailable('DatabaseUnavailable')
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(p['sql'], tuple(p['params']))
                        return list(await cur.fetchall())
            except (aiomysql.OperationalError, aiomysql.ProgrammingError) as error:
                # Keep SQL/parameters and database credentials out of diagnostics.
                code = error.args[0] if error.args and type(error.args[0]) is int else 0
                return ScoreUnavailable(type(error).__name__, code)
        async def apply(result):
            failure = (ScoreUnavailable(result.error_type) if result.status != 'completed'
                       else result.value if isinstance(result.value, ScoreUnavailable) else None)
            if failure is not None:
                self.failures[key] = failure
                self._schedule_retry()
                logger.warning('[UI] Score data unavailable (%s, MySQL %d, query %s); retry delayed',
                               failure.error_type, failure.code, fingerprint[:12])
            else:
                self.cache[key] = result.value
            await self.aseco.release_event('onScoreDataReady', None)
        outcome = self.service.submit(job, operation, apply, dedupe_key=fingerprint)
        if outcome not in (Admission.ACCEPTED, Admission.DUPLICATE):
            failure = ScoreUnavailable(outcome.value)
            self.failures[key] = failure
            self._schedule_retry()
            return failure
        return None

    def _schedule_retry(self):
        if not self._retry_at:
            self._retry_at = time.monotonic() + 10


def score_data(aseco):
    existing = aseco.services.get('score_data')
    if existing is None:
        existing = ScoreData(aseco)
        aseco.services.register('score_data', existing, owner='ui')
    return existing
