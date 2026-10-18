"""Bounded async jobs; completions run only on the ordered controller lane.

Operations use async I/O or the owned, joined urllib worker transport and
detached inputs. Durable record delivery is managed separately.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from urllib.error import HTTPError
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable
from uuid import uuid4

from aiohttp import ClientResponseError

from pyxaseco.core.http_sessions import HttpSessions
from pyxaseco.core.legacy_http import LegacyHttp
from pyxaseco.core.performance import PerformanceMetrics


logger = logging.getLogger(__name__)


class Admission(str, Enum):
    ACCEPTED = 'accepted'
    DUPLICATE = 'duplicate'
    FULL = 'full'
    STOPPED = 'stopped'
    COOLDOWN = 'cooldown'


@dataclass(frozen=True, slots=True)
class JobContext:
    run_id: str
    server_id: str
    map_uid: str
    map_generation: int
    login: str = ''
    nickname: str = ''


@dataclass(frozen=True, slots=True)
class JobEnvelope:
    context: JobContext
    payload_json: str
    request_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self):
        if not isinstance(self.payload_json, str) or len(self.payload_json.encode('utf-8')) > 262144:
            raise ValueError('job payload must be JSON text of at most 256 KiB')
        json.loads(self.payload_json)

    @classmethod
    def capture(cls, context: JobContext, payload: Any) -> JobEnvelope:
        return cls(context, json.dumps(payload, ensure_ascii=True, allow_nan=False))

    def payload(self) -> Any:
        return json.loads(self.payload_json)


@dataclass(frozen=True, slots=True)
class JobPolicy:
    capacity: int = 32
    workers: int = 1
    deadline_seconds: float = 30.0
    max_attempts: int = 1
    backoff_seconds: float = 0.25
    failures_before_cooldown: int = 3
    cooldown_seconds: float = 10.0

    def __post_init__(self):
        if not 1 <= self.capacity <= 256 or not 1 <= self.workers <= min(4, self.capacity):
            raise ValueError('invalid job capacity or worker count')
        if not 0 < self.deadline_seconds <= 300 or not 1 <= self.max_attempts <= 3:
            raise ValueError('invalid job deadline or retry count')
        if not 0 <= self.backoff_seconds <= 10 or not 0 < self.cooldown_seconds <= 300:
            raise ValueError('invalid backoff or cooldown')
        if not 1 <= self.failures_before_cooldown <= 100:
            raise ValueError('invalid failure threshold')


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    max_services: int = 32
    completions_per_tick: int = 8
    completion_budget_seconds: float = 0.005
    shutdown_grace_seconds: float = 2.0

    def __post_init__(self):
        if not 1 <= self.max_services <= 32 or not 1 <= self.completions_per_tick <= 64:
            raise ValueError('invalid background runtime capacity')
        if not 0 < self.completion_budget_seconds <= 0.1 or not 0 < self.shutdown_grace_seconds <= 10:
            raise ValueError('invalid background runtime time budget')


@dataclass(frozen=True, slots=True)
class JobResult:
    job: JobEnvelope
    status: str
    value: Any = None
    error_type: str = ''
    attempts: int = 0
    http_status: int = 0
    http_hint: str = ''

    @property
    def failure_label(self) -> str:
        label = self.error_type or 'UnknownError'
        if 400 <= self.http_status <= 599:
            label += f', HTTP {self.http_status}'
            if self.http_hint in ('Cloudflare challenge', 'JSON response', 'HTML response'):
                label += ', ' + self.http_hint
        return label


@dataclass(slots=True)
class _Work:
    job: JobEnvelope
    operation: Callable[[JobEnvelope], Awaitable[Any]]
    apply: Callable[[JobResult], Awaitable[None]]
    deadline: float
    revision: int
    key: tuple | None
    current_map: bool
    retry_errors: tuple[type[Exception], ...]
    discard: Callable[[JobResult], Awaitable[None]] | None
    revision_guard: bool


class JobService:
    def __init__(self, runtime: BackgroundJobs, name: str, policy: JobPolicy):
        self.runtime, self.name, self.policy = runtime, name, policy
        self._queue: asyncio.Queue[_Work] = asyncio.Queue(maxsize=policy.capacity)
        self._tasks: list[asyncio.Task] = []
        self._keys: set[tuple] = set()
        self._outstanding = 0
        self._revision = 0
        self._accepting = True
        self._failures = 0
        self._cooldown_until = 0.0
        self._stop_lock = asyncio.Lock()

    @property
    def outstanding(self) -> int:
        return self._outstanding

    def invalidate(self) -> None:
        """Call after a relevant config change; earlier replies cannot apply."""
        self._revision += 1

    def start(self) -> None:
        if not self._tasks and self._accepting and self.runtime.running:
            self._tasks = [asyncio.create_task(self._worker(), name=f'jobs:{self.name}:{i}')
                           for i in range(self.policy.workers)]
            for task in self._tasks:
                task.add_done_callback(self._worker_done)

    def _worker_done(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error('Background worker %s failed (%s)', self.name, type(error).__name__)
        if self._accepting and self.runtime.running:
            self._accepting = False
            logger.error('Background worker %s exited unexpectedly; admission stopped', self.name)

    def submit(self, job: JobEnvelope, operation, apply, *, dedupe_key: str | None = None,
               current_map: bool = True, retry_errors: tuple[type[Exception], ...] = (),
               discard: Callable[[JobResult], Awaitable[None]] | None = None,
               revision_guard: bool = True) -> Admission:
        """Immediate admission. Retry errors are opt-in for safe/idempotent lookups only."""
        if not self._accepting or not self.runtime.running:
            return Admission.STOPPED
        if dedupe_key is not None and (not isinstance(dedupe_key, str) or len(dedupe_key) > 256):
            raise ValueError('dedupe key must be text of at most 256 characters')
        if retry_errors and not all(isinstance(error, type) and issubclass(error, Exception)
                                    for error in retry_errors):
            raise ValueError('retry_errors must contain exception classes')
        identity = (job.context, self._revision) if revision_guard else (
            (job.context.run_id, job.context.server_id), None)
        key = (*identity, dedupe_key) if dedupe_key is not None else None
        if key is not None and key in self._keys:
            return Admission.DUPLICATE
        if time.monotonic() < self._cooldown_until:
            return Admission.COOLDOWN
        # Include active and completed-but-unapplied jobs, not only queued work.
        if self._outstanding >= self.policy.capacity:
            return Admission.FULL
        work = _Work(job, operation, apply, asyncio.get_running_loop().time() + self.policy.deadline_seconds,
                     self._revision, key, current_map, retry_errors, discard, revision_guard)
        self._queue.put_nowait(work)
        self._outstanding += 1
        if key is not None:
            self._keys.add(key)
        self.start()
        self.runtime.metrics.increment(f'jobs.{self.name}.accepted')
        self.runtime.metrics.gauge_max(f'jobs.{self.name}.outstanding', self._outstanding)
        return Admission.ACCEPTED

    def _release(self, work: _Work) -> None:
        self._outstanding -= 1
        if work.key is not None:
            self._keys.discard(work.key)

    async def _execute(self, work: _Work) -> JobResult:
        attempts = 0
        try:
            if asyncio.get_running_loop().time() >= work.deadline:
                return JobResult(work.job, 'failed', error_type='TimeoutError')
            async with asyncio.timeout_at(work.deadline):
                if time.monotonic() < self._cooldown_until:
                    return JobResult(work.job, 'failed', error_type='ServiceCooldown')
                while True:
                    attempts += 1
                    try:
                        value = await work.operation(work.job)
                        return JobResult(work.job, 'completed', value, attempts=attempts)
                    except work.retry_errors:
                        if attempts >= self.policy.max_attempts:
                            raise
                        delay = self.policy.backoff_seconds * (2 ** (attempts - 1))
                        await asyncio.sleep(delay * random.uniform(0.75, 1.25))
        except Exception as error:
            # Error text, URLs, payloads and credentials must not leak into logs.
            status = (error.status if isinstance(error, ClientResponseError)
                      else error.code if isinstance(error, HTTPError) else 0)
            hint = ''
            if isinstance(error, (ClientResponseError, HTTPError)):
                headers = error.headers or {}
                mitigation = str(headers.get('cf-mitigated') or headers.get('CF-Mitigated') or '').lower()
                content_type = str(headers.get('Content-Type') or headers.get('content-type') or '').split(';')[0].strip().lower()
                if mitigation == 'challenge':
                    hint = 'Cloudflare challenge'
                elif content_type == 'application/json' or content_type.endswith('+json'):
                    hint = 'JSON response'
                elif content_type == 'text/html':
                    hint = 'HTML response'
            return JobResult(work.job, 'failed', error_type=type(error).__name__, attempts=attempts,
                             http_status=status if isinstance(status, int) and 400 <= status <= 599 else 0,
                             http_hint=hint)

    async def _worker(self) -> None:
        while True:
            work = await self._queue.get()
            started = time.monotonic()
            try:
                result = await self._execute(work)
                if not self.runtime.running or not self._accepting:
                    await self.runtime._discard(work, result)
                    self._release(work)
                    return
                if result.status == 'completed':
                    self._failures = 0
                else:
                    self._failures += 1
                    if self._failures >= self.policy.failures_before_cooldown:
                        self._cooldown_until = time.monotonic() + self.policy.cooldown_seconds
                self.runtime._completions.put_nowait((self, work, result))
                self.runtime.metrics.increment(f'jobs.{self.name}.{result.status}')
            except asyncio.CancelledError:
                self._release(work)
                raise
            finally:
                self._queue.task_done()
                self.runtime.metrics.observe(f'jobs.{self.name}.duration', time.monotonic() - started)

    async def stop(self) -> None:
        async with self._stop_lock:
            self._accepting = False
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                _, pending = await asyncio.wait(self._tasks, timeout=self.runtime.policy.shutdown_grace_seconds)
                if pending:
                    if self.runtime.legacy_http.active:
                        logger.debug('Background service %s awaits joined urllib requests', self.name)
                    else:
                        logger.error('Background service %s has cancellation-resistant workers', self.name)
            self._tasks = [task for task in self._tasks if not task.done()]
            while not self._queue.empty():
                work = self._queue.get_nowait()
                self._queue.task_done()
                self._release(work)
            await self.runtime.http.close_owner(self.name)


class BackgroundJobs:
    def __init__(self, context: Callable[[], JobContext], metrics: PerformanceMetrics,
                 *, policy: RuntimePolicy = RuntimePolicy()):
        self._context = context
        self.metrics = metrics
        self.policy = policy
        self.http = HttpSessions()
        self.legacy_http = LegacyHttp()
        self._services: dict[str, JobService] = {}
        self._completions: asyncio.Queue = asyncio.Queue(maxsize=policy.max_services * 256)
        self.running = False
        self._closed = False
        self._draining = False
        self._stop_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError('background runtime is closed')
        self.running = True
        for service in self._services.values():
            service.start()

    def service(self, name: str, policy: JobPolicy = JobPolicy()) -> JobService:
        if self._closed:
            raise RuntimeError('background runtime is closed')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name):
            raise ValueError('invalid background service identifier')
        existing = self._services.get(name)
        if existing is not None:
            if existing.policy != policy:
                raise ValueError('service already registered with another policy')
            return existing
        if len(self._services) >= self.policy.max_services:
            raise RuntimeError('background service limit reached')
        service = JobService(self, name, policy)
        self._services[name] = service
        return service

    async def _discard(self, work: _Work, result: JobResult) -> None:
        if work.discard is not None:
            try:
                await work.discard(result)
            except Exception as error:
                logger.error('Background result cleanup failed (%s)', type(error).__name__)

    async def drain(self, *, limit: int | None = None, budget_seconds: float | None = None) -> int:
        """Controller lane only. Budgets apply between short completion handlers."""
        if self._draining:
            raise RuntimeError('completion drain must not run concurrently')
        if not self.running:
            return 0
        if limit is None:
            limit = self.policy.completions_per_tick
        if budget_seconds is None:
            budget_seconds = self.policy.completion_budget_seconds
        count = 0
        started = time.perf_counter()
        self._draining = True
        try:
            while count < limit and time.perf_counter() - started < budget_seconds:
                try:
                    service, work, result = self._completions.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    current = self._context()
                    same_server = (work.job.context.run_id == current.run_id
                                   and work.job.context.server_id == current.server_id)
                    same_map = (work.job.context.map_uid == current.map_uid
                                and work.job.context.map_generation == current.map_generation)
                    if (not service._accepting or (work.revision_guard and work.revision != service._revision)
                            or not same_server or (work.current_map and not same_map)):
                        self.metrics.increment(f'jobs.{service.name}.stale')
                        await self._discard(work, result)
                    else:
                        await work.apply(result)
                except Exception as error:
                    logger.error('Background completion %s failed (%s)', service.name, type(error).__name__)
                    self.metrics.increment(f'jobs.{service.name}.apply_failed')
                    await self._discard(work, result)
                finally:
                    service._release(work)
                    self._completions.task_done()
                count += 1
        finally:
            self._draining = False
        return count

    async def stop(self) -> None:
        async with self._stop_lock:
            self.running = False
            self._closed = True
            # Cancel all domains together, so grace is not multiplied.
            await asyncio.gather(*(service.stop() for service in self._services.values()))
            legacy_callers = self.legacy_http.callers
            await self.legacy_http.close()
            # urllib cannot be cancelled while inside a socket operation. Join
            # its callers before closing the outbox or re-executing the process.
            await asyncio.gather(*(task for service in self._services.values()
                                   for task in service._tasks if task in legacy_callers),
                                 return_exceptions=True)
            while not self._completions.empty():
                service, work, result = self._completions.get_nowait()
                await self._discard(work, result)
                service._release(work)
                self._completions.task_done()
            await self.http.close()
