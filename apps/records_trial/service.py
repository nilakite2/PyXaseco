"""
records_trial.py

Trial Records API client for PyXaseco.

This app is intentionally self-contained:
- no direct Trial MySQL access
- no .env dependency
- all Trial read/write operations go through the public HTTP API

Configure the API base/token below before deployment.
"""

from __future__ import annotations

import logging
import textwrap
import time
import urllib.parse
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink_multi, format_time, strip_colors
from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trial API configuration
# ---------------------------------------------------------------------------

TRIAL_API_BASE = "https://tmtrialgy.com"
TRIAL_API_TOKEN = ""


_enabled: bool = False
_current_track: dict | None = None
_last_checked_uid: str = ""
_current_records = []
_runtime_aseco = None
_records_revision = 0


def _trial_api_base() -> str:
    return str(TRIAL_API_BASE or "").rstrip("/")


def _trial_api_token() -> str:
    return str(TRIAL_API_TOKEN or "").strip()


def _build_headers() -> dict[str, str]:
    headers = {
        "User-Agent": "PyXaseco-TrialRecords/1.0",
        "Accept": "application/json, */*",
    }
    token = _trial_api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Trial-Token"] = token
    return headers


def _pick_display_name(*candidates: object) -> str:
    values: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            values.append(text)
    if not values:
        return "?"
    for text in values:
        if "$" in text:
            return text
    return values[0]


async def _json_request(url: str, *, timeout=30) -> object:
    from pyxaseco.core.external_io import request_legacy_json
    return await request_legacy_json(_runtime_aseco, 'GET', url, headers=_build_headers(),
                                     timeout=timeout, owner='records_trial')


async def _json_post(url: str, payload: dict) -> object:
    from pyxaseco.core.external_io import request_legacy_json
    return await request_legacy_json(_runtime_aseco, 'POST', url,
                              payload=payload, headers=_build_headers(), owner='records_trial')


def _normalize_trial_track_payload(payload: object) -> dict | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        if payload.get('ok') is False:
            raise ValueError('Trial track lookup rejected')
        if 'track' in payload and payload['track'] is None:
            return None
        if isinstance(payload.get("track"), dict):
            return dict(payload["track"])
        if isinstance(payload.get("data"), dict):
            return _normalize_trial_track_payload(payload['data'])
        if isinstance(payload.get("result"), dict):
            return _normalize_trial_track_payload(payload['result'])
        if any(key in payload for key in ("storage_uid", "challenge_uid", "uid_primary", "uid_values", "uid_aliases", "tmx_id")):
            return dict(payload)
    raise ValueError('Unexpected Trial track response')


def _normalize_trial_records_payload(payload: object) -> list[dict]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        if payload.get('ok') is False:
            raise ValueError('Trial records lookup rejected')
        records = payload.get("records")
        if isinstance(records, list):
            return [dict(row) for row in records if isinstance(row, dict)]
        data = payload.get("data")
        if isinstance(data, dict):
            return _normalize_trial_records_payload(data)
        result = payload.get("result")
        if isinstance(result, dict):
            return _normalize_trial_records_payload(result)
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    raise ValueError('Unexpected Trial records response')


def _normalize_trial_finish_payload(payload: object) -> dict:
    if isinstance(payload, dict):
        if isinstance(payload.get("result"), dict):
            return dict(payload["result"])
        return dict(payload)
    return {}


def _track_storage_uid(track: dict | None) -> str:
    if not isinstance(track, dict):
        return ""
    return str(track.get("storage_uid") or track.get("uid_primary") or track.get("challenge_uid") or "").strip()


def _with_local_uid(track: dict | None, uid: str) -> dict | None:
    if not isinstance(track, dict):
        return None
    result = dict(track)
    uid_text = str(uid or "").strip()
    if not uid_text:
        return result

    values: list[str] = []
    raw_values = result.get("uid_values")
    if isinstance(raw_values, list):
        for item in raw_values:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)

    raw_aliases = result.get("uid_aliases")
    if isinstance(raw_aliases, list):
        for item in raw_aliases:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)

    for key in ("challenge_uid", "uid_primary"):
        text = str(result.get(key) or "").strip()
        if text and text not in values:
            values.append(text)

    for key, value in result.items():
        if isinstance(key, str) and key.startswith("uid_") and isinstance(value, str):
            text = str(value or "").strip()
            if text and text not in values:
                values.append(text)

    if uid_text not in values:
        values.append(uid_text)

    result["uid_values"] = values
    result["uid_aliases"] = values
    return result


