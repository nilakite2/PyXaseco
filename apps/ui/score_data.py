"""Generation-owned background score SELECTs; no live state in workers."""

from hashlib import sha256
import json
import logging
import time

from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
from pyxaseco.core.bounded_cache import BoundedCache

logger = logging.getLogger(__name__)


class ScoreData:
    def __init__(self, aseco):
        self.aseco = aseco
        self.cache = BoundedCache(capacity=128, ttl=60, negative_ttl=10)
        self.service = aseco.jobs.service('score_data', JobPolicy(deadline_seconds=60))
        self._retry_at = 0.0
        aseco.register_event('onEverySecond', self.retry)
        for event in ('onNewChallenge', 'onRestartChallenge', 'onRanksUpdated',
                      'onRecordsChanged', 'onTracklistChanged', 'onChallengeListModified'):
            aseco.register_event(event, self.invalidate)

    async def invalidate(self, _aseco, _param=None):
        self.cache.clear()
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
        job = JobEnvelope.capture(context, {'sql': sql, 'params': params})
        async def operation(envelope):
            p = envelope.payload()
            pool = await localdb_get_pool(self.aseco)
            if not pool:
                raise RuntimeError('Score database unavailable')
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(p['sql'], tuple(p['params']))
                    return list(await cur.fetchall())
        async def apply(result):
            if result.status != 'completed':
                logger.warning('[UI] Score data unavailable (%s)', result.error_type)
                self._retry_at = time.monotonic() + 10
                return
            self.cache[key] = result.value
            await self.aseco.release_event('onScoreDataReady', None)
        self.service.submit(job, operation, apply, dedupe_key=fingerprint)
        return None


def score_data(aseco):
    existing = aseco.services.get('score_data')
    if existing is None:
        existing = ScoreData(aseco)
        aseco.services.register('score_data', existing, owner='ui')
    return existing
