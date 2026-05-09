from __future__ import annotations

"""
plugin_public_stats.py

Lightweight public stats bridge for remote PyXaseco servers.

Design goals:
- no direct database access
- no .env dependency
- small API-only snapshot/event plugin
- safe for remote servers outside the main VPS

It reports:
- server heartbeat / current snapshot
- current map
- player/spectator counts
- controller + plugin version
- last 5 local-record events
"""

import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pyxaseco.core.aseco import PYXASECO_VERSION
from pyxaseco.helpers import strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


logger = logging.getLogger(__name__)


PLUGIN_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Public Stats API configuration
# ---------------------------------------------------------------------------

PUBLIC_STATS_API_BASE = "https://tmtrialgy.com"
PUBLIC_STATS_API_TOKEN = ""
PUBLIC_STATS_HEARTBEAT_PATH = "/api/public-stats/heartbeat"
PUBLIC_STATS_RECENT_RECORD_PATH = "/api/public-stats/recent-record"

PUBLIC_STATS_HEARTBEAT_SECONDS = 60
PUBLIC_STATS_RECENT_KEEP = 5
PUBLIC_STATS_REQUEST_TIMEOUT = 20


_enabled: bool = False
_recent_local_records: list[dict] = []
_last_heartbeat_sent: float = 0.0


def _api_base() -> str:
    return str(PUBLIC_STATS_API_BASE or "").rstrip("/")


def _api_token() -> str:
    return str(PUBLIC_STATS_API_TOKEN or "").strip()


def _build_headers() -> dict[str, str]:
    headers = {
        "User-Agent": f"PyXaseco-PublicStats/{PLUGIN_VERSION}",
        "Accept": "application/json, */*",
    }
    token = _api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Public-Stats-Token"] = token
    return headers


def _json_post_sync(url: str, payload: dict) -> object:
    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers()
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=PUBLIC_STATS_REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
            return json.loads(raw) if raw else {}
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
    raise last_error or RuntimeError(f"Could not POST JSON to {url}")


async def _json_post(url: str, payload: dict) -> object:
    return await asyncio.to_thread(_json_post_sync, url, payload)


def _is_enabled() -> bool:
    return _enabled and bool(_api_base())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _display_and_raw(value: object) -> tuple[str, str]:
    raw = _clean_text(value)
    clean = strip_colors(raw) if raw else ""
    return clean, raw


def _server_country(aseco: "Aseco") -> str:
    srv = getattr(aseco, "server", None)
    nation = _clean_text(getattr(srv, "nation", ""))
    zone = _clean_text(getattr(srv, "zone", ""))
    if zone.startswith("World|"):
        zone = zone[6:]
    if "|" in zone:
        return _clean_text(zone.split("|", 1)[0])
    if zone:
        return zone
    if nation:
        return nation
    return "World"


def _is_spectator(player) -> bool:
    raw = getattr(player, "spectatorstatus", None)
    try:
        if raw is not None:
            return (int(raw) % 10) != 0
    except Exception:
        pass
    return bool(getattr(player, "isspectator", False))


def _player_counts(aseco: "Aseco") -> dict[str, int]:
    srv = getattr(aseco, "server", None)
    server_login = _clean_text(getattr(srv, "serverlogin", ""))
    players = list(getattr(getattr(srv, "players", None), "all", lambda: [])() or [])
    filtered = [p for p in players if _clean_text(getattr(p, "login", "")) and _clean_text(getattr(p, "login", "")).lower() != server_login.lower()]
    spec_count = sum(1 for p in filtered if _is_spectator(p))
    player_count = sum(1 for p in filtered if not _is_spectator(p))
    return {
        "current": player_count,
        "spectators": spec_count,
        "total": len(filtered),
        "max_players": int(getattr(srv, "maxplay", 0) or 0),
        "max_spectators": int(getattr(srv, "maxspec", 0) or 0),
    }


def _current_map_payload(aseco: "Aseco") -> dict:
    challenge = getattr(getattr(aseco, "server", None), "challenge", None)
    name, name_raw = _display_and_raw(getattr(challenge, "name", ""))
    author = _clean_text(getattr(challenge, "author", ""))
    uid = _clean_text(getattr(challenge, "uid", ""))
    environment = _clean_text(getattr(challenge, "environment", ""))
    return {
        "uid": uid,
        "name": name,
        "name_raw": name_raw,
        "author": author,
        "environment": environment,
    }


def _heartbeat_payload(aseco: "Aseco", *, is_online: bool = True) -> dict:
    srv = getattr(aseco, "server", None)
    server_name, server_name_raw = _display_and_raw(getattr(srv, "name", ""))
    return {
        "schema_version": 1,
        "reported_at": _utc_now_iso(),
        "is_online": bool(is_online),
        "server_login": _clean_text(getattr(srv, "serverlogin", "")),
        "server_name": server_name,
        "server_name_raw": server_name_raw,
        "country": _server_country(aseco),
        "game": _clean_text(getattr(srv, "game", "")),
        "controller_version": f"PyXaseco {PYXASECO_VERSION}",
        "plugin_version": PLUGIN_VERSION,
        "current_map": _current_map_payload(aseco),
        "players": _player_counts(aseco),
        "uptime_seconds": int(max(time.time() - float(getattr(srv, "starttime", time.time()) or time.time()), 0)),
        "recent_local_records": list(_recent_local_records[:PUBLIC_STATS_RECENT_KEEP]),
    }


