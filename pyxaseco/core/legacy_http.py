"""The 1.2 urllib transport, isolated from controller callbacks and disk workers."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor


class LegacyHttp:
    def __init__(self, workers=4):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='pyxaseco-http')
        self._slots = asyncio.Semaphore(workers)
        self._active = set()
        self._callers = set()
        self._closed = False

    @property
    def active(self):
        return bool(self._active)

    @property
    def callers(self):
        return tuple(self._callers)

    async def run(self, operation, *args):
        async with self._slots:
            if self._closed:
                raise RuntimeError('legacy HTTP transport is closed')
            future = asyncio.wrap_future(self._executor.submit(operation, *args))
            self._active.add(future)
            caller = asyncio.current_task()
            if caller not in self._callers:
                self._callers.add(caller)
                caller.add_done_callback(self._callers.discard)
            cancelled = False
            try:
                # A cancelled request must finish before its slot can be reused
                # or a controller restart can orphan an in-flight write.
                while not future.done():
                    try:
                        await asyncio.shield(future)
                    except asyncio.CancelledError:
                        cancelled = True
                    except Exception:
                        break
                if cancelled:
                    if not future.cancelled():
                        future.exception()
                    raise asyncio.CancelledError
                return future.result()
            finally:
                self._active.discard(future)

    async def close(self):
        self._closed = True
        if self._active:
            await asyncio.gather(*(asyncio.shield(future) for future in tuple(self._active)),
                                 return_exceptions=True)
        self._executor.shutdown(wait=False, cancel_futures=True)


def _read_response(response, timeout):
    data = bytearray()
    deadline = time.monotonic() + timeout
    read = getattr(response, 'read1', response.read)
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError('legacy HTTP body read timed out')
        chunk = read(65536)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError('external response exceeds byte limit')


def json_request(url, method, body, headers, timeout, attempts=1, observer=None, owner=''):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    for attempt in range(attempts):
        try:
            with observer.request(owner) if observer is not None else nullcontext() as sample:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if sample is not None:
                        sample.http_status = response.status
                    raw = _read_response(response, timeout)
                    text = raw.decode('utf-8', errors='replace').strip()
                    return json.loads(text) if text or method == 'GET' else {}
        except urllib.error.HTTPError as error:
            error.close()
            if method == 'GET' and error.code == 404:
                return None
            if attempt + 1 == attempts:
                raise
        except Exception:
            if attempt + 1 == attempts:
                raise
        time.sleep(1)


def put_file(url, path, headers, timeout, observer=None, owner=''):
    with path.open('rb') as handle:
        size = path.stat().st_size
        if size > 64 * 1024 * 1024:
            raise ValueError('replay exceeds byte limit')
        request = urllib.request.Request(url, data=handle,
            headers={**headers, 'Content-Length': str(size)}, method='PUT')
        try:
            with observer.request(owner) if observer is not None else nullcontext() as sample:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if sample is not None:
                        sample.http_status = response.status
                    return int(response.status or 200)
        except urllib.error.HTTPError as error:
            error.close()
            raise
