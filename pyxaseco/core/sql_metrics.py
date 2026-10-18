"""Opt-in SQL/pool timings without logging SQL text or parameter values."""

import time
from aiomysql.cursors import Cursor


def measured_cursor(metrics):
    if metrics is None or not metrics.enabled:
        return Cursor

    class MeasuredCursor(Cursor):
        async def execute(self, query, args=None):
            verb = str(query).lstrip().split(None, 1)[0].upper() if query else 'OTHER'
            if verb not in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SET', 'CREATE', 'ALTER', 'SHOW'):
                verb = 'OTHER'
            metrics.increment('sql.calls')
            with metrics.measure('sql.' + verb):
                return await super().execute(query, args)

        async def executemany(self, query, args):
            metrics.increment('sql.batches')
            with metrics.measure('sql.batch'):
                return await super().executemany(query, args)

    return MeasuredCursor


class _Acquisition:
    def __init__(self, inner, metrics):
        self.inner, self.metrics = inner, metrics

    async def _wait(self):
        started = time.monotonic()
        try:
            return await self.inner
        finally:
            self.metrics.observe('sql.pool_wait', time.monotonic() - started)

    def __await__(self):
        return self._wait().__await__()

    async def __aenter__(self):
        started = time.monotonic()
        try:
            return await self.inner.__aenter__()
        finally:
            self.metrics.observe('sql.pool_wait', time.monotonic() - started)

    async def __aexit__(self, *args):
        return await self.inner.__aexit__(*args)


class MeasuredPool:
    def __init__(self, pool, metrics):
        self.pool, self.metrics = pool, metrics

    def __getattr__(self, name):
        return getattr(self.pool, name)

    def acquire(self):
        return _Acquisition(self.pool.acquire(), self.metrics)