def _track_all_uids(track: dict | None) -> set[str]:
    if not isinstance(track, dict):
        return set()
    result: set[str] = set()
    for key, value in track.items():
        if key in ("storage_uid", "challenge_uid", "uid_primary", "uid_values", "uid_aliases"):
            if isinstance(value, list):
                for item in value:
                    text = str(item or "").strip()
                    if text:
                        result.add(text)
            else:
                text = str(value or "").strip()
                if text:
                    result.add(text)
        elif isinstance(key, str) and key.startswith("uid_"):
            text = str(value or "").strip()
            if text:
                result.add(text)
    return result


def _track_matches_uid(track: dict | None, uid: str) -> bool:
    uid_text = str(uid or "").strip()
    if not uid_text or not isinstance(track, dict):
        return False
    return uid_text in _track_all_uids(track)


def is_enabled() -> bool:
    return _enabled


def get_current_track_cache() -> dict | None:
    return dict(_current_track) if isinstance(_current_track, dict) else None


async def get_trial_track(uid: str, *, timeout=30, include_links=False) -> dict | None:
    if not is_enabled() or not uid:
        return None
    url = f"{_trial_api_base()}/api/trial-tracks/{urllib.parse.quote(str(uid).strip(), safe='')}"
    if include_links:
        url += '?include_links=1'
    payload = await _json_request(url, timeout=timeout)
    row = _normalize_trial_track_payload(payload)
    if isinstance(row, dict) and not _track_matches_uid(row, uid):
        logger.info(
            "[TrialRecords] Ignoring mismatched Trial track for %s; API returned %s",
            uid,
            _track_storage_uid(row) or "?",
        )
        raise ValueError('Trial track identity mismatch')
    row = _with_local_uid(row, uid)
    return row if isinstance(row, dict) and row else None


async def get_trial_records(uid: str, limit: int | None = None, *, timeout=30) -> list[dict]:
    if not is_enabled() or not uid:
        return []
    payload = await _json_request(
        f"{_trial_api_base()}/api/trial-records/{urllib.parse.quote(str(uid).strip(), safe='')}", timeout=timeout
    )
    rows = _normalize_trial_records_payload(payload)
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]
    return rows


