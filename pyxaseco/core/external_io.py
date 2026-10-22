"""Bounded pooled requests. An outage is not a definitive empty result."""

from __future__ import annotations

import json

from pyxaseco.core.http_sessions import HttpPolicy, request_timeout
from pyxaseco.core.service_health import observed_response, health_for


async def read_limited(response, limit):
    data = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data) > limit:
            raise ValueError('external response exceeds byte limit')
    return bytes(data)


async def request_json(aseco, owner, method, url, *, payload=None, headers=None, timeout=None):
    session = aseco.jobs.http.get(owner, HttpPolicy())
    kwargs = {'timeout': request_timeout(timeout)} if timeout is not None else {}
    async with observed_response(aseco, owner, session.request(method, url, json=payload, headers=headers, **kwargs)) as response:
        if method == 'GET' and response.status == 404:
            return None
        response.raise_for_status()
        data = await read_limited(response, 4 * 1024 * 1024)
        return json.loads(data) if data.strip() else {}


async def request_legacy_json(aseco, method, url, *, payload=None, headers=None,
                              timeout=30, empty_post=False, owner=''):
    from .legacy_http import json_request
    request_headers = dict(headers or {})
    body = None
    if method == 'POST':
        body = b'' if empty_post and payload is None else json.dumps(payload).encode('utf-8')
        if not (empty_post and payload is None):
            request_headers['Content-Type'] = 'application/json'
    # Restore read retries. Writes stay single-attempt: a lost response is not
    # permission to repeat an external mutation or replay an uncertain record.
    observations = (health_for(aseco), owner) if owner else ()
    return await aseco.jobs.legacy_http.run(json_request, str(url), method, body,
        request_headers, timeout, 2 if method == 'GET' else 1, *observations)
