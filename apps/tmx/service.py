"""
TMX service backend for metadata lookup, world record display, and TMX chat flows.

Fetches TMX track info via HTTP and displays it. Shows TMX world record
at track start. /tmxinfo and /tmxrecs commands.

TMX HTTP calls are made with aiohttp.
"""

from __future__ import annotations

import asyncio
from hashlib import sha256
import html
import logging
import re
import sys
import urllib.parse
from aiohttp import ClientError
from typing import TYPE_CHECKING

from pyxaseco.helpers import clean_tm_text, format_text, format_time, display_manialink, validate_utf8
from pyxaseco.models import Gameinfo
from pyxaseco.core.bounded_cache import BoundedCache
from pyxaseco.core.external_io import request_json
from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

PLUGIN_METADATA = {
    'display_name': 'TMX Service',
    'description': 'Provides TMX site resolution, metadata lookups, and public TMX helpers.',
    'provides': ['service/tmx', 'tmx'],
}


def _decode_tmx_legacy_text(value: object) -> str:
    text = html.unescape(str(value or '')).strip()
    if not text:
        return ''

    decoded = text
    if re.search(r'%[0-9A-Fa-f]{2}', decoded):
        decoded = urllib.parse.unquote_plus(decoded)
        if re.search(r'%[0-9A-Fa-f]{2}', decoded):
            decoded = urllib.parse.unquote(decoded)

    return clean_tm_text(html.unescape(decoded).strip(), keep_colors=True)


def _literal_ml_text(value):
    """Prefix plain labels so TMF renders them literally instead of localizing them."""
    if not isinstance(value, str):
        return value
    if value.startswith('$') or value.startswith('{#'):
        return value
    return '$z' + value


def _literal_ml_link(url: str, label: str) -> str:
    """Build a TMF-safe literal clickable label."""
    return f'$z$l[{url}]{label}$l'


async def _display_manialink_track(
    aseco: "Aseco",
    login: str,
    header: str,
    icon: list,
    links: list,
    data: list,
    widths: list,
    button: str,
):

    import html

    player = aseco.server.players.get_player(login)
    if not player:
        return

    style = player.style if player.style else {}
    square = bool(links[1]) if len(links) > 1 else False

    if not style:
        display_manialink(aseco, login, header, icon, data, widths, button)
        return

    def esc(value) -> str:
        return html.escape(validate_utf8(str(value or "")))

    hsize = float(style['HEADER'][0]['TEXTSIZE'][0])
    bsize = float(style['BODY'][0]['TEXTSIZE'][0])
    lines = len(data)
    w0 = float(widths[0])

    xml = (
        f'<manialink id="1"><frame pos="{w0/2} 0.47 0">'
        f'<quad size="{w0} {0.42 + (0.1 if square else 0.0) + 2*hsize + lines*bsize}" '
        f'style="{style["WINDOW"][0]["STYLE"][0]}" '
        f'substyle="{style["WINDOW"][0]["SUBSTYLE"][0]}"/>'
    )

    xml += (
        f'<quad pos="-{w0/2} -0.01 -0.1" size="{w0-0.02} {hsize}" halign="center" '
        f'style="{style["HEADER"][0]["STYLE"][0]}" '
        f'substyle="{style["HEADER"][0]["SUBSTYLE"][0]}"/>'
    )

    if isinstance(icon, list):
        isize = hsize + (float(icon[2]) if len(icon) > 2 else 0.0)
        xml += (
            f'<quad pos="-0.055 -0.045 -0.2" size="{isize} {isize}" '
            f'halign="center" valign="center" style="{icon[0]}" substyle="{icon[1]}"/>'
            f'<label pos="-0.10 -0.025 -0.2" size="{w0-0.12} {hsize}" halign="left" '
            f'style="{style["HEADER"][0]["TEXTSTYLE"][0]}" text="{esc(header)}"/>'
        )
    else:
        xml += (
            f'<label pos="-0.03 -0.025 -0.2" size="{w0-0.05} {hsize}" halign="left" '
            f'style="{style["HEADER"][0]["TEXTSTYLE"][0]}" text="{esc(header)}"/>'
        )

    image = links[0] if len(links) > 0 else ""
    image_h = "0.4" if square else "0.3"
    xml += (
        f'<quad pos="-{w0/2} -{0.02 + hsize} -0.2" size="0.4 {image_h}" '
        f'halign="center" image="{esc(image)}"/>'
    )

    xml += (
        f'<quad pos="-{w0/2} -{0.33 + (0.1 if square else 0.0) + hsize} -0.1" '
        f'size="{w0-0.02} {0.02 + hsize + lines*bsize}" halign="center" '
        f'style="{style["BODY"][0]["STYLE"][0]}" '
        f'substyle="{style["BODY"][0]["SUBSTYLE"][0]}"/>'
        f'<format style="{style["BODY"][0]["TEXTSTYLE"][0]}"/>'
    )

    cnt = 0
    for line in data:
        cnt += 1
        if not line:
            continue
        for i in range(len(widths) - 1):
            xpos = 0.025 + sum(widths[1:1+i])
            ypos = 0.305 + (0.1 if square else 0.0) + hsize + cnt*bsize
            cell = line[i] if i < len(line) else ""
            xml += (
                f'<label pos="-{xpos} -{ypos} -0.2" size="{widths[i+1]} {0.02+bsize}" '
                f'halign="left" style="{style["BODY"][0]["TEXTSTYLE"][0]}" '
                f'text="{esc(cell)}"/>'
            )

    ypos_links = 0.36 + (0.1 if square else 0.0) + hsize + lines*bsize
    xml += (
        f'<format style="{style["HEADER"][0]["TEXTSTYLE"][0]}"/>'
        f'<label pos="-{w0*0.25} -{ypos_links} -0.2" size="{w0/2} {hsize}" halign="center" '
        f'style="{style["HEADER"][0]["TEXTSTYLE"][0]}" text="{esc(links[2] if len(links) > 2 else "")}"/>'
        f'<label pos="-{w0*0.75} -{ypos_links} -0.2" size="{w0/2} {hsize}" halign="center" '
        f'style="{style["HEADER"][0]["TEXTSTYLE"][0]}" text="{esc(links[3] if len(links) > 3 else "")}"/>'
    )

    ypos_close = 0.35 + (0.1 if square else 0.0) + 2*hsize + lines*bsize
    xml += (
        f'<quad pos="-{w0/2} -{ypos_close} -0.2" size="0.06 0.06" halign="center" '
        f'style="Icons64x64_1" substyle="Close" action="0"/>'
        '</frame></manialink>'
    )
    xml = xml.replace('{#black}', style['WINDOW'][0]['BLACKCOLOR'][0])

    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin',
        login,
        aseco.format_colors(xml),
        0,
        True,
    )


