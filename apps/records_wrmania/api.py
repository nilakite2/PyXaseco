"""WRMania v1 protocol from the supplied Mania Records XASECO adapter."""

import asyncio
import hashlib
import hmac
import json
from time import monotonic
from urllib.parse import urlencode, urlsplit

from pyxaseco.core.external_io import read_limited
from pyxaseco.core.http_sessions import HttpPolicy, request_timeout
from pyxaseco.core.service_health import observed_response
from pyxaseco.helpers import format_time


OWNER = 'records_wrmania'
MODES = {0: 'rounds', 1: 'ta', 2: 'rounds', 3: 'ta', 5: 'rounds'}


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'WRMania HTTP {status}')


def base_url(value):
    value = str(value).rstrip('/')
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment or any(c.isspace() for c in value)):
        raise ValueError('WRMania api_base must be an HTTPS origin without credentials or path.')
    return value


def map_data(challenge, mode):
    if (mode not in MODES or not getattr(challenge, 'uid', '')
            or int(getattr(challenge, 'authortime', 0) or 0) < 8000
            or (mode in (0, 2, 5) and getattr(challenge, 'laprace', False)
                and int(getattr(challenge, 'forcedlaps', 0) or 0))):
        return None
    return {'uid': str(challenge.uid), 'name': str(challenge.name),
            'author': str(challenge.author), 'environment': str(challenge.environment),
            'authorTimeMs': int(challenge.authortime), 'nbCheckpoints': int(challenge.nbchecks)}


def fingerprint(track):
    fields = ['TMF', track['uid'], track['author'], track['environment'],
              track['authorTimeMs'], track['nbCheckpoints']]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def valid_checks(checks, score):
    return (isinstance(checks, list) and 1 <= len(checks) <= 512
            and all(type(cp) is int and 0 < cp <= score for cp in checks)
            and all(a < b for a, b in zip(checks, checks[1:])) and checks[-1] == score)


def records(payload, limit=30):
    if not isinstance(payload, list):
        raise ValueError('WRMania records response must contain a list.')
    rows, logins, ranks = [], set(), set()
    for position, raw in enumerate(payload, 1):
        if not isinstance(raw, dict):
            raise ValueError('Invalid WRMania record.')
        login, score, rank = raw.get('login'), raw.get('time_ms'), raw.get('rank', position)
        if (not isinstance(login, str) or not login or type(score) is not int or not 0 < score <= 2147483647
                or type(rank) is not int or rank < 1):
            raise ValueError('Invalid WRMania player, rank or time.')
        if rank > limit or login in logins or rank in ranks:
            continue
        logins.add(login)
        ranks.add(rank)
        nick = str(raw.get('nickname') or login)
        checks = raw.get('checkpointsMs')
        checks = list(checks) if valid_checks(checks, score) else []
        rows.append({**raw, 'rank': rank, 'login': login, 'nickname': nick,
                     'checkpointsMs': checks, 'Checks': checks,
                     'score': score, 'score_text': format_time(score),
                     'Login': login, 'NickName': nick, 'Best': score, 'Score': score, 'Pos': rank})
    return sorted(rows, key=lambda row: row['rank'])


class Client:
    def __init__(self, aseco, values):
        self.aseco, self.values = aseco, dict(values)
        self.base = base_url(values['api_base'])
        self.token, self.expires = '', 0
        self._limit, self.limit_revision = 30, -1
        self.lock = asyncio.Lock()

    @property
    def authenticated(self):
        return bool(self.token) and monotonic() < self.expires

    @property
    def limit(self):
        return self._limit if self.authenticated else 30

    def update_limit(self, data):
        limit, revision = data.get('recordLimit'), data.get('recordLimitRevision')
        if (type(limit) is int and 30 <= limit <= 40 and type(revision) is int
                and revision >= max(0, self.limit_revision) and self.authenticated):
            self._limit, self.limit_revision = limit, revision
        elif revision is None:
            self._limit = 30

    async def request(self, method, path, payload=None, *, auth=True):
        session = self.aseco.jobs.http.get(OWNER, HttpPolicy())
        headers = {'Accept': 'application/json', 'User-Agent': 'PyXaseco-WRMania/1.5'}
        if auth and self.authenticated:
            headers['Authorization'] = 'Bearer ' + self.token
        kwargs = {'headers': headers, 'timeout': request_timeout(self.values['request_timeout']),
                  'allow_redirects': False}
        if payload is not None:
            kwargs['json'] = payload
        async with observed_response(self.aseco, OWNER,
                session.request(method, self.base + path, **kwargs)) as response:
            if response.status == 401:
                self.token, self.expires, self._limit = '', 0, 30
            if response.status not in (200, 201):
                raise ApiError(response.status)
            raw = await read_limited(response, 4 * 1024 * 1024)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('Invalid WRMania response.')
            self.update_limit(data)
            return data

    async def authenticate(self):
        async with self.lock:
            if self.authenticated and monotonic() < self.expires - 120:
                return
            proof = hmac.new(self.values['server_password'].encode(),
                ('WRMania-v1|TMF|' + self.values['server_login']).encode(), hashlib.sha256).hexdigest()
            data = await self.request('POST', '/api/v1/servers/authenticate',
                {'game': 'TMF', 'login': self.values['server_login'],
                 'credentialProof': proof, 'nation': self.values['nation']}, auth=False)
            token, duration = data.get('token'), data.get('expiresInSeconds')
            if (not isinstance(token, str) or not token.startswith('wrms_')
                    or type(duration) is not int or duration < 120):
                raise ValueError('WRMania did not acknowledge authentication.')
            self.token, self.expires = token, monotonic() + duration
            self.update_limit(data)

    async def get_records(self, track, mode):
        query = urlencode({'game': 'TMF', 'uid': track['uid'], 'mode': mode,
                           'fingerprint': fingerprint(track), 'limit': 40})
        data = await self.request('GET', '/api/v1/records?' + query)
        return records(data.get('records'), self.limit)

    async def submit(self, submission):
        return await self.request('POST', '/api/v1/runs', submission)

    async def heartbeat(self, uid, players, name=''):
        payload = {
            'game': 'TMF', 'serverLogin': self.values['server_login'],
            'pluginVersion': '1.5.0', 'mapUid': uid, 'players': players}
        if name:
            payload['serverName'] = ''.join(' ' if ord(char) < 32 or ord(char) == 127 else char
                                           for char in name)[:180]
        await self.request('POST', '/api/v1/servers/heartbeat', payload)