async def get_trial_record_runs(uid: str, limit: int = 100) -> list[dict]:
    if not is_enabled() or not uid:
        return []
    payload = await _json_request(
        f"{_trial_api_base()}/api/trial-record-runs/{urllib.parse.quote(str(uid).strip(), safe='')}?limit={int(limit)}"
    )
    if isinstance(payload, dict):
        runs = payload.get("runs")
        if isinstance(runs, list):
            return [dict(row) for row in runs if isinstance(row, dict)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    return []


async def get_current_trial_track(aseco: 'Aseco') -> dict | None:
    uid = str(getattr(aseco.server.challenge, 'uid', '') or '')
    if _track_matches_uid(_current_track, uid):
        return dict(_current_track)
    if _last_checked_uid != uid:
        await _tr_sync_current_track(aseco)
    return None


async def get_current_trial_records(aseco: 'Aseco', limit=None) -> list[dict]:
    if not _track_matches_uid(_current_track, str(aseco.server.challenge.uid)):
        return []
    rows = list(_current_records)
    return rows[:limit] if limit else rows


def register(aseco: 'Aseco'):
    global _runtime_aseco, _current_records, _current_track, _last_checked_uid, _records_revision
    _runtime_aseco = aseco
    _current_records, _current_track, _last_checked_uid, _records_revision = [], None, '', 0
    aseco.register_event('onStartup', _tr_load_settings)
    aseco.register_event('onStartup', _tr_connect)
    aseco.register_event('onSync', _tr_sync_current_track)
    aseco.register_event('onNewChallenge', _tr_sync_current_track)
    aseco.register_event('onRestartChallenge', _tr_sync_current_track)
    aseco.register_event('onPlayerFinish1', _tr_player_finish)
    aseco.register_event('onShutdown', _tr_shutdown)
    aseco.add_chat_command('trialrecs', 'Displays all Trial Records on current track')
    aseco.register_event('onChat_trialrecs', chat_trialrecs)
    aseco.add_chat_command('trialinfo', 'Displays Trial API information about the current track')
    aseco.register_event('onChat_trialinfo', chat_trialinfo)
    aseco.add_chat_command('trialpb', 'Displays your Trial personal best and saved checkpoint statistics')
    aseco.register_event('onChat_trialpb', chat_trialpb)


async def _tr_load_settings(aseco: 'Aseco', _param=None):
    global _enabled
    _enabled = bool(_trial_api_base())
    if _enabled:
        aseco.console("[TrialRecords] Using Trial API '{1}'", _trial_api_base())
        _trial_delivery(aseco)
    else:
        aseco.console("[TrialRecords] Disabled - configure TRIAL_API_BASE for app/records_trial")


async def _tr_connect(aseco: 'Aseco', _param=None):
    if not _enabled:
        return
    try:
        await _post_trial_server_heartbeat(aseco)
    except Exception as exc:
        logger.warning("[TrialRecords] Could not send Trial server heartbeat on startup: %s", exc)


async def _post_trial_server_heartbeat(aseco: 'Aseco') -> None:
    server_obj = getattr(aseco, "server", None)
    server_login = str(getattr(server_obj, "serverlogin", "") or "").strip()
    if not server_login:
        return
    server_name = strip_colors(str(getattr(server_obj, "name", "") or "").strip(), for_tm=False).strip()
    game = str(
        getattr(server_obj, "game", "")
        or getattr(getattr(server_obj, "gameinfo", None), "game", "")
        or "TMF"
    ).strip() or "TMF"
    nation = str(getattr(server_obj, "nation", "") or "").strip()
    if not nation:
        zone = str(getattr(server_obj, "zone", "") or "").strip()
        if zone:
            nation = zone.split("|", 1)[0].strip()
    if not nation:
        nation = "World"

    payload = {
            "server_login": server_login,
            "server_name": server_name,
            "game": game,
            "nation": nation,
        }
    from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
    service = aseco.jobs.service('trial_heartbeat', JobPolicy(capacity=1))
    job = JobEnvelope.capture(aseco.capture_job_context(), payload)
    async def operation(envelope):
        return await _json_post(f"{_trial_api_base()}/api/trial-servers/", envelope.payload())
    async def apply(_result):
        return
    service.submit(job, operation, apply, current_map=False, dedupe_key='heartbeat')


async def _load_trial_snapshot(uid):
    track = await get_trial_track(uid)
    rows = await get_trial_records(uid) if track else []
    storage_uid = _track_storage_uid(track)
    if track and not rows and storage_uid and storage_uid != uid:
        rows = await get_trial_records(storage_uid)
    return track, rows


async def _tr_sync_current_track(aseco: 'Aseco', _param=None):
    global _current_track, _current_records, _last_checked_uid
    if not _enabled:
        return
    from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
    uid = str(aseco.server.challenge.uid)
    if _last_checked_uid != uid:
        _current_track, _current_records = None, []
        aseco.server.trial_records_active = False
    job = JobEnvelope.capture(aseco.capture_job_context(), {'uid': uid})
    revision = _records_revision
    async def operation(envelope):
        return await _load_trial_snapshot(envelope.payload()['uid'])
    async def apply(result):
        global _current_track, _current_records, _last_checked_uid
        if result.status != 'completed':
            logger.warning('[TrialRecords] Lookup unavailable (%s)', result.failure_label)
            return
        if revision != _records_revision:
            return
        _current_track, _current_records = result.value
        _last_checked_uid = uid
        aseco.server.trial_records_active = bool(_current_track)
        await aseco.release_event('onTrialRecordsLoaded', uid)
    aseco.jobs.service('trial_lookup', JobPolicy(deadline_seconds=120)).submit(
        job, operation, apply, dedupe_key=f'current:{revision}')


async def _announce_trial_record(aseco: 'Aseco', nickname: str, score: int, existing_rank: int, existing_score: int, new_rank: int) -> None:
    nickname_text = strip_colors(str(nickname or '?'))
    time_text = format_time(score)
    diff = max(int(existing_score or 0) - int(score or 0), 0)

    if existing_rank <= 0 or new_rank <= 0:
        msg = (
            f'{{#server}}>> {{#highlite}}{nickname_text}{{#dedirec}} claimed the '
            f'{{#rank}}{new_rank}{{#dedirec}}. Trial Record!  '
            f'Time: {{#highlite}}{time_text}'
        )
    elif new_rank < existing_rank:
        msg = (
            f'{{#server}}>> {{#highlite}}{nickname_text}{{#dedirec}} gained the '
            f'{{#rank}}{new_rank}{{#dedirec}}. Trial Record!  '
            f'Time: {{#highlite}}{time_text}{{#dedirec}} '
            f'$n({{#rank}}{existing_rank}{{#highlite}} -{format_time(diff)}{{#dedirec}})'
        )
    else:
        msg = (
            f'{{#server}}>> {{#highlite}}{nickname_text}{{#dedirec}} secured his/her '
            f'{{#rank}}{new_rank}{{#dedirec}}. Trial Record!  '
            f'Time: {{#highlite}}{time_text}{{#dedirec}} '
            f'$n({{#rank}}{new_rank}{{#highlite}} -{format_time(diff)}{{#dedirec}})'
        )

    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))


