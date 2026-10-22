"""Small loopback transport. HTTP handlers never mutate live controller state."""

import asyncio
import ipaddress
import json
import logging
import os
from pathlib import Path
import time

from aiohttp import web

from pyxaseco.management.config_store import ManagementError
from pyxaseco.management.credentials import read_identity, read_token
from pyxaseco.management.lifecycle import _write_json
from pyxaseco.management.protocol import RequestVerifier, response_proof
from pyxaseco.management.runtime import KINDS, QueueFull, RuntimeManagement


MAX_RESPONSE = 262144
logger = logging.getLogger(__name__)


def response(data, status=200):
    encoded = json.dumps(data, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_RESPONSE:
        return web.json_response({'error': 'Result exceeds the bounded response size'}, status=413)
    return web.Response(body=encoded, status=status, content_type='application/json', headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


class LocalBridge:
    def __init__(self, aseco, *, host='127.0.0.1', port=0):
        if host not in ('127.0.0.1', '::1') or type(port) is not int or not 0 <= port <= 65535:
            raise ManagementError('Management bridge permits numeric loopback hosts and ports 0-65535 only')
        self.root = Path(aseco._base_dir).resolve()
        self.identity = read_identity(self.root)
        self.token = read_token(self.root)
        self.verifier = RequestVerifier(self.token)
        self.runtime = RuntimeManagement(aseco, self.identity)
        self.host, self.port = host, port
        self.runner = None
        self.allowed_host = None
        self.active = 0
        self.credit, self.credit_at = 40.0, time.monotonic()

    @web.middleware
    async def authorize(self, request, handler):
        now = time.monotonic()
        self.credit = min(40.0, self.credit + (now - self.credit_at) * 20)
        self.credit_at = now
        if self.credit < 1:
            return response({'error': 'Local management request rate exceeded'}, 429)
        self.credit -= 1
        try:
            if not ipaddress.ip_address(request.remote or '').is_loopback:
                return response({'error': 'Loopback clients only'}, 403)
        except ValueError:
            return response({'error': 'Loopback clients only'}, 403)
        if ('Origin' in request.headers or 'Sec-Fetch-Site' in request.headers
                or 'Forwarded' in request.headers
                or any(name.lower().startswith('x-forwarded-') for name in request.headers)
                or request.headers.get('Host') != self.allowed_host or request.query_string):
            return response({'error': 'Browser, forwarded-host and query-string requests are not accepted'}, 403)
        if self.active >= 16:
            return response({'error': 'Too many active management requests'}, 503)
        self.active += 1
        verified = False
        try:
            async with asyncio.timeout(2):
                body = await request.read()
                verified = self.verifier.verify(request.method, request.path_qs, request.headers, body)
                if not verified:
                    return response({'error': 'Signed local authentication required'}, 401)
                if (request.headers.get('X-PyXaseco-Instance') != self.identity['instance_id']
                        or request.headers.get('X-PyXaseco-Run') != self.runtime.aseco._run_id):
                    reply = response({'error': 'Installation/run identity changed; refresh before issuing commands'}, 409)
                elif self.runtime.closing and not (request.method == 'GET' and
                        (request.path == '/v1/status' or request.path.startswith('/v1/operations/'))):
                    reply = response({'error': 'Controller is shutting down; completion may be indeterminate'}, 503)
                else:
                    reply = await handler(request)
        except (TimeoutError, web.HTTPRequestEntityTooLarge):
            reply = response({'error': 'Request exceeded the time or size limit'}, 413)
        except (ValueError, TypeError, KeyError, RecursionError):
            reply = response({'error': 'Invalid management request; input details omitted'}, 400)
        except web.HTTPException as exc:
            reply = response({'error': 'Unsupported management route/method'}, exc.status)
        except Exception as exc:
            logger.warning('Local management handler failed (%s); request contents omitted', type(exc).__name__)
            reply = response({'error': 'Local management request failed'}, 500)
        finally:
            self.active -= 1
        if verified:
            reply.headers['X-PyXaseco-Response'] = response_proof(self.token,
                request.headers['X-PyXaseco-Signature'], reply.status, reply.body)
        return reply

    async def start(self):
        app = web.Application(middlewares=[self.authorize], client_max_size=16384)
        app.router.add_get('/v1/status', self._status)
        app.router.add_get('/v1/apps', self._apps)
        app.router.add_get('/v1/capabilities', self._capabilities)
        app.router.add_get('/v1/operations/{operation_id}', self._result)
        app.router.add_post('/v1/commands', self._command)
        self.runner = web.AppRunner(app, access_log=None, handler_cancellation=True,
            auto_decompress=False, shutdown_timeout=3, keepalive_timeout=5,
            max_line_size=4096, max_field_size=4096)
        try:
            await self.runner.setup()
            await web.TCPSite(self.runner, self.host, self.port, backlog=16).start()
            self.port = self.runner.addresses[0][1]
            address = f'[{self.host}]' if ':' in self.host else self.host
            self.allowed_host = f'{address}:{self.port}'
            descriptor = {'protocol': 1, 'host': self.host, 'port': self.port,
                          'instance_id': self.identity['instance_id'], 'run_id': self.runtime.aseco._run_id}
            endpoint = self.root / '.management-endpoint.json'
            _write_json(endpoint, descriptor)
            os.chmod(endpoint, 0o644)  # Discovery is not a credential and contains no token.
            logger.info('Local management bridge listening on loopback port %s', self.port)
        except BaseException:
            await self.runner.cleanup()
            self.runner = None
            raise

    async def _status(self, _request):
        return response(self.runtime.status())

    async def _apps(self, _request):
        return response({'apps': self.runtime.apps(), 'inventory_ready': self.runtime.catalog_ready,
                         'inventory_refresh_seconds': 5})

    async def _capabilities(self, _request):
        return response({'protocol': 1, 'operations': sorted(KINDS), 'local_role': 'installation-administrator',
                         'authentication': 'hmac-sha256-request-response',
                         'free_text_tmf': False, 'arbitrary_rpc': False, 'shell': False,
                         'queue_limit': 16, 'history_limit': 128, 'history_survives_restart': False})

    async def _result(self, request):
        try:
            return response(self.runtime.get(request.match_info['operation_id']))
        except KeyError:
            return response({'error': 'Unknown/expired operation in this controller run'}, 404)

    async def _command(self, request):
        if request.content_type != 'application/json' or request.headers.get('Content-Encoding', 'identity') != 'identity':
            return response({'error': 'Send uncompressed application/json'}, 415)
        payload = await request.json()
        try:
            result = self.runtime.submit(payload, request.headers.get('X-Request-ID'))
            return response(result, 202)
        except QueueFull as exc:
            return response({'error': str(exc)}, 503)
        except ManagementError as exc:
            return response({'error': str(exc)}, 409)

    async def close(self):
        self.runtime.mark_closing()
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        await self.runtime.close()
        endpoint = self.root / '.management-endpoint.json'
        try:
            if json.loads(endpoint.read_text(encoding='utf-8')).get('run_id') == self.runtime.aseco._run_id:
                endpoint.unlink()
        except (OSError, ValueError):
            pass
