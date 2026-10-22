"""Authenticated same-host client; never replays writes or falls back to disk edits."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import time
from uuid import uuid4

import aiohttp

from .config_store import ManagementError
from .credentials import read_identity, read_token
from .instances import controller_root
from .protocol import TERMINAL, matches, response_proof, sign_request


class RuntimeClient:
    def __init__(self, root: str | Path):
        self.root = controller_root(root)
        endpoint = self.root / '.management-endpoint.json'
        if endpoint.is_symlink() or endpoint.stat().st_size > 4096:
            raise ManagementError('Unsafe local management discovery file')
        data = json.loads(endpoint.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or type(data.get('protocol')) is not int
                or data['protocol'] != 1 or data.get('host') not in ('127.0.0.1', '::1')
                or type(data.get('port')) is not int or not 1 <= data['port'] <= 65535
                or any(not re.fullmatch(r'[0-9a-f]{32}', str(data.get(key, '')))
                       for key in ('instance_id', 'run_id'))):
            raise ManagementError('Invalid local management discovery file')
        if read_identity(self.root)['instance_id'] != data['instance_id']:
            raise ManagementError('Local management discovery belongs to another installation')
        self.instance_id, self.run_id = data['instance_id'], data['run_id']
        host = '[' + data['host'] + ']' if ':' in data['host'] else data['host']
        self.base = f'http://{host}:{data["port"]}'
        self.token = read_token(self.root)
        self.headers = {'X-PyXaseco-Instance': self.instance_id, 'X-PyXaseco-Run': self.run_id}
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
            timeout=aiohttp.ClientTimeout(total=3), auto_decompress=False,
            connector=aiohttp.TCPConnector(limit=2))
        return self

    async def __aexit__(self, *_exc):
        await self.session.close()
        self.session = None

    async def _request(self, method, path, *, payload=None, request_id=None):
        if self.session is None:
            raise ManagementError('Use the runtime client as an async context manager')
        headers = dict(self.headers)
        if request_id:
            headers['X-Request-ID'] = request_id
        body = b''
        if payload is not None:
            body = json.dumps(payload, allow_nan=False).encode('utf-8')
            if len(body) > 16384:
                raise ManagementError('Operation body exceeds 16 KiB')
            headers['Content-Type'] = 'application/json'
        headers = sign_request(self.token, method, path, headers, body)
        try:
            async with self.session.request(method, self.base + path, data=body, headers=headers,
                                            allow_redirects=False) as reply:
                if reply.content_type != 'application/json' or reply.headers.get('Content-Encoding'):
                    raise ManagementError('Unexpected local management response; no command was replayed')
                raw = bytearray()
                async for chunk in reply.content.iter_chunked(16384):
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        raise ManagementError('Local management response exceeds the size limit')
                if not matches(reply.headers.get('X-PyXaseco-Response'), response_proof(self.token,
                        headers['X-PyXaseco-Signature'], reply.status, raw)):
                    raise ManagementError('Local management response could not be authenticated')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ManagementError('Invalid local management response')
                if reply.status >= 300:
                    # Never echo an untrusted server body that could contain secrets.
                    raise ManagementError(f'Local management HTTP {reply.status}; refresh status/config before retrying')
                return result
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            detail = (f'Completion unknown for request {request_id} in run {self.run_id}; '
                      'query this operation before considering another command') if request_id else 'Local runtime unavailable'
            raise ManagementError(detail + '; no automatic retry or offline write performed') from exc
        except ManagementError as exc:
            if request_id:
                raise ManagementError(f'{exc}; request {request_id} in run {self.run_id}; '
                                      'query completion before considering another command') from exc
            raise

    async def status(self):
        return await self._request('GET', '/v1/status')

    async def apps(self):
        return await self._request('GET', '/v1/apps')

    async def capabilities(self):
        return await self._request('GET', '/v1/capabilities')

    async def result(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            raise ManagementError('Invalid operation ID')
        return await self._request('GET', '/v1/operations/' + request_id)

    async def submit(self, payload, *, request_id=None):
        request_id = request_id or uuid4().hex
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            raise ManagementError('Invalid operation ID')
        return await self._request('POST', '/v1/commands', payload=payload, request_id=request_id)

    async def wait(self, request_id, *, timeout=10):
        if not 0 < timeout <= 60:
            raise ManagementError('Wait timeout must be between 0 and 60 seconds')
        deadline = time.monotonic() + timeout
        while True:
            result = await self.result(request_id)
            if result['state'] in TERMINAL or time.monotonic() >= deadline:
                return result
            await asyncio.sleep(0.25)
