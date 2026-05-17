from __future__ import annotations

import logging
from typing import Any

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo
from pyxaseco.plugins.plugin_tmxinfo import (
    get_tmx_image_for_uid as _plugin_get_tmx_image_for_uid,
    get_tmx_section as _plugin_get_tmx_section,
    get_tmx_trackinfo_for_uid as _plugin_get_tmx_trackinfo_for_uid,
    resolve_tmx_track_id as _plugin_resolve_tmx_track_id,
    tmx_prefix_for_section as _plugin_tmx_prefix_for_section,
    tmx_public_host_for_prefix as _plugin_tmx_public_host_for_prefix,
    tmx_site_for_prefix as _plugin_tmx_site_for_prefix,
)

from .config import _state

logger = logging.getLogger(__name__)


def _clip(text: str, _n: int) -> str:
    return str(text or '')


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _tm_escape(text: Any) -> str:
    if text is None:
        return ''
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('"', '&quot;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def _fmt_track_value(mode: int, value: Any) -> str:
    if mode == Gameinfo.STNT:
        return str(_safe_int(value, 0))
    return format_time(_safe_int(value, 0))


def _normalise_env_name(value: str) -> str:
    env = str(value or '').strip()
    upper = env.upper()
    if upper == 'SPEED':
        return 'Desert'
    if upper == 'SNOW':
        return 'Alpine'
    return env


def _normalise_env_key(value: str) -> str:
    return _normalise_env_name(value).strip().lower()


def _helper_cache(aseco) -> dict[str, Any]:
    cache = getattr(aseco, '_records_eyepiece_helper_cache', None)
    if not isinstance(cache, dict):
        cache = {'tmx_trackinfo': {}, 'tmx_trackid': {}, 'tracklist': {}, 'challenge_info': {}}
        aseco._records_eyepiece_helper_cache = cache
    return cache


async def _get_tmx_section(aseco) -> str:
    return await _plugin_get_tmx_section(aseco)


def _tmx_prefix_for_section(section: str) -> str:
    return _plugin_tmx_prefix_for_section(section)


def _tmx_site_for_prefix(prefix: str) -> str:
    return _plugin_tmx_site_for_prefix(prefix)


def _tmx_public_host_for_prefix(prefix: str) -> str:
    return _plugin_tmx_public_host_for_prefix(prefix)


async def _resolve_tmx_track_id(aseco, uid: str, preferred_section: str | None = None) -> tuple[int | None, str | None]:
    uid = str(uid or '').strip()
    if not uid:
        return None, None
    cache = _helper_cache(aseco)['tmx_trackid']
    if uid not in cache:
        cache[uid] = await _plugin_resolve_tmx_track_id(uid, preferred_section)
    return cache[uid]


def _no_screenshot_image() -> str:
    return getattr(_state.images, 'no_screenshot', '') or ''


async def _get_tmx_image_for_uid(aseco, uid: str) -> str:
    image = await _plugin_get_tmx_image_for_uid(aseco, uid)
    return image or _no_screenshot_image()


async def _get_tmx_trackinfo_for_uid(aseco, uid: str, mode: int) -> dict:
    uid = str(uid or '').strip()
    if not uid:
        return {}
    info_cache = _helper_cache(aseco)['tmx_trackinfo']
    cache_key = (uid, mode)
    if cache_key not in info_cache:
        info_cache[cache_key] = await _plugin_get_tmx_trackinfo_for_uid(aseco, uid, mode)
    return dict(info_cache[cache_key])


async def _get_challenge_info_for_file(aseco, filename: str) -> dict:
    filename = str(filename or '').strip()
    if not filename:
        return {}

    cache = _helper_cache(aseco)['challenge_info']
    if filename in cache:
        return dict(cache[filename])

    try:
        info = await aseco.client.query('GetChallengeInfo', filename) or {}
    except Exception as e:
        logger.debug('[Eyepiece/Helpers] GetChallengeInfo failed for %s: %r', filename, e)
        info = {}

    cache[filename] = dict(info) if isinstance(info, dict) else {}
    return dict(cache[filename])


async def _enrich_track_with_challenge_info(aseco, track: dict[str, Any], mode: int, *, need_times: bool = False, need_env: bool = False, need_mood: bool = False) -> dict[str, Any]:
    if not isinstance(track, dict):
        return track

    filename = str(track.get('filename') or track.get('FileName') or '').strip()
    if not filename:
        return track

    missing_env = need_env and not str(track.get('env') or '').strip()
    missing_mood = need_mood and not str(track.get('mood') or '').strip()
    missing_times = need_times and not _safe_int(track.get('authortime_ms'), 0)

    if not (missing_env or missing_mood or missing_times):
        return track

    info = await _get_challenge_info_for_file(aseco, filename)
    if not info:
        return track

    uid = str(info.get('UId', '') or info.get('Uid', '') or '').strip()
    if uid and not str(track.get('uid') or '').strip():
        track['uid'] = uid

    name = str(info.get('Name', '') or '').strip()
    if name:
        track.setdefault('name_orig', name)
        track.setdefault('name_plain', name)
        if not str(track.get('name') or '').strip() or str(track.get('name')) == '-':
            track['name'] = name
        if not str(track.get('author') or '').strip() or str(track.get('author')) == '-':
            track['author'] = str(info.get('Author', '') or '').strip() or track.get('author', '-')

    if missing_env:
        env = _normalise_env_name(str(info.get('Environnement', '') or info.get('Environment', '') or ''))
        if env:
            track['env'] = env

    if missing_mood:
        mood = str(info.get('Mood', '') or '').strip()
        if mood:
            track['mood'] = mood

    if missing_times:
        at = _safe_int(info.get('AuthorTime'), 0)
        gt = _safe_int(info.get('GoldTime'), 0)
        st = _safe_int(info.get('SilverTime'), 0)
        bt = _safe_int(info.get('BronzeTime'), 0)
        if at > 0:
            track['authortime_ms'] = at
            track['authortime'] = _fmt_track_value(mode, at)
        if gt > 0:
            track['goldtime_ms'] = gt
            track['goldtime'] = _fmt_track_value(mode, gt)
        if st > 0:
            track['silvertime_ms'] = st
            track['silvertime'] = _fmt_track_value(mode, st)
        if bt > 0:
            track['bronzetime_ms'] = bt
            track['bronzetime'] = _fmt_track_value(mode, bt)

    return track


async def _enrich_track_with_tmx(aseco, track: dict[str, Any], mode: int, *, need_mood: bool = False, need_times: bool = False, need_env: bool = False, need_meta: bool = False) -> dict[str, Any]:
    await _enrich_track_with_challenge_info(
        aseco, track, mode,
        need_mood=need_mood,
        need_times=need_times,
        need_env=need_env,
    )

    if not isinstance(track, dict):
        return track

    uid = str(track.get('uid') or '').strip()
    if not uid:
        return track

    missing_mood = need_mood and not str(track.get('mood') or '').strip()
    missing_env = need_env and not str(track.get('env') or '').strip()
    missing_times = need_times and not _safe_int(track.get('authortime_ms'), 0)
    missing_meta = need_meta and any(
        not str(track.get(key) or '').strip()
        for key in ('type', 'style', 'diffic', 'routes', 'awards', 'section', 'imageurl', 'pageurl', 'dloadurl')
    )

    if not (missing_mood or missing_env or missing_times or missing_meta):
        return track

    info = await _get_tmx_trackinfo_for_uid(aseco, uid, mode)
    if not info:
        return track

    if missing_env and info.get('env'):
        track['env'] = info.get('env')
    if missing_mood and info.get('mood'):
        track['mood'] = info.get('mood')
    if missing_times:
        if info.get('authortime_ms'):
            track['authortime_ms'] = info.get('authortime_ms')
        if info.get('goldtime_ms'):
            track['goldtime_ms'] = info.get('goldtime_ms')
        if info.get('silvertime_ms'):
            track['silvertime_ms'] = info.get('silvertime_ms')
        if info.get('bronzetime_ms'):
            track['bronzetime_ms'] = info.get('bronzetime_ms')
    if missing_meta:
        for key in ('type', 'style', 'diffic', 'routes', 'awards', 'section',
                    'imageurl', 'pageurl', 'dloadurl', 'replayurl'):
            value = info.get(key)
            if value not in ('', None):
                track[key] = value
    return track


async def _enrich_tracks_with_tmx(aseco, tracks: list[dict[str, Any]], mode: int, *, need_mood: bool = False, need_times: bool = False, need_env: bool = False, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is None:
        seq = tracks
    else:
        seq = tracks[:limit]
    for track in seq:
        await _enrich_track_with_tmx(aseco, track, mode, need_mood=need_mood, need_times=need_times, need_env=need_env)
    return tracks