def _recent_record_payload(aseco: "Aseco", rec) -> dict:
    challenge = getattr(getattr(aseco, "server", None), "challenge", None)
    player = getattr(rec, "player", None)
    nickname, nickname_raw = _display_and_raw(getattr(player, "nickname", ""))
    map_name, map_name_raw = _display_and_raw(getattr(challenge, "name", ""))
    return {
        "schema_version": 1,
        "reported_at": _utc_now_iso(),
        "server_login": _clean_text(getattr(getattr(aseco, "server", None), "serverlogin", "")),
        "map_uid": _clean_text(getattr(challenge, "uid", "")),
        "map_name": map_name,
        "map_name_raw": map_name_raw,
        "player_login": _clean_text(getattr(player, "login", "")),
        "player_nickname": nickname,
        "player_nickname_raw": nickname_raw,
        "time_ms": int(getattr(rec, "score", 0) or 0),
        "rank": int(getattr(rec, "pos", 0) or 0),
        "source": "local",
    }


def _remember_recent_record(payload: dict):
    global _recent_local_records
    entry = dict(payload)
    _recent_local_records.insert(0, entry)
    _recent_local_records = _recent_local_records[:PUBLIC_STATS_RECENT_KEEP]


async def _post_heartbeat(aseco: "Aseco", *, force: bool = False, is_online: bool = True):
    global _last_heartbeat_sent
    if not _is_enabled():
        return
    now = time.time()
    if not force and (now - _last_heartbeat_sent) < float(PUBLIC_STATS_HEARTBEAT_SECONDS):
        return
    payload = _heartbeat_payload(aseco, is_online=is_online)
    try:
        await _json_post(f"{_api_base()}{PUBLIC_STATS_HEARTBEAT_PATH}", payload)
        _last_heartbeat_sent = now
    except Exception as exc:
        logger.warning("[PublicStats] Heartbeat failed: %s", exc)


async def _post_recent_record(aseco: "Aseco", rec):
    if not _is_enabled():
        return
    payload = _recent_record_payload(aseco, rec)
    _remember_recent_record(payload)
    try:
        await _json_post(f"{_api_base()}{PUBLIC_STATS_RECENT_RECORD_PATH}", payload)
    except Exception as exc:
        logger.warning("[PublicStats] Recent-record POST failed: %s", exc)


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", public_stats_startup)
    aseco.register_event("onSync", public_stats_sync)
    aseco.register_event("onNewChallenge", public_stats_new_challenge)
    aseco.register_event("onPlayerConnect", public_stats_player_connect)
    aseco.register_event("onPlayerDisconnect", public_stats_player_disconnect)
    aseco.register_event("onPlayerInfoChanged", public_stats_player_info_changed)
    aseco.register_event("onLocalRecord", public_stats_local_record)
    aseco.register_event("onShutdown", public_stats_shutdown)


async def public_stats_startup(aseco: "Aseco", _param=None):
    global _enabled
    _enabled = bool(_api_base())
    if not _enabled:
        logger.info("[PublicStats] Disabled (PUBLIC_STATS_API_BASE is empty)")
        return
    logger.info("[PublicStats] Using API '%s'", _api_base())
    try:
        versions = getattr(aseco, "plugin_versions", None)
        if isinstance(versions, list):
            versions.append({"name": "plugin_public_stats", "version": PLUGIN_VERSION})
    except Exception:
        pass
    await _post_heartbeat(aseco, force=True, is_online=True)


async def public_stats_sync(aseco: "Aseco", _param=None):
    await _post_heartbeat(aseco, force=False, is_online=True)


async def public_stats_new_challenge(aseco: "Aseco", _param=None):
    await _post_heartbeat(aseco, force=True, is_online=True)


async def public_stats_player_connect(aseco: "Aseco", _player):
    await _post_heartbeat(aseco, force=False, is_online=True)


async def public_stats_player_disconnect(aseco: "Aseco", _player):
    await _post_heartbeat(aseco, force=False, is_online=True)


async def public_stats_player_info_changed(aseco: "Aseco", _info):
    await _post_heartbeat(aseco, force=False, is_online=True)


async def public_stats_local_record(aseco: "Aseco", rec):
    await _post_recent_record(aseco, rec)
    await _post_heartbeat(aseco, force=True, is_online=True)


async def public_stats_shutdown(aseco: "Aseco", _param=None):
    await _post_heartbeat(aseco, force=True, is_online=False)