# Public website hosts used for user-facing links / downloads.
TMX_HOST_ALIASES = {
    "TMNF": "tmnf.exchange",
    "TMU": "tmuf.exchange",
    "TMN": "nations.tm-exchange.com",
    "TMO": "original.tm-exchange.com",
    "TMS": "sunrise.tm-exchange.com",
}

# API prefixes used for tm-exchange API calls.
TMX_PREFIXES = {
    "TMNF": "tmnforever",
    "TMU": "united",
    "TMN": "nations",
    "TMO": "original",
    "TMS": "sunrise",
}

TMX_SITE_ORDER = ["TMNF", "TMU", "TMN", "TMO", "TMS"]

_tmxdata = None  # cached TMX data for current track
_tmx_worldrec_cached_msg = ""
_tmx_helper_cache = {key: BoundedCache() for key in ('trackid', 'trackinfo', 'image', 'trackmeta')}
_tmx_wr_cache = BoundedCache(ttl=60, negative_ttl=15)
_runtime_aseco = None


def register(aseco: "Aseco"):
    global _runtime_aseco
    _runtime_aseco = aseco
    aseco.register_service(
        'service/tmx',
        sys.modules[__name__],
        owner='service/tmx',
        aliases=['tmx'],
    )
    aseco.register_event("onNewChallenge2", _tmx_worldrec)
    aseco.register_event("onPlayerConnect", _tmx_worldrec_player_connect)
    aseco.add_chat_command("tmxinfo", "Displays TMX info {Track_ID/TMX_ID} {sec}")
    aseco.add_chat_command("tmxrecs", "Displays TMX records {Track_ID/TMX_ID} {sec}")
    aseco.register_event("onChat_tmxinfo", chat_tmxinfo)
    aseco.register_event("onChat_tmxrecs", chat_tmxrecs)


async def _get_tmx_section(aseco: "Aseco") -> str:
    game = aseco.server.get_game()
    if game == "TMF":
        return "TMNF" if aseco.server.packmask == "Stadium" else "TMU"
    return game


def _tmx_prefix_for_section(section: str) -> str:
    return TMX_PREFIXES.get((section or "").upper(), "tmnforever")


