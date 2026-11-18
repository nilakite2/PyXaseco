"""Opt-in, short-lived transfers of saved HUD layouts between servers."""

import hashlib
import json
import os
import re
from urllib.parse import urlsplit

from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.http_sessions import HttpPolicy

from . import hud_layout as layout


CODE = re.compile(r'[0-9]{20}\Z')
DEFAULT_URL = 'https://tmtrialgy.com/api/pyxaseco/hud/v1'
MAX_BYTES = 8192
_JOBS = JobPolicy(capacity=8, workers=2, deadline_seconds=10)
_HTTP = HttpPolicy(connections=2, connect_seconds=3, read_seconds=5, total_seconds=8)


def validate(document):
    if (not isinstance(document, dict) or document.keys() != {'version', 'style', 'density', 'panels'}
            or type(document['version']) is not int or document['version'] != 1
            or not isinstance(document['style'], str) or not 1 <= len(document['style']) <= 80
            or document['density'] not in layout.DENSITIES):
        raise ValueError('Unsupported HUD transfer format.')
    panels = layout.validate_styles({'0': document['panels']}).get('0', {})
    result = {**document, 'panels': panels}
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > MAX_BYTES - 512:
        raise ValueError('HUD transfer is too large.')
    return result


def _settings():
    url = (os.environ.get('PYXASECO_HUD_TRANSFER_URL', '').strip() or DEFAULT_URL).rstrip('/')
    key = os.environ.get('PYXASECO_HUD_TRANSFER_KEY', '').strip()
    if not key:
        raise ValueError('HUD transfer is not configured on this server.')
    details = urlsplit(url)
    if (details.scheme != 'https' or not details.hostname or details.username is not None
            or details.query or details.fragment or not 32 <= len(key) <= 256 or not key.isascii()
            or any(c.isspace() for c in key)):
        raise ValueError('HUD transfer requires a valid HTTPS URL and relay key.')
    return url, key


def available():
    try:
        _settings()
    except ValueError:
        return False
    return True


async def request(hud, player, session, operation, value):
    aseco = hud.aseco
    try:
        endpoint, key = _settings()
        owner = hashlib.sha256(player.login.casefold().encode('utf-8')).hexdigest()
        payload = {'owner': owner}
        payload.update({'layout': validate(value)} if operation == 'export' else {'code': value})
    except ValueError as error:
        await hud.styles.reply(player, '{#error}' + str(error))
        return

    target = hud.preset(player)
    captured = JobEnvelope.capture(aseco.capture_job_context(login=player.login), payload)
    jobs = aseco.jobs.service('hud_transfer', _JOBS)

    async def work(job):
        client = aseco.jobs.http.get('hud_transfer', _HTTP)
        async with client.post(endpoint + '/' + operation, json=job.payload(),
                               headers={'Authorization': 'Bearer ' + key}, allow_redirects=False) as response:
            if response.status in (404, 410) and operation == 'restore':
                return None
            if not 200 <= response.status < 300:
                raise ValueError('HUD relay rejected the request.')
            data = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError('HUD relay response is too large.')
            result = json.loads(data)
        if operation == 'export':
            code = result.get('code') if isinstance(result, dict) else None
            if not isinstance(code, str) or not CODE.fullmatch(code):
                raise ValueError('Invalid HUD transfer code.')
            return code
        return validate(result['layout'])

    async def apply(result):
        if hud.session(player) is not session:
            return
        session.transferring = False
        if result.status != 'completed':
            await hud.styles.reply(player, '{#error}HUD transfer failed. Your saved layout is unchanged.')
        elif operation == 'export':
            await hud.styles.reply(player, f'Private HUD code (15 minutes): {result.value}. '
                                           'Use /hud restore <code> on the other server.')
        elif result.value is None:
            await hud.styles.reply(player, '{#error}HUD code not found, expired, or not for this login.')
        elif hud.preset(player) != target:
            await hud.styles.reply(player, '{#error}Your UI style changed. Run /hud restore again in the desired style.')
        else:
            await hud.apply_transfer(player, session, target, result.value)

    async def discard(_result):
        if hud.session(player) is session:
            session.transferring = False

    outcome = jobs.submit(captured, work, apply, dedupe_key=player.login, discard=discard, current_map=False)
    if outcome == Admission.ACCEPTED:
        session.transferring = True
        await hud.styles.reply(player, 'Preparing HUD transfer...')
    else:
        await hud.styles.reply(player, '{#error}HUD transfer is busy. Try again in a moment.')
