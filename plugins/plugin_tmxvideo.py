"""
plugin_tmxvideo.py - Port of chat.tmxvideo.php

Commands:
  /gps [help|latest|oldest|list]

Fetches TMX video links for the current track and shows them either in chat
or in a multi-page ManiaLink window.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pyxaseco.helpers import display_manialink, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

PLUGIN_VERSION = "1.0.0"
TMX_VIDEO_HOSTS_BY_PREFIX = {
    "tmnforever": "tmnf.exchange",
    "united": "tmuf.exchange",
    "nations": "nations.tm-exchange.com",
    "original": "original.tm-exchange.com",
    "sunrise": "sunrise.tm-exchange.com",
}

_current_uid: str = ""
_current_tmx_id: int = 0
_current_tmx_prefix: str = ""
_videos: list[dict] = []
_load_lock = asyncio.Lock()


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", tmxvideo_startup)
    aseco.register_event("onNewChallenge2", tmxvideo_new_challenge)
    aseco.add_chat_command("gps", "Shows TMX GPS/videos for the current track")
    aseco.register_event("onChat_gps", chat_gps)


def _msg_console(aseco: "Aseco", text: str):
    aseco.console(f"[plugin_tmxvideo] {text}")


async def _msg_player(aseco: "Aseco", login: str, text: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors("{#server}> " + text),
        login,
    )


def _escape_title(title: str) -> str:
    return str(title or "").replace("$", "$$")


def _video_url(video_id: str) -> str:
    return f"http://youtu.be/{str(video_id or '').strip()}"


def _published_sort_key(item: dict) -> float:
    raw = str(item.get("PublishedAt") or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw).timestamp()
    except Exception:
        return 0.0


def _published_label(item: dict) -> str:
    raw = str(item.get("PublishedAt") or "").strip()
    if not raw:
        return "-"
    return raw.split("T", 1)[0]


def _current_challenge(aseco: "Aseco"):
    return getattr(getattr(aseco, "server", None), "challenge", None)


def _host_from_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    return str(parsed.netloc or "").strip()


async def _resolve_current_tmx_ref(aseco: "Aseco", challenge=None) -> tuple[int, str]:
    ch = challenge if challenge is not None else _current_challenge(aseco)
    if ch is None:
        return 0, ""

    section = ""
    try:
        from pyxaseco.plugins.plugin_tmxinfo import get_tmx_section

        section = await get_tmx_section(aseco)
    except Exception:
        section = ""

    prefix = str(getattr(ch, "tmx_prefix", "") or "").strip()

    try:
        direct = int(getattr(ch, "tmx_id", 0) or 0)
    except Exception:
        direct = 0
    if direct > 0:
        if prefix:
            return direct, prefix
        try:
            from pyxaseco.plugins.plugin_tmxinfo import tmx_prefix_for_section

            return direct, tmx_prefix_for_section(section)
        except Exception:
            return direct, ""

    tmx_obj = getattr(ch, "tmx", None)
    if prefix == "":
        prefix = str(getattr(tmx_obj, "prefix", "") or "").strip()
    try:
        nested = int(getattr(tmx_obj, "id", 0) or 0)
    except Exception:
        nested = 0
    if nested > 0:
        if prefix:
            return nested, prefix
        page_host = _host_from_url(getattr(tmx_obj, "pageurl", "") or "")
        try:
            from pyxaseco.plugins.plugin_tmxinfo import TMX_HOST_ALIASES, tmx_prefix_for_section

            for site, host in TMX_HOST_ALIASES.items():
                if page_host.lower() == str(host).lower():
                    return nested, tmx_prefix_for_section(site)
            return nested, tmx_prefix_for_section(section)
        except Exception:
            return nested, ""

    uid = str(getattr(ch, "uid", "") or "").strip()
    if not uid:
        return 0, ""

    try:
        from pyxaseco.plugins.plugin_tmxinfo import resolve_tmx_track_id

        track_id, prefix = await resolve_tmx_track_id(uid, section)
        if track_id:
            try:
                ch.tmx_id = int(track_id)
                if prefix:
                    ch.tmx_prefix = prefix
            except Exception:
                pass
            return int(track_id), str(prefix or "")
    except Exception as exc:
        logger.debug("[TMXVideo] Could not resolve TMX track id for uid=%s: %s", uid, exc)

    return 0, ""


async def _fetch_json(url: str):
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.debug("[TMXVideo] HTTP %s for %s", resp.status, url)
                    return None
                return await resp.json(content_type=None)
    except Exception as exc:
        logger.debug("[TMXVideo] Request failed for %s: %s", url, exc)
        return None


async def _load_videos_for_track(aseco: "Aseco", uid: str, tmx_id: int, prefix: str):
    global _videos
    _msg_console(aseco, f"Requesting videos for track with TMX ID {tmx_id}")
    host = await _resolve_video_host(aseco, prefix)

    url = f"https://{host}/api/videos?fields=LinkId%2CTitle%2CPublishedAt&trackid={int(tmx_id)}"
    _msg_console(aseco, f"Requesting {url}")

    data = await _fetch_json(url)
    results = data.get("Results") if isinstance(data, dict) else None
    if isinstance(results, list):
        _videos = [dict(item) for item in results if isinstance(item, dict) and str(item.get("LinkId") or "").strip()]
        _videos.sort(key=_published_sort_key, reverse=True)
    else:
        _videos = []

    _msg_console(aseco, f"Found {len(_videos)} videos for track with TMX ID {tmx_id}")


async def _resolve_server_section(aseco: "Aseco") -> str:
    try:
        from pyxaseco.plugins.plugin_tmxinfo import get_tmx_section

        return await get_tmx_section(aseco)
    except Exception:
        try:
            game = aseco.server.get_game()
        except Exception:
            game = str(getattr(aseco.server, "game", "") or "").upper()

        if game == "TMF":
            packmask = str(getattr(aseco.server, "packmask", "") or "")
            return "TMNF" if packmask == "Stadium" else "TMU"

        return game or "TMNF"


async def _resolve_video_host(aseco: "Aseco", prefix: str) -> str:
    pref = str(prefix or "").strip().lower()
    if pref in TMX_VIDEO_HOSTS_BY_PREFIX:
        return TMX_VIDEO_HOSTS_BY_PREFIX[pref]

    try:
        from pyxaseco.plugins.plugin_tmxinfo import tmx_public_host_for_section

        return tmx_public_host_for_section(await _resolve_server_section(aseco))
    except Exception:
        section = (await _resolve_server_section(aseco)).upper()
        if section == "TMU":
            return "tmuf.exchange"
        if section == "TMN":
            return "nations.tm-exchange.com"
        if section == "TMO":
            return "original.tm-exchange.com"
        if section == "TMS":
            return "sunrise.tm-exchange.com"
        return "tmnf.exchange"


async def _ensure_current_videos(aseco: "Aseco", challenge=None, *, force: bool = False):
    global _current_uid, _current_tmx_id, _current_tmx_prefix, _videos
    ch = challenge if challenge is not None else _current_challenge(aseco)
    if ch is None:
        _current_uid = ""
        _current_tmx_id = 0
        _current_tmx_prefix = ""
        _videos = []
        return

    uid = str(getattr(ch, "uid", "") or "").strip()
    if not uid:
        _current_uid = ""
        _current_tmx_id = 0
        _current_tmx_prefix = ""
        _videos = []
        return

    async with _load_lock:
        if not force and uid == _current_uid:
            return

        _current_uid = uid
        _videos = []
        _current_tmx_id, _current_tmx_prefix = await _resolve_current_tmx_ref(aseco, ch)
        if _current_tmx_id <= 0:
            _msg_console(aseco, f"No TMX ID available for track uid {uid}")
            return

        await _load_videos_for_track(aseco, uid, _current_tmx_id, _current_tmx_prefix)


def _has_videos() -> bool:
    return bool(_videos)


async def _show_help(aseco: "Aseco", login: str):
    header = "{#black}/gps <option>$g shows TMX GPS/videos for the current track:"
    help_data = [
        ["...", "{#black}help", "Shows this help window"],
        ["...", "{#black}latest", "Gives the latest video in chat"],
        ["...", "{#black}oldest", "Gives the oldest video in chat"],
        ["...", "{#black}list", "Displays all videos in a window"],
    ]
    display_manialink(
        aseco,
        login,
        header,
        ["Icons64x64_1", "TrackInfo", -0.01],
        help_data,
        [1.1, 0.05, 0.3, 0.75],
        "OK",
    )


async def _send_video_in_chat(aseco: "Aseco", login: str, video: dict):
    link_id = str(video.get("LinkId") or "").strip()
    title = _escape_title(str(video.get("Title") or "").strip() or link_id)
    await _msg_player(
        aseco,
        login,
        f"Watch $l[{_video_url(link_id)}]{title}$l{{#server}} on YouTube.",
    )


async def _show_videos_window(aseco: "Aseco", player):
    challenge = _current_challenge(aseco)
    header = f"Videos for {getattr(challenge, 'name', '') or 'current track'}"

    rows: list[list[str]] = []
    for item in _videos:
        link_id = str(item.get("LinkId") or "").strip()
        title = _escape_title(str(item.get("Title") or "").strip() or link_id)
        rows.append(
            [
                "{#black}" + _published_label(item),
                f"$l[{_video_url(link_id)}]{{#black}}{title}$l",
            ]
        )

    pages = [rows[i:i + 15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, header, [1.35, 0.25, 1.10], ["Icons64x64_1", "TrackInfo"]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def tmxvideo_startup(aseco: "Aseco", _param=None):
    _msg_console(aseco, "Plugin TMX Video initialized.")
    try:
        versions = getattr(aseco, "plugin_versions", None)
        if isinstance(versions, list):
            versions.append({"name": "plugin_tmxvideo", "version": PLUGIN_VERSION})
    except Exception:
        pass


async def tmxvideo_new_challenge(aseco: "Aseco", challenge):
    await _ensure_current_videos(aseco, challenge, force=True)


async def chat_gps(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login
    params = [part for part in str(command.get("params") or "").strip().split() if part]
    subcmd = params[0].lower() if params else ""

    if subcmd == "help":
        await _show_help(aseco, login)
        return

    await _ensure_current_videos(aseco)
    if not _has_videos():
        await _msg_player(aseco, login, "{#error}No videos found for this track.")
        return

    if subcmd == "list":
        await _show_videos_window(aseco, player)
        return
    if subcmd in ("", "latest"):
        await _send_video_in_chat(aseco, login, _videos[0])
        return
    if subcmd == "oldest":
        await _send_video_in_chat(aseco, login, _videos[-1])
        return

    await _msg_player(aseco, login, "{#error}Unknown command, use /gps help for more information.")
