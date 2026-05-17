"""
plugin_records_rpg.py

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
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink_multi, format_time, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


PLUGIN_VERSION = "1.0.0"

RPG_API_BASE = "https://www.tmrpg.com"
RPG_API_TOKEN = ""
RPG_RECORDS_PATH_TMPL = "/api/pyxaseco/maps/{uid}/records"
RPG_CREATE_REPLAY_URL_PATH = "/createReplayUrl"

RPG_REPLAY_WAIT_SECONDS = 20.0
RPG_REPLAY_STABLE_DELAY_SECONDS = 0.35
RPG_SAVE_SUBDIR = "PyXasecoRPG"
RPG_DELETE_AFTER_UPLOAD = True


_enabled: bool = False
_current_track: dict | None = None
_current_records: list[dict] = []
_last_status_key: tuple[str, bool, int, int] | None = None


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
    track_uid = _track_uid(challenge) or "unknown_uid"
    safe_login = _safe_path_component(login)
    safe_uid = _safe_path_component(track_uid)
    filename = f"{safe_uid}__{safe_login}__{int(score)}.Replay.Gbx"
    return str(Path(RPG_SAVE_SUBDIR) / filename).replace("\\", "/")


def _resolve_saved_replay_path(aseco: "Aseco", relative_path: str) -> Path:
    rel = str(relative_path or "").replace("/", os.sep).replace("\\", os.sep).strip("\\/")
    return _replays_root(aseco) / Path(rel)


def _rpg_records_url(uid: str) -> str:
    path = RPG_RECORDS_PATH_TMPL.format(uid=urllib.parse.quote(str(uid).strip(), safe=""))
    return f"{_api_base()}{path}"


def _json_request_sync(url: str) -> object | None:
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


def _json_post_sync(url: str, payload: dict | None = None) -> object:
    headers = _build_headers()
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    if payload is not None:
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


def _put_file_sync(url: str, path: Path) -> int:
    headers = {
        "Content-Type": "application/octet-stream",
        "User-Agent": f"PyXaseco-RPGRecords/{PLUGIN_VERSION}",
    }
    with path.open("rb") as fh:
        data = fh.read()
    req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(getattr(resp, "status", 200) or 200)


async def _json_request(url: str) -> object | None:
    return await asyncio.to_thread(_json_request_sync, url)


async def _json_post(url: str, payload: dict | None = None) -> object:
    return await asyncio.to_thread(_json_post_sync, url, payload)


async def _put_file(url: str, path: Path) -> int:
    return await asyncio.to_thread(_put_file_sync, url, path)


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
    if not isinstance(payload, dict):
        return None, []
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return None, []

    challenge_uid = _clean_text(payload.get("challenge_uid") or requested_uid)
    stars = _safe_int(payload.get("stars"), 0)
    rtype = _safe_int(payload.get("type"), 0)

    rows: list[dict] = []
    for idx, rec in enumerate(raw_records, start=1):
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


async def get_current_rpg_track(aseco: "Aseco") -> dict | None:
    challenge = getattr(aseco.server, "challenge", None)
    uid = _track_uid(challenge)
    if not uid:
        _clear_current_cache()
        return None
    if _cache_for_uid(uid):
        return dict(_current_track)
    await _sync_current_track(aseco)
    return dict(_current_track) if _cache_for_uid(uid) else None


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


def _announce_track_status(aseco: "Aseco", uid: str, active: bool, *, stars: int = 0, count: int = 0) -> None:
    global _last_status_key
    key = (_clean_text(uid), bool(active), int(stars or 0), int(count or 0))
    if _last_status_key == key:
        return
    _last_status_key = key
    if not active:
        aseco.console("[RPGRecords] Inactive on {1}; fallback to Dedimania", uid)
        return
    aseco.console("[RPGRecords] Active on {1} (stars={2})", uid, stars)
    aseco.console("[RPGRecords] Fetched {1} RPG records for {2}", count, uid)


async def _sync_current_track(aseco: "Aseco") -> None:
    global _current_track, _current_records
    if not _enabled:
        _clear_current_cache()
        try:
            aseco.server.rpg_records_active = False
        except Exception:
            pass
        return

    challenge = getattr(aseco.server, "challenge", None)
    uid = _track_uid(challenge)
    if not uid:
        _clear_current_cache()
        try:
            aseco.server.rpg_records_active = False
        except Exception:
            pass
        return

    try:
        payload = await _json_request(_rpg_records_url(uid))
    except Exception as exc:
        _clear_current_cache()
        try:
            aseco.server.rpg_records_active = False
        except Exception:
            pass
        logger.warning("[RPGRecords] Record fetch failed for %s: %s", uid, exc)
        _announce_track_status(aseco, uid, False)
        return

    track, rows = _normalize_rpg_records_payload(payload, uid)
    if not track or not rows:
        _clear_current_cache()
        try:
            aseco.server.rpg_records_active = False
        except Exception:
            pass
        _announce_track_status(aseco, uid, False)
        return

    _current_track = dict(track)
    _current_records = list(rows)
    try:
        aseco.server.rpg_records_active = True
    except Exception:
        pass
    _announce_track_status(
        aseco,
        _storage_uid(_current_track) or uid,
        True,
        stars=_safe_int(_current_track.get("stars"), 0),
        count=len(_current_records),
    )


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
    return await _put_file(upload_url, path)


async def _save_best_ghost_replay(aseco: "Aseco", login: str, relative_path: str) -> bool:
    result = await aseco.client.query("SaveBestGhostsReplay", login, relative_path)
    return bool(result)


async def _wait_for_saved_replay(path: Path) -> Path | None:
    deadline = time.monotonic() + float(RPG_REPLAY_WAIT_SECONDS)
    while time.monotonic() < deadline:
        if path.exists():
            try:
                size1 = path.stat().st_size
            except OSError:
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(float(RPG_REPLAY_STABLE_DELAY_SECONDS))
            try:
                size2 = path.stat().st_size
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


def _prepare_save_target(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return
    try:
        path.unlink()
    except Exception as exc:
        logger.warning("[RPGRecords] Could not remove stale replay target %s before save: %s", path, exc)


def _merge_record_into_cache(uid: str, login: str, nickname_raw: str, score: int) -> tuple[bool, int, int, int]:
    global _current_track, _current_records
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
    aseco.register_event("onStartup", _rpg_load_settings)
    aseco.register_event("onSync", _rpg_sync_current_track)
    aseco.register_event("onNewChallenge", _rpg_sync_current_track)
    aseco.register_event("onLocalRecord", _rpg_local_record)
    aseco.add_chat_command("rpgrecs", "Displays all RPG Records on current track")
    aseco.register_event("onChat_rpgrecs", chat_rpgrecs)


async def _rpg_load_settings(aseco: "Aseco", _param=None):
    global _enabled
    _enabled = bool(_api_base())
    if _enabled:
        aseco.console("[RPGRecords] Using RPG API '{1}'", _api_base())
    else:
        aseco.console("[RPGRecords] Disabled - configure RPG_API_BASE in plugin_records_rpg.py")


async def _rpg_sync_current_track(aseco: "Aseco", _param=None):
    await _sync_current_track(aseco)


async def _rpg_local_record(aseco: "Aseco", new_rec):
    if not _enabled:
        return
    player = getattr(new_rec, "player", None)
    challenge = getattr(new_rec, "challenge", None) or getattr(getattr(aseco, "server", None), "challenge", None)
    if not player or not challenge:
        return

    login = _clean_text(getattr(player, "login", ""))
    nickname_raw = _clean_text(getattr(player, "nickname", "") or login)
    challenge_uid = _track_uid(challenge)
    if not login or not challenge_uid:
        return
    if not _cache_for_uid(challenge_uid):
        aseco.console("[RPGRecords] Skipping replay upload for inactive challenge {1}", challenge_uid)
        return

    score = _safe_int(getattr(new_rec, "score", 0), 0)
    if score <= 0:
        return
    rank = _safe_int(getattr(new_rec, "pos", 0), 0)
    map_name = _clean_text(getattr(challenge, "name", "") or challenge_uid)

    relative_path = _build_saved_replay_relative_path(challenge, login, score)
    replay_path = _resolve_saved_replay_path(aseco, relative_path)
    _prepare_save_target(replay_path)

    try:
        saved = await _save_best_ghost_replay(aseco, login, relative_path)
    except Exception as exc:
        logger.warning(
            "[RPGRecords] SaveBestGhostsReplay failed for %s on %s (%s): %s",
            login,
            challenge_uid,
            relative_path,
            exc,
        )
        return
    if not saved:
        logger.warning(
            "[RPGRecords] SaveBestGhostsReplay returned false for %s on %s (%s)",
            login,
            challenge_uid,
            relative_path,
        )
        return

    replay_path = await _wait_for_saved_replay(replay_path)
    if replay_path is None:
        logger.warning(
            "[RPGRecords] Saved replay file missing for %s on %s at %s",
            login,
            challenge_uid,
            _resolve_saved_replay_path(aseco, relative_path),
        )
        return

    try:
        status = await _upload_replay(replay_path)
    except Exception as exc:
        logger.warning(
            "[RPGRecords] Upload failed for %s on %s from %s: %s",
            login,
            challenge_uid,
            replay_path,
            exc,
        )
        return

    if 200 <= int(status) < 300:
        cleanup_ok = True
        if RPG_DELETE_AFTER_UPLOAD:
            cleanup_ok = await asyncio.to_thread(_delete_replay_file, replay_path)

        changed, existing_rank, existing_score, new_rank = _merge_record_into_cache(challenge_uid, login, nickname_raw, score)
        if changed:
            await _announce_rpg_record(
                aseco,
                nickname_raw,
                score,
                existing_rank,
                existing_score,
                new_rank,
            )
            await aseco.release_event("onRpgRecord", {
                "challenge_uid": challenge_uid,
                "login": login,
                "nickname_raw": nickname_raw,
                "score": score,
                "rank": new_rank or rank,
            })

        aseco.console(
            "[RPGRecords] Uploaded replay for {1} rank={2} score={3} map='{4}'",
            login,
            rank or "?",
            score,
            map_name,
        )
        if RPG_DELETE_AFTER_UPLOAD:
            if cleanup_ok:
                aseco.console("[RPGRecords] Deleted local replay {1}", str(replay_path))
            else:
                logger.warning("[RPGRecords] Replay uploaded but local cleanup failed: %s", replay_path)
    else:
        logger.warning(
            "[RPGRecords] Upload returned unexpected status %s for %s on %s; keeping replay file %s",
            status,
            login,
            challenge_uid,
            replay_path,
        )


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

    current = None
    rows: list[dict] = []
    cached = get_current_track_cache()
    if isinstance(cached, dict) and uid in _track_all_uids(cached):
        current = cached
    try:
        fetched = await get_rpg_track(uid)
        if isinstance(fetched, dict):
            current = fetched
    except Exception as exc:
        logger.warning("[RPGRecords] /rpgrecs track fetch failed for %s: %s", uid, exc)
    try:
        rows = await get_rpg_records(uid)
    except Exception as exc:
        logger.warning("[RPGRecords] /rpgrecs record fetch failed for %s: %s", uid, exc)
    if isinstance(current, dict):
        global _current_track, _current_records
        _current_track = dict(current)
        if rows:
            _current_records = list(rows)

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