def _tmx_site_for_prefix(prefix: str) -> str:
    for site, pref in TMX_PREFIXES.items():
        if pref == prefix:
            return site
    return "TMNF"


def _tmx_public_host_for_prefix(prefix: str) -> str:
    site = _tmx_site_for_prefix(prefix)
    return TMX_HOST_ALIASES.get(site, f"{prefix}.tm-exchange.com")


def normalise_tmx_web_url(url: str, *, html_amp: bool = False) -> str:
    val = str(url or "").strip()
    if not val:
        return ""
    if val.startswith("https://"):
        val = "http://" + val[len("https://"):]
    elif not val.startswith("http://"):
        val = f"http://{val.lstrip('/')}"
    return val.replace("&", "&amp;") if html_amp else val


async def get_tmx_section(aseco: "Aseco") -> str:
    return await _get_tmx_section(aseco)


async def resolve_tmx_track_id(uid: str, preferred_section: str | None = None) -> tuple[int | None, str | None]:
    return await _resolve_tmx_track_id(uid, preferred_section)


def tmx_prefix_for_section(section: str) -> str:
    return _tmx_prefix_for_section(section)


def tmx_site_for_prefix(prefix: str) -> str:
    return _tmx_site_for_prefix(prefix)


def tmx_public_host_for_prefix(prefix: str) -> str:
    return _tmx_public_host_for_prefix(prefix)


def tmx_public_host_for_section(section: str) -> str:
    return TMX_HOST_ALIASES.get((section or "").upper(), "tmnf.exchange")


def build_public_tmx_track_url(
    aseco: "Aseco",
    challenge=None,
    *,
    track_id: int | str | None = None,
    prefix: str = "",
    pageurl: str = "",
    html_amp: bool = False,
) -> str:
    if pageurl:
        return normalise_tmx_web_url(pageurl, html_amp=html_amp)

    ch = challenge if challenge is not None else getattr(aseco.server, "challenge", None)
    for attr in ("tmx", "mx"):
        obj = getattr(ch, attr, None)
        if obj is None:
            continue
        obj_pageurl = getattr(obj, "pageurl", "") or ""
        if obj_pageurl:
            return normalise_tmx_web_url(obj_pageurl, html_amp=html_amp)
        obj_id = str(getattr(obj, "id", "") or "").strip()
        if obj_id.isdigit():
            host = _tmx_public_host_for_prefix(prefix or str(getattr(obj, "prefix", "") or "").strip())
            return normalise_tmx_web_url(f"{host}/trackshow/{obj_id}", html_amp=html_amp)

    chosen_id = str(track_id or getattr(ch, "tmx_id", "") or "").strip()
    chosen_prefix = str(prefix or getattr(ch, "tmx_prefix", "") or "").strip()
    if chosen_id.isdigit():
        host = _tmx_public_host_for_prefix(chosen_prefix) if chosen_prefix else tmx_public_host_for_section(
            getattr(aseco.server, "get_game", lambda: "TMF")() if hasattr(aseco.server, "get_game") else getattr(aseco.server, "game", "TMF")
        )
        return normalise_tmx_web_url(f"{host}/trackshow/{chosen_id}", html_amp=html_amp)

    return normalise_tmx_web_url(tmx_public_host_for_section(
        getattr(aseco.server, "get_game", lambda: "TMF")() if hasattr(aseco.server, "get_game") else getattr(aseco.server, "game", "TMF")
    ), html_amp=html_amp)


async def _tmx_get_json(url: str):
    if _runtime_aseco is None:
        raise RuntimeError('TMX runtime is not registered')
    return await request_json(_runtime_aseco, 'tmx_metadata', 'GET', url, timeout=10)


def _tmx_results(data):
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get('Results'), list):
        raise ValueError('Invalid TMX results response')
    results = data['Results']
    if any(not isinstance(row, dict) for row in results):
        raise ValueError('Invalid TMX result row')
    return results