async def _tr_player_finish(aseco: 'Aseco', finish):
    if not is_enabled() or not finish or not getattr(finish, 'player', None):
        return
    score = int(getattr(finish, 'score', 0) or 0)
    if score <= 0 or aseco.server.gameinfo.mode == Gameinfo.STNT:
        return
    uid = str(getattr(getattr(finish, 'challenge', None), 'uid', '') or '')
    if not uid:
        return
    if _last_checked_uid == uid and not _current_track:
        return
    payload = {'uid': uid, 'login': finish.player.login,
               'nickname': str(finish.player.nickname), 'score': score, 'source': 'online'}
    await _trial_delivery(aseco).retain(payload, map_uid=uid)


def _trial_delivery(aseco):
    from pyxaseco.core.retained_delivery import delivery, PreparationRejected
    async def prepare(data):
        # The captured map can be active even if its lookup is still loading.
        if not await get_trial_track(data['uid']):
            raise PreparationRejected('Captured map is not Trial-enabled')
        return data
    async def send(data):
        response = _normalize_trial_finish_payload(await _json_post(
            f"{_trial_api_base()}/api/trial-finish", data))
        if (response.get('ok') is not True or not isinstance(response.get('changed'), bool)
                or not _track_matches_uid(response.get('track'), data['uid'])
                or str(response.get('login') or '') != data['login']
                or int(response.get('score') or 0) != data['score']):
            raise RuntimeError('Unconfirmed Trial finish response')
        return response
    async def apply(data, response, current):
        global _current_track, _records_revision
        track = response.get('track')
        if current and isinstance(track, dict):
            _current_track = dict(_with_local_uid(track, data['uid']) or track)
        if not response.get('changed'):
            return
        if current:
            _records_revision += 1
        new_score = int(response.get('new_score') or data['score'])
        # Old-map responses stay retained/delivered but cannot redraw current UI.
        if current:
            await _announce_trial_record(aseco, data['nickname'], new_score,
                int(response.get('existing_rank') or 0), int(response.get('existing_score') or 0),
                int(response.get('new_rank') or 0))
            await _tr_sync_current_track(aseco)
            await aseco.release_event('onTrialRecord', {
                'challenge_uid': str(response.get('storage_uid') or data['uid']),
                'login': data['login'], 'nickname': data['nickname'], 'score': new_score})
    return delivery(aseco, 'trial_records', send, apply, prepare=prepare)


async def _tr_shutdown(aseco: 'Aseco', _param=None):
    return


async def _send_chat(aseco: 'Aseco', login: str, message: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login
    )


async def chat_trialinfo(aseco: 'Aseco', command: dict):
    await _chat_trial_details(aseco, command)


async def chat_trialpb(aseco: 'Aseco', command: dict):
    await _chat_trial_details(aseco, command, personal=True)


