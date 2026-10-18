"""Opt-in, bounded performance counters. Never records RPC arguments."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from contextlib import contextmanager
from functools import wraps


logger = logging.getLogger(__name__)


class PerformanceMetrics:
    def __init__(self, enabled: bool = False, *, max_keys: int = 256, sample_size: int = 128):
        self.enabled = enabled
        self.max_keys = max(1, max_keys)
        self.sample_size = max(1, sample_size)
        self.counters: dict[str, int] = {}
        self.timings: dict[str, deque] = {}
        self.high_water: dict[str, int] = {}
        self._task: asyncio.Task | None = None

    def increment(self, key: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        if key not in self.counters and len(self.counters) >= self.max_keys:
            return
        self.counters[key] = self.counters.get(key, 0) + amount

    def observe(self, key: str, seconds: float) -> None:
        if not self.enabled:
            return
        if key not in self.timings:
            if len(self.timings) >= self.max_keys:
                return
            self.timings[key] = deque(maxlen=self.sample_size)
        self.timings[key].append(max(0.0, seconds) * 1000.0)

    def gauge_max(self, key: str, value: int) -> None:
        if not self.enabled:
            return
        if key not in self.high_water and len(self.high_water) >= self.max_keys:
            return
        self.high_water[key] = max(self.high_water.get(key, 0), value)

    @contextmanager
    def measure(self, key: str):
        if not self.enabled:
            yield
            return
        started = time.monotonic()
        try:
            yield
        finally:
            self.observe(key, time.monotonic() - started)

    def snapshot(self, *, reset: bool = False) -> dict:
        timings = {}
        for key, samples in self.timings.items():
            values = sorted(samples)
            if values:
                timings[key] = {
                    'samples': len(values),
                    'p50_ms': round(values[max(0, math.ceil(len(values) * .50) - 1)], 3),
                    'p95_ms': round(values[max(0, math.ceil(len(values) * .95) - 1)], 3),
                    'p99_ms': round(values[max(0, math.ceil(len(values) * .99) - 1)], 3),
                    'max_ms': round(values[-1], 3),
                }
        result = {
            'counters': dict(self.counters),
            'timings': timings,
            'high_water': dict(self.high_water),
        }
        if reset:
            self.counters.clear()
            self.timings.clear()
            self.high_water.clear()
        return result

    def log_summary(self) -> None:
        if not self.enabled:
            return
        data = self.snapshot(reset=True)
        if not any(data.values()):
            return
        busiest = sorted(data['counters'].items(), key=lambda item: -item[1])[:8]
        slowest = sorted(data['timings'].items(), key=lambda item: -item[1]['max_ms'])[:8]
        logger.info('[Perf] counts=%s slowest_recent=%s high_water=%s',
                    dict(busiest), dict(slowest), data['high_water'])

    async def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._monitor(), name='performance-monitor')

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.log_summary()

    async def _monitor(self) -> None:
        next_summary = time.monotonic() + 60.0
        while True:
            due = time.monotonic() + .1
            await asyncio.sleep(.1)
            self.observe('event_loop.lag', time.monotonic() - due)
            if time.monotonic() >= next_summary:
                self.log_summary()
                next_summary = time.monotonic() + 60.0


def profile_rpc(kind: str):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(self, method, *args):
            metrics = self.performance
            if metrics is None or not metrics.enabled:
                return await fn(self, method, *args)
            metrics.increment(f'gbx.{kind}.{method}')
            with metrics.measure(f'gbx.{kind}.{method}'):
                return await fn(self, method, *args)
        return wrapped
    return decorate
