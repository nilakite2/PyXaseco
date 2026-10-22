"""Bounded request observations, independent of opt-in performance logging."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
import math
import re
import threading
import time


@dataclass(frozen=True)
class Observation:
    status: str
    milliseconds: float
    finished_at: float
    last_success_at: float | None


class ServiceHealth:
    def __init__(self, *, capacity=32, clock=time.monotonic):
        self.capacity = max(1, min(128, capacity))
        self.clock = clock
        self._rows = {}
        self._lock = threading.Lock()

    @staticmethod
    def owner(name):
        return 'tmx' if name.startswith('tmx_') else name

    def request(self, owner):
        return _Request(self, self.owner(owner))

    def snapshot(self):
        with self._lock:
            return dict(self._rows)

    def _record(self, owner, started, status):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', owner):
            return
        finished = self.clock()
        elapsed = max(0.0, (finished - started) * 1000)
        if not math.isfinite(elapsed):
            return
        with self._lock:
            if owner not in self._rows and len(self._rows) >= self.capacity:
                return
            previous = self._rows.get(owner)
            success = finished if status == 'Responding' else (previous.last_success_at if previous else None)
            self._rows[owner] = Observation(status, elapsed, finished, success)


class _Request:
    def __init__(self, health, owner):
        self.health, self.owner = health, owner
        self.http_status = None
        self.status = 'Responding'

    def __enter__(self):
        self.started = self.health.clock()
        return self

    def __exit__(self, kind, error, traceback):
        if isinstance(error, asyncio.CancelledError):
            return False
        status = self.status if self.status in ('Responding', 'API rejected') else 'Failed'
        code = getattr(error, 'status', getattr(error, 'code', self.http_status))
        if isinstance(error, TimeoutError):
            status = 'Timed out'
        elif type(code) is int and 400 <= code <= 599:
            status = f'HTTP {code}'
        elif error is not None:
            status = 'Failed'
        self.health._record(self.owner, self.started, status)
        return False


def health_for(aseco):
    health = getattr(getattr(aseco, 'jobs', None), 'health', None)
    return health if isinstance(health, ServiceHealth) else None


def observe_request(aseco, owner):
    health = health_for(aseco)
    return health.request(owner) if health is not None else nullcontext()


@asynccontextmanager
async def observed_response(aseco, owner, request):
    # Runs after job/worker admission, not while a request is waiting in its queue.
    with observe_request(aseco, owner) as sample:
        async with request as response:
            if sample is not None:
                sample.http_status = response.status
            yield response