async def _load_trial_pb(uid, login):
    from . import info
    track = await get_trial_track(uid, timeout=12)
    result = {'track': track, 'record': None, 'stats': [], 'unavailable': False, 'limited': False, 'run': None}
    if not track:
        return result
    records = await get_trial_records(uid, timeout=12)
    storage_uid = _track_storage_uid(track)
    if not records and storage_uid and storage_uid != uid:
        records = await get_trial_records(storage_uid, timeout=12)
    record = info.personal_record(records, login)
    result['record'] = record
    if record is None:
        return result
    try:
        params = urllib.parse.urlencode({'login': record['best_login'], 'limit': 5000})
        endpoint = urllib.parse.quote(uid, safe='')
        payload = await _json_request(
            f'{_trial_api_base()}/api/trial-checkpoint-runs/{endpoint}?{params}', timeout=12)
        result['stats'], result['run'], result['limited'] = info.personal_splits(
            payload, _track_all_uids(track), record)
    except Exception as error:
        logger.warning('[TrialRecords] Personal checkpoint information unavailable (%s)', type(error).__name__)
        result['unavailable'] = True
    return result


async def _chat_trial_details(aseco: 'Aseco', command: dict, *, personal=False):
    player = command['author']
    login = player.login
    name = 'trialpb' if personal else 'trialinfo'
    if (command.get('params') or '').strip():
        await _send_chat(aseco, login, f'{{#server}}> Usage: /{name} (current track).')
        return
    if not is_enabled():
        await _send_chat(aseco, login, '{#server}> {#error}Trial records are disabled.')
        return
    uid = str(getattr(aseco.server.challenge, 'uid', '') or '').strip()
    if not uid:
        await _send_chat(aseco, login, '{#server}> {#error}No current challenge UID available.')
        return

    from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
    from . import info
    job = JobEnvelope.capture(aseco.capture_job_context(login=login), {'uid': uid, 'login': login})

    async def operation(envelope):
        requested_uid = envelope.payload()['uid']
        if personal:
            return await _load_trial_pb(requested_uid, envelope.payload()['login'])
        track = await get_trial_track(requested_uid, include_links=True)
        if not track:
            return {'track': None, 'stats': [], 'unavailable': False}
        try:
            endpoint = urllib.parse.quote(requested_uid, safe='')
            payload = await _json_request(
                f'{_trial_api_base()}/api/trial-checkpoint-stats/{endpoint}', timeout=12)
            stats = info.checkpoint_stats(payload, _track_all_uids(track))
        except Exception as error:
            logger.warning('[TrialRecords] Checkpoint information unavailable (%s)', type(error).__name__)
            return {'track': track, 'stats': [], 'unavailable': True}
        return {'track': track, 'stats': stats, 'unavailable': False}

    async def apply(result):
        if aseco.server.players.get_player(login) is not player:
            return
        if result.status != 'completed':
            await _send_chat(aseco, login, '{#server}> {#error}Trial information unavailable; please try again later.')
            return
        data = result.value
        track, stats, unavailable = data['track'], data['stats'], data['unavailable']
        if not track:
            await _send_chat(aseco, login, '{#server}> {#error}Current track was not found on the Trial API.')
            return
        if personal and data['record'] is None:
            await _send_chat(aseco, login, '{#server}> No saved Trial personal best for you on this map.')
            return
        title = ('$zTrial PB: {#black}' if personal else '$zTrial Info: {#black}') + _trialinfo_text(track.get('name') or uid)
        rows = _trialpb_rows(data) if personal else _trialinfo_rows(track)

        def valid_page(controller, viewer):
            context = controller.capture_job_context(login=login)
            return (viewer is player
                    and controller.server.players.get_player(login) is player
                    and context == job.context)

        await info.show(aseco, player, title, rows, stats, valid_page,
                        unavailable=unavailable, personal=personal)

    outcome = aseco.jobs.service('trial_lookup', JobPolicy(deadline_seconds=120)).submit(
        job, operation, apply, dedupe_key=f'{name}:{id(player)}')
    if outcome == Admission.ACCEPTED:
        message = 'Loading your Trial personal best...' if personal else 'Loading fresh Trial information...'
        await _send_chat(aseco, login, '{#server}> ' + message)
    elif outcome != Admission.DUPLICATE:
        await _send_chat(aseco, login, '{#server}> {#error}Trial lookup busy; please try again shortly.')