async def _resolve_tmx_track_id(uid: str, preferred_section: str | None = None) -> tuple[int | None, str | None]:
    """
    Resolve TMX TrackId from map UID.
    Returns: (track_id, prefix) or (None, None)
    """
    uid = str(uid or "").strip()
    if not uid:
        return None, None
    cache_key = (uid, (preferred_section or '').upper())
    cached = _tmx_helper_cache['trackid'].get(cache_key)
    if cached is not None:
        return cached if cached else (None, None)

    order: list[str] = []
    pref = (preferred_section or "").upper()
    if pref in TMX_PREFIXES:
        order.append(pref)
    for site in TMX_SITE_ORDER:
        if site not in order:
            order.append(site)

    last_error = None
    for site in order:
        prefix = _tmx_prefix_for_section(site)
        url = f"https://{prefix}.tm-exchange.com/api/tracks?fields=TrackId&uid={urllib.parse.quote(uid, safe='')}"

        logger.debug("[TMXInfo] UID resolve section=%s prefix=%s uid=%s", site, prefix, uid)
        logger.debug("[TMXInfo] URL: %s", url)

        try:
            async with asyncio.timeout(5):
                data = await _tmx_get_json(url)
            results = _tmx_results(data)
            if results:
                track_id = int(results[0].get('TrackId', 0) or 0)
                if track_id <= 0:
                    raise ValueError('Invalid TMX identity')
                answer = track_id, prefix
                _tmx_helper_cache['trackid'][cache_key] = answer
                return answer
        except (ClientError, OSError, ValueError, TypeError) as error:
            last_error = error
            logger.debug('[TMXInfo] UID lookup failed on %s (%s); trying next site', site, type(error).__name__)

    if last_error is not None:
        # A failed site may hold the map. Do not turn an outage into a cached miss.
        raise last_error

    logger.debug("[TMXInfo] Could not resolve TMX TrackId from UID: %s", uid)
    # Use a false value for short-lived confirmed negatives.
    _tmx_helper_cache['trackid'][cache_key] = False
    return None, None


async def _fetch_tmx_replays(track_id: int, prefix: str) -> list[dict]:
    url = (
        f"https://{prefix}.tm-exchange.com/api/replays"
        f"?fields=ReplayTime,ReplayId,ReplayScore,Score,TrackAt,ReplayAt,User.UserId,User.Name"
        f"&trackId={int(track_id)}&best=1"
    )

    logger.debug("[TMXInfo] Replays URL: %s", url)

    data = await _tmx_get_json(url)
    if data is None:
        return []

    if not isinstance(data, dict) or not isinstance(data.get('Results'), list):
        raise ValueError('Invalid TMX replay response')
    results = data['Results']

    public_host = _tmx_public_host_for_prefix(prefix)

    replays: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue

        user = r.get("User", {}) if isinstance(r.get("User"), dict) else {}
        replay_id = int(r.get("ReplayId", 0) or 0)

        replays.append({
            "id": replay_id,
            "name": _decode_tmx_legacy_text(user.get("Name", "?")) or "?",
            "time": int(r.get("ReplayTime", 0) or 0),
            "score": r.get("ReplayScore"),
            "leaderboard_score": r.get("Score"),
            "url": f"{public_host}/recordgbx/{replay_id}",
            "track_at": r.get("TrackAt", ""),
            "replay_at": r.get("ReplayAt", ""),
        })

    return replays


def _parse_tmx_track_result(t: dict, prefix: str, replays: list[dict]) -> dict:
    authors = t.get("Authors", [])
    author_name = "?"
    if authors and isinstance(authors[0], dict):
        user = authors[0].get("User", {})
        if isinstance(user, dict):
            author_name = _decode_tmx_legacy_text(user.get("Name", "?")) or "?"

    type_map = {
        0: "Race",
        1: "Puzzle",
        2: "Platform",
        3: "Stunts",
        4: "Shortcut",
        5: "Laps",
    }
    style_map = {
        0: "Normal",
        1: "Stunt",
        2: "Maze",
        3: "Offroad",
        4: "Laps",
        5: "Fullspeed",
        6: "LOL",
        7: "Tech",
        8: "SpeedTech",
        9: "RPG",
        10: "PressForward",
        11: "Trial",
        12: "Grass",
    }
    env_map = {
        1: "Snow",
        2: "Desert",
        3: "Rally",
        4: "Island",
        5: "Coast",
        6: "Bay",
        7: "Stadium",
    }
    mood_map = {
        0: "Sunrise",
        1: "Day",
        2: "Sunset",
        3: "Night",
    }
    route_map = {
        0: "Single",
        1: "Multiple",
        2: "Symmetrical",
    }
    diff_map = {
        0: "Beginner",
        1: "Intermediate",
        2: "Expert",
        3: "Lunatic",
    }

    track_id = int(t.get("TrackId", 0) or 0)
    public_host = _tmx_public_host_for_prefix(prefix)

    return {
        "id": track_id,
        "uid": t.get("UId", ""),
        "name": _decode_tmx_legacy_text(t.get("TrackName", "")),
        "author": author_name,
        "uploaded": str(t.get("UploadedAt", "") or "")[:16],
        "updated": str(t.get("UpdatedAt", "") or "")[:16],
        "type": type_map.get(t.get("PrimaryType"), ""),
        "style": style_map.get(t.get("Style"), ""),
        "envir": env_map.get(t.get("Environment"), ""),
        "mood": mood_map.get(t.get("Mood"), ""),
        "routes": route_map.get(t.get("Routes"), ""),
        "diffic": diff_map.get(t.get("Difficulty"), ""),
        "length": "",
        "awards": t.get("Awards", 0),
        "lbrating": t.get("TrackValue", 0),
        "section": _tmx_site_for_prefix(prefix),
        "recordlist": replays,
        "imageurl": f"https://{public_host}/get.aspx?action=trackscreen&id={track_id}&.jpg",
        "pageurl": f"{public_host}/trackshow/{track_id}",
        "dloadurl": f"{public_host}/trackgbx/{track_id}",
        "replayurl": replays[0].get("url", "") if replays else "",
        "author_time": int(t.get("AuthorTime", 0) or 0),
        "author_score": t.get("AuthorScore"),
        "gold_target": int(t.get("GoldTarget", 0) or 0),
        "silver_target": int(t.get("SilverTarget", 0) or 0),
        "bronze_target": int(t.get("BronzeTarget", 0) or 0),
    }


