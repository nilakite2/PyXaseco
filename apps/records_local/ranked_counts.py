"""Shared bulk ranked-record counts, independent of the UI app."""

import logging
import time

from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.playlist import playlist

logger = logging.getLogger(__name__)


class RankedCounts:
    def __init__(self, aseco):
        self.aseco = aseco
        self.revision = 0
        self.loading = False
        self._retry_at = 0.0
        self._key, self._rows = None, None
        aseco.register_event('onEverySecond', self.retry)
        for event in ('onLocalRecord', 'onRecordsChanged', 'onTracklistChanged',
                      'onChallengeListModified'):
            aseco.register_event(event, self.invalidate)

    async def invalidate(self, _aseco, _param=None):
        from pyxaseco.core.background_jobs import JobPolicy
        self.revision += 1
        self.loading = False
        self._retry_at = 0.0
        self._key, self._rows = None, None
        self.aseco.jobs.service('ranked_counts', JobPolicy(deadline_seconds=60)).invalidate()

    async def retry(self, _aseco, _param=None):
        if self._retry_at and time.monotonic() >= self._retry_at:
            self._retry_at = 0.0
            await self.aseco.release_event('onScoreDataReady', None)

    async def snapshot(self, *, deferred=False):
        from apps.players.rankings import maxrecs
        uids = tuple(sorted({str(row.get('UId', row.get('Uid', '')))
                             for row in await playlist(self.aseco).snapshot()}))
        mode = self.aseco.server.gameinfo.mode
        key = self.revision, uids, int(maxrecs), mode
        if key != self._key:
            if deferred:
                self.loading = True
                if self._retry_at:
                    return []
                from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
                job = JobEnvelope.capture(self.aseco.capture_job_context(), {'revision': self.revision})
                async def operation(_job):
                    return await load_counts(self.aseco, uids, key[2], mode == 4)
                async def apply(result):
                    if result.status == 'completed' and key[0] == self.revision:
                        self._rows, self._key = result.value, key
                        await self.aseco.release_event('onScoreDataReady', None)
                    elif result.status != 'completed':
                        logger.warning('[Records] Ranked counts unavailable (%s)', result.error_type)
                        self._retry_at = time.monotonic() + 10
                self.aseco.jobs.service('ranked_counts', JobPolicy(deadline_seconds=60)).submit(
                    job, operation, apply, dedupe_key='counts')
                return []
            rows = await load_counts(self.aseco, uids, int(maxrecs), mode == 4)
            if key[0] == self.revision:
                self._rows, self._key = rows, key
            self.loading = False
            return rows
        self.loading = False
        return list(self._rows)


def ranked_counts(aseco):
    existing = aseco.services.get('ranked_counts')
    if existing is None:
        existing = RankedCounts(aseco)
        aseco.services.register('ranked_counts', existing, owner='records_local')
    return existing


async def load_counts(aseco, uids, maxrecs, stunts):
    pool = await localdb_get_pool(aseco)
    if not pool:
        raise RuntimeError('Ranked records database unavailable')
    if not uids or maxrecs <= 0:
        return []
    ids, counts, nicknames = [], {}, {}
    direction = 'DESC' if stunts else 'ASC'
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for offset in range(0, len(uids), 256):
                batch = uids[offset:offset + 256]
                placeholders = ','.join(['%s'] * len(batch))
                await cur.execute(f'SELECT Id FROM challenges WHERE Uid IN ({placeholders})', batch)
                ids.extend(row[0] for row in await cur.fetchall())
            ids.sort()
            for offset in range(0, len(ids), 256):
                batch = ids[offset:offset + 256]
                placeholders = ','.join(['%s'] * len(batch))
                await cur.execute(
                    'SELECT r.ChallengeId, p.Login, p.NickName FROM records r '
                    'INNER JOIN players p ON p.Id=r.PlayerId '
                    f'WHERE r.ChallengeId IN ({placeholders}) '
                    f'ORDER BY r.ChallengeId, r.Score {direction}, r.Date ASC', tuple(batch))
                per_track = {}
                for track, login, nickname in await cur.fetchall():
                    per_track[track] = per_track.get(track, 0) + 1
                    if per_track[track] <= maxrecs and login:
                        counts[login] = counts.get(login, 0) + 1
                        nicknames[login] = nickname or login
    return [(login, nicknames[login], count) for login, count in counts.items()]