def _trialinfo_text(value):
    return str(value).replace('$', '$$')


def _trialpb_rows(data):
    track, record = data['track'], data['record']
    values = [('Track', track.get('name') or track.get('uid_primary')),
              ('Player', record['nickname']), ('Login', record['best_login']),
              ('Trial rank', record['rank']), ('PB time', format_time(record['best_score'])),
              ('List', track.get('note'))]
    if data['run']:
        values.append(('Run source', data['run'].get('source') or 'Unknown'))
        respawns = [row['respawns_segment'] for row in data['stats']]
        if any(value is not None for value in respawns):
            suffix = ' (partial)' if any(value is None for value in respawns) else ''
            values.append(('Recorded respawns', str(int(sum(value or 0 for value in respawns))) + suffix))
    if data['limited']:
        values.append(('Checkpoint search', 'API limit reached; only complete matching PB runs can be displayed.'))
    rows = []
    for label, value in values:
        if value is None or str(value).strip() == '':
            continue
        for index, line in enumerate(textwrap.wrap(str(value), width=64)):
            rows.append(['$z' + label if index == 0 else '', '{#black}' + _trialinfo_text(line)])
    return rows


def _trialinfo_link(url, label):
    try:
        parsed = urllib.parse.urlsplit(str(url or '').strip())
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return ''
        if any(char in parsed.netloc for char in '[]$'):
            return ''
        # TMF browser links require HTTP, including links returned as HTTPS by the API.
        target = urllib.parse.urlunsplit(parsed._replace(scheme='http'))
        target = target.replace('[', '%5B').replace(']', '%5D').replace('$', '%24')
        if any(char.isspace() or ord(char) < 32 for char in target):
            return ''
        return f'$z$l[{target}]{label}$l'
    except ValueError:
        return ''