async def _fetch_tmx_info(uid_or_id: str, section: str, with_records: bool) -> dict | None:
    """
    Fetch TMX info by numeric TMX TrackId or by map UID.
    """
    arg = str(uid_or_id or "").strip()
    if not arg:
        return None

    if arg.isdigit():
        track_id = int(arg)
        prefix = _tmx_prefix_for_section(section)

        url = (
            f"https://{prefix}.tm-exchange.com/api/tracks"
            f"?fields=TrackId,TrackName,UId,AuthorTime,AuthorScore,GoldTarget,SilverTarget,"
            f"BronzeTarget,Authors,UploadedAt,UpdatedAt,PrimaryType,AuthorComments,Style,"
            f"Routes,Difficulty,Environment,Car,Mood,Awards,Comments,Images,TrackValue"
            f"&id={track_id}"
        )

        logger.debug("[TMXInfo] TrackId fetch section=%s prefix=%s track_id=%s", section, prefix, track_id)
        logger.debug("[TMXInfo] URL: %s", url)

        data = await _tmx_get_json(url)
        results = _tmx_results(data)
        if not results or not isinstance(results[0], dict):
            return None
        if int(results[0].get('TrackId', 0) or 0) != track_id:
            raise ValueError('TMX metadata does not match requested track ID')

        replays = await _fetch_tmx_replays(track_id, prefix) if with_records else []
        return _parse_tmx_track_result(results[0], prefix, replays)

    track_id, prefix = await _resolve_tmx_track_id(arg, section)
    if not track_id or not prefix:
        logger.debug("[TMXInfo] No TMX track found for UID: %s", arg)
        return None

    url = (
        f"https://{prefix}.tm-exchange.com/api/tracks"
        f"?fields=TrackId,TrackName,UId,AuthorTime,AuthorScore,GoldTarget,SilverTarget,"
        f"BronzeTarget,Authors,UploadedAt,UpdatedAt,PrimaryType,AuthorComments,Style,"
        f"Routes,Difficulty,Environment,Car,Mood,Awards,Comments,Images,TrackValue"
        f"&id={track_id}"
    )

    logger.debug("[TMXInfo] UID resolved to track_id=%s prefix=%s", track_id, prefix)
    logger.debug("[TMXInfo] URL: %s", url)

    data = await _tmx_get_json(url)
    results = _tmx_results(data)
    if not results or not isinstance(results[0], dict):
        return None
    if int(results[0].get('TrackId', 0) or 0) != track_id:
        raise ValueError('TMX metadata does not match resolved track ID')
    if str(results[0].get('UId', '')) != arg:
        raise ValueError('TMX metadata UID does not match requested map')

    replays = await _fetch_tmx_replays(track_id, prefix) if with_records else []
    return _parse_tmx_track_result(results[0], prefix, replays)


async def _load_tmx_image_for_uid(aseco: "Aseco", uid: str) -> str:
    key = str(uid or "").strip()
    if not key:
        return ""
    cached = _tmx_helper_cache["image"].get(key)
    if cached is not None:
        return cached
    section = await _get_tmx_section(aseco)
    track_id, prefix = await _resolve_tmx_track_id(key, section)
    if not track_id or not prefix:
        _tmx_helper_cache["image"][key] = ""
        return ""
    host = _tmx_public_host_for_prefix(prefix)
    image = f"https://{host}/get.aspx?action=trackscreen&id={track_id}&.jpg"
    _tmx_helper_cache["image"][key] = image
    return image


