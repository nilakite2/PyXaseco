"""Ultimania v5 client; external writes are single-attempt, not blindly retried."""

import json
from urllib.parse import quote, urlsplit
from uuid import uuid4

from pyxaseco.core.external_io import read_limited
from pyxaseco.core.http_sessions import HttpPolicy, request_timeout
from pyxaseco.core.service_health import observed_response


OWNER = 'records_ultimania'


class MapNotFound(ValueError):
    pass


def base_url(value):
    value = str(value).rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(ch.isspace() for ch in value)):
        raise ValueError('Ultimania api_base must be an HTTP(S) URL without credentials, query or fragment.')
    return value


def records(payload, uid):
    if not isinstance(payload, list):
        raise ValueError('Ultimania records response must be a list.')
    by_login = {}
    for raw in payload:
        if not isinstance(raw, dict) or raw.get('map_uid') != uid or not isinstance(raw.get('player'), dict):
            raise ValueError('Ultimania record has an unexpected map/player identity.')
        login = raw['player'].get('login')
        score = raw.get('score')
        if (not isinstance(login, str) or not login.strip() or isinstance(score, bool)
                or not isinstance(score, (int, str))):
            raise ValueError('Invalid Ultimania player or score.')
        points = int(score)
        if not 0 < points <= 2147483647 or str(score) != str(points):
            raise ValueError('Invalid Ultimania score.')
        nick = str(raw['player'].get('nick') or login)
        row = {**raw, 'login': login, 'nickname': nick, 'score': points, 'score_text': str(points),
               'Login': login, 'NickName': nick, 'Best': points, 'Score': points}
        old = by_login.get(login)
        if old is None or points > old['score']:
            by_login[login] = row
    rows = sorted(by_login.values(), key=lambda row: -row['score'])
    return [{**row, 'rank': i, 'Pos': i} for i, row in enumerate(rows, 1)]


class Client:
    def __init__(self, aseco, base, timeout=15):
        self.aseco, self.base, self.timeout = aseco, base_url(base), timeout

    async def request(self, method, path, payload=None, *, binary=False):
        session = self.aseco.jobs.http.get(OWNER, HttpPolicy())
        headers = {'Accept': 'application/json', 'User-Agent': 'PyXaseco-Ultimania/1.4/API5',
                   'X-Request-Id': uuid4().hex}
        url = self.base + '/api/v5/' + path
        kwargs = {'headers': headers, 'timeout': request_timeout(self.timeout), 'allow_redirects': False}
        if binary:
            headers['Content-Type'] = 'application/octet-stream'
            kwargs['data'] = payload
        elif payload is not None:
            kwargs['json'] = payload
        request = session.request(method, url, **kwargs)
        async with observed_response(self.aseco, OWNER, request) as response:
            raw = await read_limited(response, 4 * 1024 * 1024)
            try:
                data = json.loads(raw) if raw.strip() else None
            except (ValueError, UnicodeError) as error:
                raise ValueError('Ultimania returned a non-JSON response.') from error
            if (method == 'GET' and response.status == 404 and isinstance(data, dict) and isinstance(data.get('error'), dict)
                    and data['error'].get('code') == 'MAP_NOT_FOUND'):
                raise MapNotFound('Map is not registered on Ultimania.')
            response.raise_for_status()
            if not 200 <= response.status < 300 or (isinstance(data, dict) and data.get('error')):
                raise ValueError('Unexpected Ultimania HTTP response.')
            return data

    async def get_records(self, uid):
        return records(await self.request('GET', 'maps/' + quote(uid, safe='') + '/records'), uid)

    async def register_map(self, uid, name):
        await self.request('PUT', 'maps', {'uid': uid, 'name': name})

    async def submit(self, data):
        await self.request('PUT', 'players', {'login': data['login'], 'nick': data['nickname']})
        payload = {'player_login': data['login'], 'map_uid': data['uid'], 'score': data['score']}
        raw = await self.request('PUT', 'records', payload)
        if not isinstance(raw, dict) or raw.get('player_login') != data['login'] or not raw.get('id'):
            raise ValueError('Ultimania did not confirm the submitted player/record ID.')
        saved = records([{**raw, 'player': {'login': data['login'], 'nick': data['nickname']}}], data['uid'])[0]
        if saved['score'] < data['score']:
            raise ValueError('Ultimania did not confirm the submitted score.')
        return saved

    async def replay(self, identifier, content):
        result = await self.request('POST', 'records/' + quote(str(identifier), safe='') + '/replay', content, binary=True)
        if not isinstance(result, dict) or result.get('replay_available') is not True:
            raise ValueError('Ultimania did not acknowledge the replay upload.')
