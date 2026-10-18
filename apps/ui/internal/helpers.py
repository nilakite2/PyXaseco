from __future__ import annotations

import logging
from typing import Any

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo
from pyxaseco.app_services import get_tmx_service, localdb_get_pool
from pyxaseco.core.bounded_cache import BoundedCache

from ..config import _state

logger = logging.getLogger(__name__)


def _tmx_service(aseco=None):
    runtime = aseco or getattr(_state, 'aseco', None)
    return get_tmx_service(runtime)


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
        cache = {'tmx_trackid': {}, 'tracklist': {}, 'challenge_info': {}}
        aseco._records_eyepiece_helper_cache = cache
    return cache


async def _enrich_track_with_database(aseco, track, mode):
    uid = str(track.get('uid') or '').strip()
    if not uid:
        return
    helper_cache = _helper_cache(aseco)
    cache = helper_cache.get('challenge_metadata')
    if cache is None:
        cache = helper_cache['challenge_metadata'] = BoundedCache()
    data = cache.get(uid)
    if data is None:
        try:
            pool = await localdb_get_pool(aseco)
            if not pool:
                return
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'SELECT c.Name, c.Author, c.Environment, x.AuthorTime, x.GoldTime, x.TMX_UploadDate '
                        'FROM challenges c LEFT JOIN challenges_extra x ON x.Challenge_Id=c.Id '
                        'WHERE c.Uid=%s LIMIT 1', (uid,))
                    row = await cur.fetchone()
            data = (dict(name=row[0], author=row[1], env=row[2],
                         author_time=row[3], gold_time=row[4], uploaded=row[5]) if row else {})
            cache[uid] = data
        except Exception as error:
            logger.debug('[Eyepiece/Helpers] Stored challenge metadata unavailable (%s)', type(error).__name__)
            return
    for key in ('name', 'author', 'env', 'uploaded'):
        if str(track.get(key) or '').strip() in ('', '-', 'N/A') and data.get(key):
            track[key] = str(data[key])
    if mode != Gameinfo.STNT:
        for raw, source, display in (('authortime_ms', 'author_time', 'authortime'),
                                     ('goldtime_ms', 'gold_time', 'goldtime')):
            value = _safe_int(data.get(source), 0)
            if not _safe_int(track.get(raw), 0) and value > 0:
                track[raw] = value
                track[display] = _fmt_track_value(mode, value)


async def _get_tmx_section(aseco) -> str:
    service = _tmx_service(aseco)
    impl = getattr(service, 'get_tmx_section', None) if service is not None else None
    return await impl(aseco) if callable(impl) else ''


def _tmx_prefix_for_section(section: str) -> str:
    service = _tmx_service()
    impl = getattr(service, 'tmx_prefix_for_section', None) if service is not None else None
    return impl(section) if callable(impl) else str(section or '')


def _tmx_site_for_prefix(prefix: str) -> str:
    service = _tmx_service()
    impl = getattr(service, 'tmx_site_for_prefix', None) if service is not None else None
    return impl(prefix) if callable(impl) else ''


def _tmx_public_host_for_prefix(prefix: str) -> str:
    service = _tmx_service()
    impl = getattr(service, 'tmx_public_host_for_prefix', None) if service is not None else None
    return impl(prefix) if callable(impl) else ''


async def _resolve_tmx_track_id(aseco, uid: str, preferred_section: str | None = None) -> tuple[int | None, str | None]:
    uid = str(uid or '').strip()
    if not uid:
        return None, None
    cache = _helper_cache(aseco)['tmx_trackid']
    if uid not in cache:
        service = _tmx_service(aseco)
        impl = getattr(service, 'resolve_tmx_track_id', None) if service is not None else None
        cache[uid] = await impl(uid, preferred_section) if callable(impl) else (None, None)
    return cache[uid]


def _no_screenshot_image() -> str:
    return getattr(_state.images, 'no_screenshot', '') or ''


async def _get_tmx_image_for_uid(aseco, uid: str) -> str:
    service = _tmx_service(aseco)
    impl = getattr(service, 'get_tmx_image_for_uid', None) if service is not None else None
    image = await impl(aseco, uid) if callable(impl) else ''
    return image or _no_screenshot_image()


async def _get_tmx_trackinfo_for_uid(aseco, uid: str, mode: int) -> dict:
    uid = str(uid or '').strip()
    if not uid:
        return {}
    # The service owns the bounded cache. An empty first result can mean that
    # its background lookup is still running, not that this map has no metadata.
    service = _tmx_service(aseco)
    impl = getattr(service, 'get_tmx_trackinfo_for_uid', None) if service is not None else None
    info = await impl(aseco, uid, mode) if callable(impl) else {}
    return dict(info) if isinstance(info, dict) else {}


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

    await _enrich_track_with_database(aseco, track, mode)

    uid = str(track.get('uid') or '').strip()
    if not uid:
        return track

    missing_mood = need_mood and not str(track.get('mood') or '').strip()
    missing_env = need_env and not str(track.get('env') or '').strip()
    missing_times = need_times and not _safe_int(track.get('authortime_ms'), 0)
    missing_meta = need_meta and any(
        not str(track.get(key) or '').strip()
        for key in (
            'type', 'style', 'diffic', 'routes', 'awards', 'section',
            'imageurl', 'pageurl', 'dloadurl', 'uploaded', 'updated'
        )
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
        for raw, display in (('authortime_ms', 'authortime'), ('goldtime_ms', 'goldtime'),
                             ('silvertime_ms', 'silvertime'), ('bronzetime_ms', 'bronzetime')):
            if info.get(raw):
                track[raw] = info[raw]
                track[display] = str(info.get(display) or _fmt_track_value(mode, info[raw]))
    if missing_meta:
        for key in (
            'type', 'style', 'diffic', 'routes', 'awards', 'section',
            'imageurl', 'pageurl', 'dloadurl', 'replayurl', 'uploaded', 'updated'
        ):
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