async def _load_tmx_trackinfo_for_uid(aseco: "Aseco", uid: str, mode: int) -> dict:
    key = (str(uid or "").strip(), int(mode))
    if not key[0]:
        return {}
    cached = _tmx_helper_cache["trackinfo"].get(key)
    if cached is not None:
        return dict(cached)

    section = await _get_tmx_section(aseco)
    data = await _fetch_tmx_info(key[0], section, True)
    if not data:
        _tmx_helper_cache["trackinfo"][key] = {}
        return {}

    out = {
        "authortime": str(data.get("author_score", "")) if mode == Gameinfo.STNT else format_time(int(data.get("author_time", 0) or 0)),
        "goldtime": format_time(int(data.get("gold_target", 0) or 0)) if data.get("gold_target") else "",
        "silvertime": format_time(int(data.get("silver_target", 0) or 0)) if data.get("silver_target") else "",
        "bronzetime": format_time(int(data.get("bronze_target", 0) or 0)) if data.get("bronze_target") else "",
        "authortime_ms": int(data.get("author_time", 0) or 0),
        "goldtime_ms": int(data.get("gold_target", 0) or 0),
        "silvertime_ms": int(data.get("silver_target", 0) or 0),
        "bronzetime_ms": int(data.get("bronze_target", 0) or 0),
        "env": str(data.get("envir", "") or ""),
        "mood": str(data.get("mood", "") or ""),
        "type": str(data.get("type", "") or ""),
        "style": str(data.get("style", "") or ""),
        "diffic": str(data.get("diffic", "") or ""),
        "routes": str(data.get("routes", "") or ""),
        "awards": str(data.get("awards", "") or ""),
        "section": str(data.get("section", "") or ""),
        "imageurl": str(data.get("imageurl", "") or ""),
        "pageurl": str(data.get("pageurl", "") or ""),
        "dloadurl": str(data.get("dloadurl", "") or ""),
        "replayurl": str(data.get("replayurl", "") or ""),
        "uploaded": str(data.get("uploaded", "") or ""),
        "updated": str(data.get("updated", "") or ""),
    }
    _tmx_helper_cache["trackinfo"][key] = dict(out)
    return out


async def _load_tmx_trackmeta_for_uid(aseco: "Aseco", uid: str) -> dict:
    key = str(uid or "").strip()
    if not key:
        return {}

    cached = _tmx_helper_cache["trackmeta"].get(key)
    if cached is not None:
        return dict(cached)

    section = await _get_tmx_section(aseco)
    data = await _fetch_tmx_info(key, section, False)
    if not data:
        _tmx_helper_cache["trackmeta"][key] = {}
        return {}

    out = {
        "id": int(data.get("id", 0) or 0),
        "uploaded": str(data.get("uploaded", "") or ""),
        "pageurl": str(data.get("pageurl", "") or ""),
        "section": str(data.get("section", "") or ""),
    }
    _tmx_helper_cache["trackmeta"][key] = dict(out)
    return out


async def _cached_helper(aseco, kind, uid, mode=None):
    if not uid:
        return '' if kind == 'image' else {}
    key = (str(uid), int(mode)) if kind == 'trackinfo' else str(uid)
    cached = _tmx_helper_cache[kind].get(key)
    if cached is not None:
        return cached.copy() if isinstance(cached, dict) else cached
    job = JobEnvelope.capture(aseco.capture_job_context(), {'uid': str(uid), 'mode': mode})
    loaders = {'image': _load_tmx_image_for_uid, 'trackinfo': _load_tmx_trackinfo_for_uid,
               'trackmeta': _load_tmx_trackmeta_for_uid}
    async def operation(envelope):
        data = envelope.payload()
        args = (aseco, data['uid'], data['mode']) if kind == 'trackinfo' else (aseco, data['uid'])
        return await loaders[kind](*args)
    async def apply(result):
        if result.status == 'completed':
            await aseco.release_event('onTmxMetadataLoaded', str(uid))
    aseco.jobs.service('tmx_metadata', JobPolicy(deadline_seconds=60)).submit(
        job, operation, apply, dedupe_key=kind + ':' + str(key))
    return '' if kind == 'image' else {}


async def get_tmx_image_for_uid(aseco, uid):
    return await _cached_helper(aseco, 'image', uid)


async def get_tmx_trackinfo_for_uid(aseco, uid, mode):
    return await _cached_helper(aseco, 'trackinfo', uid, mode)


