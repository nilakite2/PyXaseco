"""
plugin_trial_records.py

Trial Records API client for PyXaseco.

This plugin is intentionally self-contained:
- no direct Trial MySQL access
- no .env dependency
- all Trial read/write operations go through the public HTTP API

Configure the API base/token below before deployment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
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
_current_records: list[dict] = []
_last_status_key: tuple[str, bool, int, int] | None = None


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


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _json_request_sync(url: str) -> object:
    req = urllib.request.Request(url, headers=_build_headers())
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) == 404:
                return None
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
    raise last_error or RuntimeError(f"Could not fetch JSON from {url}")


def _json_post_sync(url: str, payload: dict) -> object:
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers()
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
            return json.loads(raw) if raw else {}
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
    raise last_error or RuntimeError(f"Could not POST JSON to {url}")


async def _json_request(url: str) -> object:
    return await asyncio.to_thread(_json_request_sync, url)


async def _json_post(url: str, payload: dict) -> object:
    return await asyncio.to_thread(_json_post_sync, url, payload)


def _normalize_trial_track_payload(payload: object) -> dict | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("track"), dict):
            return dict(payload["track"])
        if isinstance(payload.get("data"), dict):
            nested = _normalize_trial_track_payload(payload.get("data"))
            if isinstance(nested, dict):
                return nested
        if isinstance(payload.get("result"), dict):
            nested = _normalize_trial_track_payload(payload.get("result"))
            if isinstance(nested, dict):
                return nested
        if any(key in payload for key in ("challenge_uid", "uid_primary", "uid_values", "uid_aliases", "tmx_id")):
            return dict(payload)
        return dict(payload)
    return None


def _normalize_trial_records_payload(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [dict(row) for row in records if isinstance(row, dict)]
        data = payload.get("data")
        if isinstance(data, dict):
            return _normalize_trial_records_payload(data)
        result = payload.get("result")
        if isinstance(result, dict):
            return _normalize_trial_records_payload(result)
        return []
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    return []


def _normalize_trial_finish_payload(payload: object) -> dict:
    if isinstance(payload, dict):
        if isinstance(payload.get("result"), dict):
            return dict(payload["result"])
        return dict(payload)
    return {}


def _track_storage_uid(track: dict | None) -> str:
    if not isinstance(track, dict):
        return ""
    return str(track.get("uid_primary") or track.get("challenge_uid") or "").strip()


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
        if isinstance(key, str) and key.startswith("uid_"):
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
        if key in ("challenge_uid", "uid_primary", "uid_values", "uid_aliases"):
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


def _cache_for_uid(uid: str) -> bool:
    if not isinstance(_current_track, dict):
        return False
    return _clean_text(uid) in _track_all_uids(_current_track)


def _track_matches_requested_uid(track: dict | None, uid: str) -> bool:
    uid_text = _clean_text(uid)
    if not uid_text or not isinstance(track, dict):
        return False
    identifiers = _track_all_uids(track)
    return uid_text in identifiers


def _clear_current_cache() -> None:
    global _current_track, _current_records
    _current_track = None
    _current_records = []


def _announce_track_status(aseco: "Aseco", uid: str, active: bool, *, points: int = 0, count: int = 0) -> None:
    global _last_status_key
    key = (_clean_text(uid), bool(active), int(points or 0), int(count or 0))
    if _last_status_key == key:
        return
    _last_status_key = key
    if not active:
        aseco.console("[TrialRecords] Inactive on {1}; fallback to Dedimania", uid)
        return
    suffix = f" (points={points})" if points > 0 else ""
    aseco.console("[TrialRecords] Active on {1}{2}", uid, suffix)
    aseco.console("[TrialRecords] Fetched {1} Trial records for {2}", count, uid)


def _normalise_trial_record(rec: dict, rank: int, challenge_uid: str) -> dict | None:
    if not isinstance(rec, dict):
        return None
    best = _safe_int(rec.get("best_score") or rec.get("Best") or rec.get("Score") or rec.get("score"))
    if best <= 0:
        return None
    login = _clean_text(rec.get("login") or rec.get("Login"))
    if not login:
        return None
    nickname_raw = _clean_text(
        rec.get("player_nickname_raw")
        or rec.get("nickname_raw")
        or rec.get("player_nickname")
        or rec.get("tmx_name")
        or rec.get("PlayerNickname")
        or rec.get("TmxName")
        or rec.get("nickname")
        or rec.get("NickName")
        or rec.get("Nickname")
        or login
    )
    resolved_rank = _safe_int(rec.get("rank") or rec.get("Pos"), rank)
    return {
        "rank": resolved_rank,
        "login": login,
        "nickname_raw": nickname_raw,
        "player_nickname_raw": nickname_raw,
        "player_nickname": _clean_text(rec.get("player_nickname") or rec.get("nickname") or nickname_raw),
        "nickname": _clean_text(rec.get("nickname") or nickname_raw),
        "best_score": best,
        "score": best,
        "score_text": format_time(best),
        "challenge_uid": _clean_text(rec.get("challenge_uid") or challenge_uid),
        "source": _clean_text(rec.get("source") or "trial"),
        "points": rec.get("points"),
        "Login": login,
        "NickName": nickname_raw,
        "Nickname": nickname_raw,
        "Best": best,
        "Score": best,
        "Pos": resolved_rank,
    }


def _normalise_trial_records_for_cache(rows: list[dict], challenge_uid: str) -> list[dict]:
    result: list[dict] = []
    for idx, rec in enumerate(rows or [], start=1):
        row = _normalise_trial_record(rec, idx, challenge_uid)
        if row is not None:
            result.append(row)
    return result


def _merge_record_into_cache(uid: str, login: str, nickname_raw: str, score: int) -> tuple[bool, int, int, int]:
    global _current_track, _current_records

    rows = [dict(r) for r in (_current_records or []) if isinstance(r, dict)]
    changed = False
    existing_rank = 0
    existing_score = 0

    found = False
    for row in rows:
        if _clean_text(row.get("login")).lower() == login.lower():
            found = True
            existing_score = _safe_int(row.get("best_score") or row.get("score"), 0)
            existing_rank = _safe_int(row.get("rank"), 0)
            if existing_score <= 0 or score < existing_score:
                row["best_score"] = score
                row["score"] = score
                row["score_text"] = format_time(score)
                row["nickname_raw"] = nickname_raw or _clean_text(row.get("nickname_raw"))
                row["player_nickname_raw"] = nickname_raw or _clean_text(row.get("player_nickname_raw"))
                row["player_nickname"] = nickname_raw or _clean_text(row.get("player_nickname"))
                row["nickname"] = nickname_raw or _clean_text(row.get("nickname"))
                row["source"] = "online"
                changed = True
            break

    if not found:
        rows.append({
            "rank": 0,
            "login": login,
            "nickname_raw": nickname_raw or login,
            "player_nickname_raw": nickname_raw or login,
            "player_nickname": nickname_raw or login,
            "nickname": nickname_raw or login,
            "best_score": score,
            "score": score,
            "score_text": format_time(score),
            "challenge_uid": uid,
            "source": "online",
            "points": (_current_track or {}).get("points") if isinstance(_current_track, dict) else None,
            "Login": login,
            "NickName": nickname_raw or login,
            "Nickname": nickname_raw or login,
            "Best": score,
            "Score": score,
            "Pos": 0,
        })
        changed = True

    if not changed:
        return False, existing_rank, existing_score, existing_rank

    rows.sort(key=lambda r: (_safe_int(r.get("best_score") or r.get("score"), 2**31 - 1), _clean_text(r.get("login")).lower()))
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
        row["Pos"] = idx
        row["challenge_uid"] = uid
        row["score"] = _safe_int(row.get("best_score") or row.get("score"), 0)
        row["best_score"] = row["score"]
        row["score_text"] = format_time(row["score"]) if row["score"] > 0 else "--"
    _current_records = rows
    if not isinstance(_current_track, dict):
        _current_track = {
            "challenge_uid": uid,
            "uid_primary": uid,
            "uid_values": [uid],
            "uid_aliases": [uid],
            "source": "trial",
        }

    new_rank = 0
    for row in rows:
        if _clean_text(row.get("login")).lower() == login.lower():
            new_rank = _safe_int(row.get("rank"), 0)
            break
    return True, existing_rank, existing_score, new_rank


def is_enabled() -> bool:
    return _enabled


def get_current_track_cache() -> dict | None:
    return dict(_current_track) if isinstance(_current_track, dict) else None


async def get_trial_track(uid: str) -> dict | None:
    if not is_enabled() or not uid:
        return None
    payload = await _json_request(
        f"{_trial_api_base()}/api/trial-tracks/{urllib.parse.quote(str(uid).strip(), safe='')}"
    )
    row = _normalize_trial_track_payload(payload)
    if not isinstance(row, dict) or not row:
        return None
    if not _track_matches_requested_uid(row, uid):
        return None
    row = _with_local_uid(row, uid)
    return row if isinstance(row, dict) and row else None


async def get_trial_records(uid: str, limit: int | None = None) -> list[dict]:
    if not is_enabled() or not uid:
        return []
    payload = await _json_request(
        f"{_trial_api_base()}/api/trial-records/{urllib.parse.quote(str(uid).strip(), safe='')}"
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
    challenge = getattr(aseco.server, "challenge", None)
    uid = str(getattr(challenge, "uid", "") or "").strip()
    if not uid:
        _clear_current_cache()
        return None
    if _cache_for_uid(uid):
        return dict(_current_track)
    await _tr_sync_current_track(aseco)
    if _cache_for_uid(uid):
        return dict(_current_track)
    return None


async def get_current_trial_records(aseco: 'Aseco', limit: int | None = None) -> list[dict]:
    challenge = getattr(aseco.server, "challenge", None)
    uid = str(getattr(challenge, "uid", "") or "").strip()
    if not uid:
        return []
    if not _cache_for_uid(uid):
        await _tr_sync_current_track(aseco)
    if not _cache_for_uid(uid):
        return []
    rows = list(_current_records)
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]
    return rows


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup', _tr_load_settings)
    aseco.register_event('onStartup', _tr_connect)
    aseco.register_event('onSync', _tr_sync_current_track)
    aseco.register_event('onNewChallenge', _tr_sync_current_track)
    aseco.register_event('onPlayerFinish1', _tr_player_finish)
    aseco.register_event('onShutdown', _tr_shutdown)
    aseco.add_chat_command('trialrecs', 'Displays all Trial Records on current track')
    aseco.register_event('onChat_trialrecs', chat_trialrecs)


async def _tr_load_settings(aseco: 'Aseco', _param=None):
    global _enabled
    _enabled = bool(_trial_api_base())
    if _enabled:
        aseco.console("[TrialRecords] Using Trial API '{1}'", _trial_api_base())
    else:
        aseco.console("[TrialRecords] Disabled - configure TRIAL_API_BASE in plugin_trial_records.py")


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

    await _json_post(
        f"{_trial_api_base()}/api/trial-servers/",
        {
            "server_login": server_login,
            "server_name": server_name,
            "game": game,
            "nation": nation,
        },
    )


async def _tr_sync_current_track(aseco: 'Aseco', _param=None):
    global _current_track, _current_records
    if _enabled:
        try:
            await _post_trial_server_heartbeat(aseco)
        except Exception as exc:
            logger.debug("[TrialRecords] Could not refresh Trial server heartbeat: %s", exc)
    challenge = getattr(aseco.server, "challenge", None)
    uid = str(getattr(challenge, "uid", "") or "").strip()
    if not uid:
        _clear_current_cache()
        try:
            aseco.server.trial_records_active = False
        except Exception:
            pass
        return

    try:
        current = await get_trial_track(uid)
    except Exception as exc:
        logger.warning("[TrialRecords] Trial API track lookup failed for %s: %s", uid, exc)
        _clear_current_cache()
        try:
            aseco.server.trial_records_active = False
        except Exception:
            pass
        return

    if not isinstance(current, dict) or not current:
        _clear_current_cache()
        try:
            aseco.server.trial_records_active = False
        except Exception:
            pass
        _announce_track_status(aseco, uid, False)
        return

    if not _track_matches_requested_uid(current, uid):
        _clear_current_cache()
        try:
            aseco.server.trial_records_active = False
        except Exception:
            pass
        logger.info(
            "[TrialRecords] Ignoring mismatched Trial track for requested UID %s: storage_uid=%s aliases=%s",
            uid,
            _track_storage_uid(current) or "?",
            sorted(_track_all_uids(current)),
        )
        _announce_track_status(aseco, uid, False)
        return

    _current_track = dict(_with_local_uid(current, uid) or current)
    try:
        raw_rows = await get_trial_records(uid)
    except Exception as exc:
        logger.warning("[TrialRecords] Trial API record fetch failed for %s: %s", uid, exc)
        raw_rows = []
    _current_records = _normalise_trial_records_for_cache(raw_rows, _track_storage_uid(_current_track) or uid)

    try:
        aseco.server.trial_records_active = True
    except Exception:
        pass
    _announce_track_status(
        aseco,
        _track_storage_uid(_current_track) or uid,
        True,
        points=_safe_int(_current_track.get("points"), 0),
        count=len(_current_records),
    )


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
    global _current_track
    if not is_enabled():
        return
    if not finish or not getattr(finish, 'player', None) or not getattr(finish, 'challenge', None):
        return

    try:
        score = int(getattr(finish, 'score', 0) or 0)
    except Exception:
        score = 0
    if score <= 0:
        return
    if getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1) == Gameinfo.STNT:
        return

    challenge = finish.challenge
    uid = str(getattr(challenge, 'uid', '') or '').strip()
    if not uid:
        return

    current = _current_track
    if not current or uid not in _track_all_uids(current):
        current = await get_current_trial_track(aseco)
    if not current:
        return

    player = finish.player
    login = str(getattr(player, 'login', '') or '').strip()
    nickname = str(getattr(player, 'nickname', '') or login or '?')
    if not login:
        return

    payload = {
        "uid": uid,
        "login": login,
        "nickname": nickname,
        "score": score,
        "source": "online",
    }

    try:
        response = _normalize_trial_finish_payload(
            await _json_post(f"{_trial_api_base()}/api/trial-finish", payload)
        )
    except Exception as exc:
        logger.warning("[TrialRecords] Could not submit live finish for %s on %s: %s", login, uid, exc)
        return

    changed = bool(response.get("changed"))
    returned_track = response.get("track")
    if isinstance(returned_track, dict):
        _current_track = dict(_with_local_uid(returned_track, uid) or returned_track)

    if changed:
        new_rank = int(response.get("new_rank") or 0)
        existing_rank = int(response.get("existing_rank") or 0)
        existing_score = int(response.get("existing_score") or 0)
        new_score = int(response.get("new_score") or score or 0)
        cache_changed, cache_existing_rank, cache_existing_score, cache_new_rank = _merge_record_into_cache(
            _track_storage_uid(_current_track) or uid,
            login,
            nickname,
            new_score,
        )
        if cache_changed:
            if existing_rank <= 0:
                existing_rank = cache_existing_rank
            if existing_score <= 0:
                existing_score = cache_existing_score
            if new_rank <= 0:
                new_rank = cache_new_rank
        await _announce_trial_record(
            aseco,
            nickname,
            new_score,
            existing_rank,
            existing_score,
            new_rank,
        )
        await aseco.release_event('onTrialRecord', {
            'challenge_uid': str(response.get("storage_uid") or _track_storage_uid(_current_track) or uid),
            'login': login,
            'nickname': nickname,
            'score': new_score,
        })
        aseco.console("[TrialRecords] player {1} finished with {2} → Trial best updated", login, new_score)


async def _tr_shutdown(aseco: 'Aseco', _param=None):
    return


async def _send_chat(aseco: 'Aseco', login: str, message: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login
    )


async def chat_trialrecs(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    challenge = getattr(aseco.server, "challenge", None)
    uid = str(getattr(challenge, "uid", "") or "").strip()
    if not uid:
        await _send_chat(aseco, login, '{#server}> {#error}No current challenge UID available.')
        return

    current = await get_current_trial_track(aseco)
    rows = await get_current_trial_records(aseco)

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