def _trialinfo_map_links(track):
    official = ''
    links = track.get('map_links')
    for item in links if isinstance(links, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            url = urllib.parse.urlsplit(str(item.get('url') or ''))
            if (url.scheme not in ('http', 'https') or url.hostname not in ('tmrpgtrial.com', 'www.tmrpgtrial.com')
                    or url.username or url.password or url.port is not None):
                continue
            map_id = url.path.removeprefix('/map/')
            if (not url.path.startswith('/map/') or not 1 <= len(map_id) <= 191
                    or not map_id.isascii() or not map_id.replace('-', '').replace('_', '').isalnum()):
                continue
            official = _trialinfo_link(f'http://tmrpgtrial.com/map/{map_id}', 'Open map on tmrpgtrial.com')
            break
        except ValueError:
            continue
    rows = [['$zTrial page', official or '$zNot available']]
    tmx_id = int(track.get('tmx_id') or 0)
    if tmx_id > 0:
        path = f'/trial/{tmx_id}'
        if track.get('tmx_section'):
            path += '?' + urllib.parse.urlencode({'section': track['tmx_section']})
    else:
        uid = str(track.get('uid_primary') or track.get('challenge_uid') or _track_storage_uid(track) or '')
        path = '/trial/uid/' + urllib.parse.quote(uid, safe='') if uid else ''
    if path:
        link = _trialinfo_link(_trial_api_base() + path, 'Open map on TMTG')
        if link:
            rows.append(['$zTMTG', link])
    return rows


def _trialinfo_rows(track):
    rows = []

    def add(label, value):
        if value is None or str(value).strip() == '':
            return
        for index, line in enumerate(textwrap.wrap(str(value), width=64)):
            rows.append(['$z' + label if index == 0 else '', '{#black}' + _trialinfo_text(line)])

    add('Track', track.get('name'))
    add('Author', track.get('author'))
    add('Environment', track.get('environment'))
    add('Points', track.get('points'))
    if 'enabled' in track:
        add('Trial enabled', 'No' if str(track['enabled']).strip().lower() in ('0', 'false', 'no', '') else 'Yes')
    add('Records', track.get('total_records'))
    best = int(track.get('best_score') or 0)
    add('Best time', format_time(best) if best > 0 else 'No records')
    add('TMX section', track.get('tmx_section'))
    tmx_id = int(track.get('tmx_id') or 0)
    if tmx_id > 0:
        add('TMX ID', tmx_id)
    rows.extend(_trialinfo_map_links(track))
    tmx_link = _trialinfo_link(track.get('tmx_url'), 'Open map on TMX')
    if tmx_link:
        rows.append(['$zTMX page', tmx_link])
    add('Added', track.get('created_at'))
    add('Updated', track.get('updated_at'))
    add('Last synced', track.get('last_synced_at'))
    add('List', track.get('note'))
    if track.get('raw_name') != track.get('name'):
        add('Original name', track.get('raw_name'))
    if track.get('normalized_name') != track.get('name'):
        add('Normalized name', track.get('normalized_name'))
    add('Track ID', track.get('track_id') or track.get('id'))
    add('Primary UID', track.get('uid_primary') or track.get('challenge_uid'))
    storage_uid = _track_storage_uid(track)
    if storage_uid != (track.get('uid_primary') or track.get('challenge_uid')):
        add('Storage UID', storage_uid)
    shown_uids = {str(track.get('uid_primary') or track.get('challenge_uid') or ''), storage_uid}
    for uid in _track_all_uids(track):
        if uid not in shown_uids:
            add('UID alias', uid)
            shown_uids.add(uid)
    return rows


async def chat_trialrecs(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    challenge = getattr(aseco.server, "challenge", None)
    uid = str(getattr(challenge, "uid", "") or "").strip()
    if not uid:
        await _send_chat(aseco, login, '{#server}> {#error}No current challenge UID available.')
        return

    if not _enabled:
        await _send_chat(aseco, login, '{#server}> {#error}Trial records are disabled.')
        return
    from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
    job = JobEnvelope.capture(aseco.capture_job_context(), {'uid': uid})
    async def operation(envelope):
        return await _load_trial_snapshot(envelope.payload()['uid'])
    async def apply(result):
        if aseco.server.players.get_player(login) is not player:
            return
        if result.status != 'completed':
            await _send_chat(aseco, login, '{#server}> {#error}Trial records unavailable; please try again later.')
            return
        current, rows = result.value
        await _show_trialrecs(aseco, player, current, rows)
    outcome = aseco.jobs.service('trial_lookup', JobPolicy(deadline_seconds=120)).submit(
        job, operation, apply, dedupe_key=f'command:{id(player)}')
    if outcome == Admission.ACCEPTED:
        await _send_chat(aseco, login, '{#server}> Loading fresh Trial records...')
    elif outcome != Admission.DUPLICATE:
        await _send_chat(aseco, login, '{#server}> {#error}Trial records busy; please try again shortly.')


async def _show_trialrecs(aseco, player, current, rows):
    login = player.login
    if not current and not rows:
        await _send_chat(aseco, login, '{#server}> {#error}Current track is not Trial-enabled.')
        return
    if not rows:
        await _send_chat(aseco, login, '{#server}> {#error}No Trial records available.')
        return

    show_logins = True
    extra = 0.2 if getattr(aseco.settings, 'lists_colornicks', False) else 0
    table_rows = []
    for idx, row in enumerate(rows, start=1):
        rec_login = str(row.get('login') or '?')
        nick = _pick_display_name(
            row.get('player_nickname_raw'),
            row.get('nickname_raw'),
            row.get('player_nickname'),
            row.get('tmx_name'),
            row.get('PlayerNickname'),
            row.get('TmxName'),
            row.get('nickname'),
            row.get('NickName'),
            row.get('Nickname'),
            rec_login,
        )
        try:
            score = format_time(int(row.get('best_score') or row.get('score') or 0))
        except Exception:
            score = '--'
        if show_logins:
            table_rows.append([f'{idx:02d}.', '{#black}' + nick, '{#login}' + rec_login, score])
        else:
            table_rows.append([f'{idx:02d}.', '{#black}' + nick, score])

    maxrank = max(len(rows), 1)
    if show_logins:
        widths = [1.2 + extra, 0.1, 0.45 + extra, 0.4, 0.25]
    else:
        widths = [0.8 + extra, 0.1, 0.45 + extra, 0.25]
    pages = [table_rows[i:i+15] for i in range(0, len(table_rows), 15)]
    player.msgs = [[1, f'Current TOP {maxrank} Trial Records:', widths, ['BgRaceScore2', 'Podium']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)