async def get_tmx_trackmeta_for_uid(aseco, uid):
    return await _cached_helper(aseco, 'trackmeta', uid)


async def get_tmx_world_record_for_uid(aseco: "Aseco", uid: str) -> dict:
    key = str(uid or "").strip()
    if not key:
        return {}

    section = await _get_tmx_section(aseco)
    cached = _tmx_wr_cache.get((key, section))
    if cached is not None:
        return dict(cached)
    data = await _fetch_tmx_info(key, section, True)
    if not data:
        _tmx_wr_cache[(key, section)] = {}
        return {}

    records = data.get("recordlist", [])
    if not isinstance(records, list) or not records:
        _tmx_wr_cache[(key, section)] = {}
        return {}

    rec = records[0] if isinstance(records[0], dict) else {}
    if not rec:
        return {}

    answer = {
        "score": int(rec.get("time", 0) or 0),
        "name": str(rec.get("name", "") or ""),
        "url": str(rec.get("url", "") or ""),
        "track_id": int(data.get("id", 0) or 0),
        "section": str(data.get("section", "") or ""),
    }
    _tmx_wr_cache[(key, section)] = answer
    return dict(answer)


async def _tmx_worldrec_player_connect(aseco: "Aseco", player):
    show = int(getattr(aseco.settings, "show_tmxrec", 0) or 0)
    if show <= 0 or not _tmx_worldrec_cached_msg:
        return
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors(_tmx_worldrec_cached_msg),
        player.login,
    )


async def _tmx_worldrec(aseco: "Aseco", challenge):
    global _tmx_worldrec_cached_msg
    _tmx_worldrec_cached_msg = ""
    uid = str(getattr(challenge, 'uid', '') or '')
    if not uid:
        return
    section = await _get_tmx_section(aseco)
    mode = aseco.server.gameinfo.mode
    panel = sys.modules.get('apps.platform_ui.panels')
    if panel:
        panel.set_records_panel('tmx', '  ---' if mode == Gameinfo.STNT else '---.--')
        await panel.update_allrecpanels(aseco)
    job = JobEnvelope.capture(aseco.capture_job_context(), {'uid': uid, 'section': section})
    async def operation(envelope):
        p = envelope.payload()
        return await _fetch_tmx_info(p['uid'], p['section'], True)
    async def apply(result):
        global _tmx_worldrec_cached_msg
        if result.status != 'completed':
            return
        data = result.value or {}
        if data:
            challenge.tmx_id = data['id']
            challenge.tmx_prefix = _tmx_prefix_for_section(data['section'])
        records = data.get('recordlist', [])
        value = '  ---' if mode == Gameinfo.STNT else '---.--'
        if records:
            rec = records[0]
            value = str(rec['time']) if mode == Gameinfo.STNT else format_time(rec['time'])
            if int(getattr(aseco.settings, 'show_tmxrec', 0) or 0) > 0:
                msg = format_text(aseco.get_chat_message('TMXREC'), value, rec['name'])
                _tmx_worldrec_cached_msg = msg
                await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))
        if panel:
            panel.set_records_panel('tmx', value)
            await panel.update_allrecpanels(aseco)
    aseco.jobs.service('tmx_metadata', JobPolicy(deadline_seconds=60)).submit(
        job, operation, apply, dedupe_key='worldrec')


async def _queue_tmx_command(aseco, command, render):
    player = command['author']
    login = player.login
    params = (command.get('params') or '').split()
    section = params[1].upper() if len(params) > 1 else await _get_tmx_section(aseco)
    if section not in TMX_PREFIXES:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}Unknown TMX section; use TMNF, TMU, TMN, TMO or TMS.'), login)
        return
    ref = params[0] if params else aseco.server.challenge.uid
    mode = aseco.server.gameinfo.mode
    job = JobEnvelope.capture(aseco.capture_job_context(login=login),
                              {'ref': ref, 'section': section})
    async def operation(envelope):
        p = envelope.payload()
        return await _fetch_tmx_info(p['ref'], p['section'], True)
    async def apply(result):
        if aseco.server.players.get_player(login) is not player:
            return
        if result.status != 'completed':
            await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
                aseco.format_colors('{#server}> {#error}TMX lookup unavailable; try again later.'), login)
            return
        data = dict(result.value, _requested_mode=mode) if result.value else None
        await render(aseco, login, data)
    key = sha256(f'{render.__name__}:{section}:{ref}:{id(player)}'.encode()).hexdigest()
    admitted = aseco.jobs.service('tmx_commands', JobPolicy(capacity=8, workers=2, deadline_seconds=60)).submit(
        job, operation, apply, dedupe_key=key, current_map=not bool(params))
    from pyxaseco.core.background_jobs import Admission
    message = '{#server}> Loading TMX data...' if admitted in (Admission.ACCEPTED, Admission.DUPLICATE) else '{#server}> {#error}TMX lookup busy; retry shortly.'
    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors(message), login)


