"""
records_rpg.py

RPG Records API client + replay uploader for PyXaseco.

Behavior:
  - fetch current challenge RPG records from tmrpg.com once per new challenge
  - treat PyXaseco as source of truth for live local-record uploads
  - save the local-record replay via SaveBestGhostsReplay(login, filename)
  - upload the saved .Replay.Gbx through the presigned upload flow
  - delete the local replay file only after a successful upload
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink_multi, format_time, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)
_lookup_uid = ''
_runtime_aseco = None
_records_revision = 0


PLUGIN_VERSION = "1.0.0"

RPG_API_BASE = "https://www.tmrpg.com"
RPG_API_TOKEN = ""
RPG_RECORDS_PATH_TMPL = "/api/pyxaseco/maps/{uid}/records"
RPG_CREATE_REPLAY_URL_PATH = "/createReplayUrl"

RPG_REPLAY_WAIT_SECONDS = 20.0
RPG_REPLAY_STABLE_DELAY_SECONDS = 0.35
RPG_SAVE_SUBDIR = "PyXasecoRPG"
RPG_DELETE_AFTER_UPLOAD = True
RPG_STORAGE_MAX_FILES = 1000
RPG_STORAGE_MAX_BYTES = 2 * 1024 * 1024 * 1024


_enabled: bool = False
_current_track: dict | None = None
_current_records: list[dict] = []


def _api_base() -> str:
    return str(RPG_API_BASE or "").rstrip("/")


def _api_token() -> str:
    return str(RPG_API_TOKEN or "").strip()


def _build_headers() -> dict[str, str]:
    headers = {
        "User-Agent": f"PyXaseco-RPGRecords/{PLUGIN_VERSION}",
        "Accept": "application/json, */*",
    }
    token = _api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-RPG-Token"] = token
    return headers


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _safe_path_component(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "unknown"


def _track_uid(challenge) -> str:
    return _clean_text(getattr(challenge, "uid", ""))


def _replays_root(aseco: "Aseco") -> Path:
    gamedir = Path(str(getattr(getattr(aseco, "server", None), "gamedir", "") or "")).resolve()
    return gamedir / "Tracks" / "Replays"


def _build_saved_replay_relative_path(challenge, login: str, score: int) -> str:
    from uuid import uuid4
    track_uid = _track_uid(challenge) or "unknown_uid"
    safe_login = _safe_path_component(login)
    safe_uid = _safe_path_component(track_uid)
    filename = f"{safe_uid}__{safe_login}__{int(score)}__{uuid4().hex}.Replay.Gbx"
    return str(Path(RPG_SAVE_SUBDIR) / filename).replace("\\", "/")


def _resolve_saved_replay_path(aseco: "Aseco", relative_path: str) -> Path:
    rel = str(relative_path or "").replace("/", os.sep).replace("\\", os.sep).strip("\\/")
    return _replays_root(aseco) / Path(rel)


def _replay_storage_available(directory: Path) -> bool:
    count, size = 0, 0
    if not directory.exists():
        return True
    for path in directory.glob('*.Replay.Gbx'):
        count += 1
        try:
            size += path.stat().st_size
        except FileNotFoundError:
            continue
        if count >= RPG_STORAGE_MAX_FILES or size >= RPG_STORAGE_MAX_BYTES:
            return False
    return True


def _rpg_records_url(uid: str) -> str:
    path = RPG_RECORDS_PATH_TMPL.format(uid=urllib.parse.quote(str(uid).strip(), safe=""))
    return f"{_api_base()}{path}"


async def _json_request(url: str):
    from pyxaseco.core.external_io import request_legacy_json
    return await request_legacy_json(_runtime_aseco, 'GET', url, headers=_build_headers(), owner='records_rpg')


async def _json_post(url: str, payload=None):
    from pyxaseco.core.external_io import request_legacy_json
    return await request_legacy_json(_runtime_aseco, 'POST', url,
                              payload=payload, headers=_build_headers(), empty_post=True, owner='records_rpg')


async def _put_file(url: str, path: Path):
    from pyxaseco.core.legacy_http import put_file
    from pyxaseco.core.service_health import health_for
    return await _runtime_aseco.jobs.legacy_http.run(put_file, url, path, {
        'Content-Type': 'application/octet-stream',
        'User-Agent': f'PyXaseco-RPGRecords/{PLUGIN_VERSION}',
    }, 60, health_for(_runtime_aseco), 'records_rpg')


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _normalize_rpg_record(rec: dict, rank: int, stars: int, challenge_uid: str) -> dict | None:
    if not isinstance(rec, dict):
        return None
    best = _safe_int(rec.get("best_score") or rec.get("score") or rec.get("Best") or rec.get("Score"))
    if best <= 0:
        return None
    login = _clean_text(rec.get("login") or rec.get("Login"))
    if not login:
        return None
    nickname_raw = _clean_text(
        rec.get("nickname_raw")
        or rec.get("player_nickname_raw")
        or rec.get("nickname")
        or rec.get("player_nickname")
        or rec.get("NickName")
        or login
    )
    challenge_uid = _clean_text(rec.get("challenge_uid") or challenge_uid)
    resolved_rank = _safe_int(rec.get("rank"), rank)
    return {
        "rank": resolved_rank,
        "login": login,
        "nickname_raw": nickname_raw,
        "nickname": _clean_text(rec.get("nickname") or rec.get("player_nickname") or nickname_raw),
        "best_score": best,
        "score": best,
        "score_text": format_time(best),
        "challenge_uid": challenge_uid,
        "source": "tmrpg",
        "stars": stars,
        "Login": login,
        "NickName": nickname_raw,
        "Best": best,
        "Score": best,
        "Pos": resolved_rank,
    }


def _normalize_rpg_records_payload(payload: object, requested_uid: str) -> tuple[dict | None, list[dict]]:
    if payload is None:
        return None, []
    if not isinstance(payload, dict) or payload.get('ok') is False:
        raise ValueError('Unexpected RPG records response')
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise ValueError('Missing RPG records list')

    challenge_uid = _clean_text(payload.get("challenge_uid") or requested_uid)
    if challenge_uid != requested_uid:
        raise ValueError('RPG track identity mismatch')
    stars = _safe_int(payload.get("stars"), 0)
    rtype = _safe_int(payload.get("type"), 0)

    rows: list[dict] = []
    for idx, rec in enumerate(raw_records, start=1):
        if isinstance(rec, dict) and _clean_text(rec.get('challenge_uid') or challenge_uid) != challenge_uid:
            raise ValueError('RPG record identity mismatch')
        row = _normalize_rpg_record(rec, idx, stars, challenge_uid)
        if row is not None:
            rows.append(row)

    if not rows:
        return None, []

    track = {
        "challenge_uid": challenge_uid,
        "uid_primary": challenge_uid,
        "uid_values": [challenge_uid],
        "uid_aliases": [challenge_uid],
        "stars": stars,
        "type": rtype,
        "source": "tmrpg",
    }
    return track, rows


def _storage_uid(track: dict | None) -> str:
    if not isinstance(track, dict):
        return ""
    return _clean_text(track.get("challenge_uid") or track.get("uid_primary"))


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


def _track_all_uids(track: dict | None) -> set[str]:
    if not isinstance(track, dict):
        return set()
    values: set[str] = set()
    for key in ("challenge_uid", "uid_primary"):
        text = _clean_text(track.get(key))
        if text:
            values.add(text)
    for key in ("uid_values", "uid_aliases"):
        raw = track.get(key)
        if isinstance(raw, list):
            for item in raw:
                text = _clean_text(item)
                if text:
                    values.add(text)
    return values


def _cache_for_uid(uid: str) -> bool:
    if not isinstance(_current_track, dict):
        return False
    return _clean_text(uid) in _track_all_uids(_current_track)


def is_enabled() -> bool:
    return _enabled


def get_current_track_cache() -> dict | None:
    return dict(_current_track) if isinstance(_current_track, dict) else None


async def get_rpg_track(uid: str) -> dict | None:
    if not is_enabled() or not uid:
        return None
    payload = await _json_request(_rpg_records_url(uid))
    track, rows = _normalize_rpg_records_payload(payload, uid)
    if not track or not rows:
        return None
    return dict(track)


async def get_rpg_records(uid: str, limit: int | None = None) -> list[dict]:
    if not is_enabled() or not uid:
        return []
    payload = await _json_request(_rpg_records_url(uid))
    _track, rows = _normalize_rpg_records_payload(payload, uid)
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]
    return rows


async def get_current_rpg_track(aseco: "Aseco"):
    uid = _track_uid(aseco.server.challenge)
    if _cache_for_uid(uid):
        return dict(_current_track)
    if _lookup_uid != uid:
        await _sync_current_track(aseco)
    return None


async def get_current_rpg_records(aseco: "Aseco", limit: int | None = None) -> list[dict]:
    challenge = getattr(aseco.server, "challenge", None)
    uid = _track_uid(challenge)
    if not uid:
        return []
    if not _cache_for_uid(uid):
        current = await get_current_rpg_track(aseco)
        if not current:
            return []
    rows = list(_current_records)
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]
    return rows


def _clear_current_cache() -> None:
    global _current_track, _current_records
    _current_track = None
    _current_records = []


async def _sync_current_track(aseco: "Aseco"):
    global _lookup_uid
    if not _enabled:
        return
    from pyxaseco.core.background_jobs import JobEnvelope
    uid = _track_uid(aseco.server.challenge)
    if not uid:
        return
    if _lookup_uid != uid:
        _clear_current_cache()
        aseco.server.rpg_records_active = False
    job = JobEnvelope.capture(aseco.capture_job_context(), {'uid': uid})
    revision = _records_revision
    async def operation(envelope):
        requested = envelope.payload()['uid']
        return _normalize_rpg_records_payload(await _json_request(_rpg_records_url(requested)), requested)
    async def apply(result):
        global _current_track, _current_records, _lookup_uid
        if result.status != 'completed':
            logger.warning('[RPGRecords] Lookup unavailable (%s)', result.error_type)
            return
        if revision != _records_revision:
            return
        _current_track, _current_records = result.value
        _lookup_uid = uid
        aseco.server.rpg_records_active = bool(_current_track)
        await aseco.release_event('onRpgRecordsLoaded', uid)
    from pyxaseco.core.background_jobs import JobPolicy
    aseco.jobs.service('rpg_lookup', JobPolicy(deadline_seconds=65)).submit(
        job, operation, apply, dedupe_key=f'current:{revision}')


async def _announce_rpg_record(aseco: "Aseco", nickname: str, score: int, existing_rank: int, existing_score: int, new_rank: int) -> None:
    nickname_text = strip_colors(str(nickname or "?"))
    time_text = format_time(score)
    diff = max(int(existing_score or 0) - int(score or 0), 0)

    if existing_rank <= 0 or new_rank <= 0:
        msg = (
            f'{{#server}}>> {{#highlite}}{nickname_text}{{#dedirec}} claimed the '
            f'{{#rank}}{new_rank}{{#dedirec}}. RPG Record!  '
            f'Time: {{#highlite}}{time_text}'
        )
    elif new_rank < existing_rank:
        msg = (
            f'{{#server}}>> {{#highlite}}{nickname_text}{{#dedirec}} gained the '
            f'{{#rank}}{new_rank}{{#dedirec}}. RPG Record!  '
            f'Time: {{#highlite}}{time_text}{{#dedirec}} '
            f'$n({{#rank}}{existing_rank}{{#highlite}} -{format_time(diff)}{{#dedirec}})'
        )
    else:
        msg = (
            f'{{#server}}>> {{#highlite}}{nickname_text}{{#dedirec}} secured his/her '
            f'{{#rank}}{new_rank}{{#dedirec}}. RPG Record!  '
            f'Time: {{#highlite}}{time_text}{{#dedirec}} '
            f'$n({{#rank}}{new_rank}{{#highlite}} -{format_time(diff)}{{#dedirec}})'
        )

    await aseco.client.query_ignore_result("ChatSendServerMessage", aseco.format_colors(msg))


async def _create_upload_url() -> str:
    payload = await _json_post(f"{_api_base()}{RPG_CREATE_REPLAY_URL_PATH}", None)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected createReplayUrl response shape")
    ok = payload.get("ok")
    if ok is False:
        raise RuntimeError(f"createReplayUrl returned ok=false: {payload}")
    url = _clean_text(payload.get("url"))
    if not url:
        raise RuntimeError(f"createReplayUrl did not return an upload url: {payload}")
    return urllib.parse.urljoin(_api_base() + "/", url)


async def _upload_replay(path: Path) -> int:
    upload_url = await _create_upload_url()
    status = await _put_file(upload_url, path)
    if not isinstance(status, int) or not 200 <= status < 300:
        raise RuntimeError('Unconfirmed RPG replay upload')
    return status


async def _save_best_ghost_replay(aseco: "Aseco", login: str, relative_path: str) -> bool:
    result = await aseco.client.query("SaveBestGhostsReplay", login, relative_path)
    return bool(result)


async def _wait_for_saved_replay(path: Path) -> Path | None:
    from pyxaseco.core.file_io import file_io
    deadline = time.monotonic() + float(RPG_REPLAY_WAIT_SECONDS)
    while time.monotonic() < deadline:
        if await file_io(path.exists):
            try:
                size1 = (await file_io(path.stat)).st_size
            except OSError:
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(float(RPG_REPLAY_STABLE_DELAY_SECONDS))
            try:
                size2 = (await file_io(path.stat)).st_size
            except OSError:
                await asyncio.sleep(0.5)
                continue
            if size1 == size2 and size2 > 0:
                return path
        await asyncio.sleep(0.5)
    return None


def _delete_replay_file(path: Path) -> bool:
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:
        logger.warning("[RPGRecords] Could not delete replay file %s: %s", path, exc)
        return False
    return True


def _merge_record_into_cache(uid: str, login: str, nickname_raw: str, score: int) -> tuple[bool, int, int, int]:
    global _current_track, _current_records, _records_revision
    if not _cache_for_uid(uid):
        return False, 0, 0, 0

    stars = _safe_int((_current_track or {}).get("stars"), 0)
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
                row["nickname"] = nickname_raw or _clean_text(row.get("nickname"))
                row["stars"] = stars
                row["source"] = "tmrpg"
                changed = True
            break

    if not found:
        rows.append({
            "rank": 0,
            "login": login,
            "nickname_raw": nickname_raw or login,
            "nickname": nickname_raw or login,
            "best_score": score,
            "score": score,
            "score_text": format_time(score),
            "challenge_uid": uid,
            "source": "tmrpg",
            "stars": stars,
            "Login": login,
            "NickName": nickname_raw or login,
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
        row["source"] = "tmrpg"
        row["stars"] = stars
        row["score"] = _safe_int(row.get("best_score") or row.get("score"), 0)
        row["best_score"] = row["score"]
        row["score_text"] = format_time(row["score"]) if row["score"] > 0 else "--"
    _current_records = rows
    _records_revision += 1
    if not isinstance(_current_track, dict):
        _current_track = {
            "challenge_uid": uid,
            "uid_primary": uid,
            "uid_values": [uid],
            "uid_aliases": [uid],
            "stars": stars,
            "type": 1,
            "source": "tmrpg",
        }

    new_rank = 0
    for row in rows:
        if _clean_text(row.get("login")).lower() == login.lower():
            new_rank = _safe_int(row.get("rank"), 0)
            break
    return True, existing_rank, existing_score, new_rank


def register(aseco: "Aseco"):
    global _runtime_aseco, _lookup_uid, _records_revision
    _runtime_aseco, _lookup_uid, _records_revision = aseco, '', 0
    _clear_current_cache()
    aseco.register_event("onStartup", _rpg_load_settings)
    aseco.register_event("onNewChallenge", _rpg_sync_current_track)
    aseco.register_event("onRestartChallenge", _rpg_sync_current_track)
    aseco.register_event("onLocalRecord", _rpg_local_record)
    aseco.add_chat_command("rpgrecs", "Displays all RPG Records on current track")
    aseco.register_event("onChat_rpgrecs", chat_rpgrecs)


async def _rpg_load_settings(aseco: "Aseco", _param=None):
    global _enabled
    _enabled = bool(_api_base())
    if _enabled:
        aseco.console("[RPGRecords] Using RPG API '{1}'", _api_base())
        _rpg_delivery(aseco)
    else:
        aseco.console("[RPGRecords] Disabled - configure RPG_API_BASE for app/records_rpg")


async def _rpg_sync_current_track(aseco: "Aseco", _param=None):
    await _sync_current_track(aseco)


async def _rpg_local_record(aseco: "Aseco", new_rec):
    if not _enabled:
        return
    player = getattr(new_rec, 'player', None)
    challenge = getattr(new_rec, 'challenge', None) or aseco.server.challenge
    if not player or not challenge:
        return
    uid, login = _track_uid(challenge), str(player.login)
    score = int(getattr(new_rec, 'score', 0) or 0)
    if not uid or not login or score <= 0 or (_lookup_uid == uid and not _cache_for_uid(uid)):
        return
    if uid != _track_uid(aseco.server.challenge):
        logger.warning('[RPGRecords] Cannot capture an old-map ghost after the map changed')
        return
    from pyxaseco.core.file_io import file_io
    relative = _build_saved_replay_relative_path(challenge, login, score)
    path = _resolve_saved_replay_path(aseco, relative)
    if not path.resolve().is_relative_to(_replays_root(aseco).resolve()):
        raise ValueError('Replay path outside replay root')
    if not await file_io(_replay_storage_available, path.parent):
        logger.error('[RPGRecords] Replay storage admission limit reached; existing retained replays preserved')
        return
    await file_io(path.parent.mkdir, parents=True, exist_ok=True)
    # Capture the ghost before leaving the map. File stability/network work
    # belongs to the worker, not the authoritative finish callback.
    if not await _save_best_ghost_replay(aseco, login, relative):
        logger.warning('[RPGRecords] Replay capture not acknowledged for %s', uid)
        return
    await _rpg_delivery(aseco).retain({
        'uid': uid, 'login': login, 'nickname': str(player.nickname), 'score': score,
        'rank': int(getattr(new_rec, 'pos', 0) or 0), 'relative_path': relative}, map_uid=uid)


def _rpg_delivery(aseco):
    from pyxaseco.core.retained_delivery import delivery, PreparationRejected
    from pyxaseco.core.file_io import file_io
    async def prepare(data):
        path = _resolve_saved_replay_path(aseco, data['relative_path']).resolve()
        if not path.is_relative_to(_replays_root(aseco).resolve()):
            raise PreparationRejected('Replay path outside replay root')
        if not await _wait_for_saved_replay(path):
            raise FileNotFoundError('Retained replay not available yet')
        if not await get_rpg_track(data['uid']):
            raise PreparationRejected('Captured map is not eligible for RPG upload')
        return data
    async def send(data):
        path = _resolve_saved_replay_path(aseco, data['relative_path'])
        return await _upload_replay(path)
    async def apply(data, status, current):
        if current and status is not None:
            if not _cache_for_uid(data['uid']):
                await _sync_current_track(aseco)
                return
            changed, old_rank, old_score, rank = _merge_record_into_cache(
                data['uid'], data['login'], data['nickname'], data['score'])
            if changed:
                await _announce_rpg_record(aseco, data['nickname'], data['score'], old_rank, old_score, rank)
                await aseco.release_event('onRpgRecord', {
                    'challenge_uid': data['uid'], 'login': data['login'],
                    'nickname_raw': data['nickname'], 'score': data['score'], 'rank': rank})
    async def cleanup(data):
        if RPG_DELETE_AFTER_UPLOAD:
            path = _resolve_saved_replay_path(aseco, data['relative_path'])
            if not path.resolve().is_relative_to(_replays_root(aseco).resolve()):
                raise ValueError('Replay path outside replay root')
            await file_io(_delete_replay_file, path)
    return delivery(aseco, 'rpg_records', send, apply, prepare=prepare, cleanup=cleanup)


async def _send_chat(aseco: "Aseco", login: str, message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin", aseco.format_colors(message), login
    )


async def chat_rpgrecs(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login
    challenge = getattr(aseco.server, "challenge", None)
    uid = _track_uid(challenge)
    if not uid:
        await _send_chat(aseco, login, "{#server}> {#error}No current challenge UID available.")
        return

    if not _enabled:
        await _send_chat(aseco, login, '{#server}> {#error}RPG records are disabled.')
        return
    from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
    job = JobEnvelope.capture(aseco.capture_job_context(), {'uid': uid})
    async def operation(envelope):
        requested = envelope.payload()['uid']
        return _normalize_rpg_records_payload(await _json_request(_rpg_records_url(requested)), requested)
    async def apply(result):
        if aseco.server.players.get_player(login) is not player:
            return
        if result.status != 'completed':
            await _send_chat(aseco, login, '{#server}> {#error}RPG records unavailable; please try again later.')
            return
        current, rows = result.value
        await _show_rpgrecs(aseco, player, current, rows)
    outcome = aseco.jobs.service('rpg_lookup', JobPolicy(deadline_seconds=65)).submit(
        job, operation, apply, dedupe_key=f'command:{id(player)}')
    if outcome == Admission.ACCEPTED:
        await _send_chat(aseco, login, '{#server}> Loading fresh RPG records...')
    elif outcome != Admission.DUPLICATE:
        await _send_chat(aseco, login, '{#server}> {#error}RPG records busy; please try again shortly.')


async def _show_rpgrecs(aseco, player, current, rows):
    login = player.login
    if not current or not rows:
        await _send_chat(aseco, login, "{#server}> {#error}Current track has no RPG records.")
        return

    show_logins = True
    extra = 0.2 if getattr(aseco.settings, "lists_colornicks", False) else 0
    table_rows = []
    for idx, row in enumerate(rows, start=1):
        rec_login = _clean_text(row.get("login")) or "?"
        nick = _pick_display_name(
            row.get("nickname_raw"),
            row.get("player_nickname_raw"),
            row.get("nickname"),
            row.get("player_nickname"),
            row.get("NickName"),
            rec_login,
        )
        score = str(row.get("score_text") or "--")
        if show_logins:
            table_rows.append([f"{idx:02d}.", "{#black}" + nick, "{#login}" + rec_login, score])
        else:
            table_rows.append([f"{idx:02d}.", "{#black}" + nick, score])

    maxrank = max(len(rows), 1)
    if show_logins:
        widths = [1.2 + extra, 0.1, 0.45 + extra, 0.4, 0.25]
    else:
        widths = [0.8 + extra, 0.1, 0.45 + extra, 0.25]
    pages = [table_rows[i:i + 15] for i in range(0, len(table_rows), 15)]
    player.msgs = [[1, f"Current TOP {maxrank} RPG Records:", widths, ["BgRaceScore2", "Podium"]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)