async def chat_tmxinfo(aseco, command):
    await _queue_tmx_command(aseco, command, _render_tmxinfo)


async def chat_tmxrecs(aseco, command):
    await _queue_tmx_command(aseco, command, _render_tmxrecs)


async def _render_tmxinfo(aseco, login, data):
    if not data:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors("{#server}> {#error}Track not found on TMX!"),
            login,
        )
        return

    header = f'{_literal_ml_text("TMX Info for:")} {{#black}}{data["name"]}'
    stats = [
        [_literal_ml_text("TMX ID"), f'{{#black}}{data["id"]}', _literal_ml_text("Type/Style"), f'{{#black}}{data["type"]}$g / {{#black}}{data["style"]}'],
        [_literal_ml_text("Section"), f'{{#black}}{data["section"]}', _literal_ml_text("Env/Mood"), f'{{#black}}{data["envir"]}$g / {{#black}}{data["mood"]}'],
        [_literal_ml_text("UID"), f'{{#black}}$n{data["uid"]}', _literal_ml_text("Routes"), f'{{#black}}{data["routes"]}'],
        [_literal_ml_text("Author"), f'{{#black}}{data["author"]}', _literal_ml_text("Difficulty"), f'{{#black}}{data["diffic"]}'],
        [_literal_ml_text("Uploaded"), f'{{#black}}{data["uploaded"]}', _literal_ml_text("Awards"), f'{{#black}}{data["awards"]}'],
        [_literal_ml_text("Updated"), f'{{#black}}{data["updated"]}', _literal_ml_text("LB Rating"), f'{{#black}}{data["lbrating"]}'],
        [_literal_ml_text("TMX Page"), f'{{#black}}{_literal_ml_link(data["pageurl"], "Open")}' if data.get("pageurl") else _literal_ml_text("<none>"), _literal_ml_text("Replay"), (f'{{#black}}{_literal_ml_link(data["replayurl"], "Download")}' if data.get("replayurl") else _literal_ml_text("<none>"))],
    ]

    if aseco.server.get_game() == "TMF":
        imageurl = data.get("imageurl", "")
        if not imageurl:
            try:
                imageurl = await get_tmx_image_for_uid(aseco, data.get("uid", ""))
            except Exception:
                imageurl = ""
        links = [
            imageurl,
            False,
            _literal_ml_link(data["pageurl"], "Visit TMX Page") if data.get("pageurl") else "",
            _literal_ml_link(data["dloadurl"], "Download Track") if data.get("dloadurl") else "",
        ]
        await _display_manialink_track(
            aseco,
            login,
            header,
            ["Icons64x64_1", "Maximize", -0.01],
            links,
            stats,
            [1.15, 0.2, 0.45, 0.2, 0.3],
            "OK",
        )
        return

    display_manialink(
        aseco,
        login,
        header,
        ["Icons64x64_1", "Maximize", -0.01],
        stats,
        [1.15, 0.2, 0.45, 0.2, 0.3],
        "OK",
    )


async def _render_tmxrecs(aseco, login, data):
    if not data:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors("{#server}> {#error}Track not found on TMX!"),
            login,
        )
        return

    records = data.get("recordlist", [])
    if not records:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors(f'{{#server}}> {{#error}}No TMX records found for {{#highlite}}$i {data["name"]}'),
            login,
        )
        return

    is_stunts = data.get('_requested_mode', getattr(aseco.server.gameinfo, 'mode', -1)) == Gameinfo.STNT

    header = f'{_literal_ml_text("TMX Top-10 Records:")} {{#black}}{data["name"]}'
    rows = [
        [
            f"{i + 1:02d}.",
            f'{{#black}}{rec.get("name", "?")}',
            str(rec.get("time", 0)) if is_stunts else format_time(int(rec.get("time", 0) or 0)),
        ]
        for i, rec in enumerate(records[:10])
    ]

    display_manialink(
        aseco,
        login,
        header,
        ["BgRaceScore2", "Podium"],
        rows,
        [0.9, 0.1, 0.5, 0.3],
        "OK",
    )

