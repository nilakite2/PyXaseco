from __future__ import annotations

import logging
import aiohttp
from typing import Any

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from .config import _state

logger = logging.getLogger(__name__)


TMX_PREFIXES = {
    'TMNF': 'tmnforever',
    'TMU': 'united',
    'TMN': 'nations',
    'TMO': 'original',
    'TMS': 'sunrise',
}

TMX_HOST_ALIASES = {
    'TMNF': 'tmnf.exchange',
    'TMU': 'tmuf.exchange',
    'TMN': 'nations.tm-exchange.com',
    'TMO': 'original.tm-exchange.com',
    'TMS': 'sunrise.tm-exchange.com',
}

TMX_SITE_ORDER = ['TMNF', 'TMU', 'TMN', 'TMO', 'TMS']


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
    try:
        game = aseco.server.get_game()
    except Exception:
        game = aseco.server.getGame() if hasattr(aseco.server, 'getGame') else ''
    if game == 'TMF':
        return 'TMNF' if getattr(aseco.server, 'packmask', '') == 'Stadium' else 'TMU'
    return game


def _tmx_prefix_for_section(section: str) -> str:
    return TMX_PREFIXES.get((section or '').upper(), 'tmnforever')


def _tmx_site_for_prefix(prefix: str) -> str:
    for site, pref in TMX_PREFIXES.items():
        if pref == prefix:
            return site
    return 'TMNF'


def _tmx_public_host_for_prefix(prefix: str) -> str:
    site = _tmx_site_for_prefix(prefix)
    return TMX_HOST_ALIASES.get(site, 'tmnf.exchange')


async def _tmx_get_json(url: str):
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.json(content_type=None)
    except Exception as e:
        logger.debug('[Eyepiece/Helpers] TMX request failed for %s: %r', url, e)
        return None


async def _resolve_tmx_track_id(aseco, uid: str, preferred_section: str | None = None) -> tuple[int | None, str | None]:
    uid = str(uid or '').strip()
    if not uid:
        return None, None

    cache = _helper_cache(aseco)['tmx_trackid']
    if uid in cache:
        return cache[uid]

    order: list[str] = []
    pref = (preferred_section or '').upper()
    if pref in TMX_PREFIXES:
        order.append(pref)
    for site in TMX_SITE_ORDER:
        if site not in order:
            order.append(site)

    for site in order:
        prefix = _tmx_prefix_for_section(site)
        url = f'https://{prefix}.tm-exchange.com/api/tracks?fields=TrackId&uid={uid}'
        data = await _tmx_get_json(url)
        if not isinstance(data, dict):
            continue
        results = data.get('Results', [])
        if results and isinstance(results[0], dict) and results[0].get('TrackId') is not None:
            try:
                pair = (int(results[0]['TrackId']), prefix)
                cache[uid] = pair
                return pair
            except Exception:
                pass

    cache[uid] = (None, None)
    return None, None


def _no_screenshot_image() -> str:
    return getattr(_state.images, 'no_screenshot', '') or ''


async def _get_tmx_image_for_uid(aseco, uid: str) -> str:
    uid = str(uid or '').strip()
    if not uid:
        return _no_screenshot_image()

    section = await _get_tmx_section(aseco)
    track_id, prefix = await _resolve_tmx_track_id(aseco, uid, section)
    if not track_id or not prefix:
        return _no_screenshot_image()

    public_host = _tmx_public_host_for_prefix(prefix)
    return f'https://{public_host}/get.aspx?action=trackscreen&id={track_id}&.jpg'


async def _get_tmx_trackinfo_for_uid(aseco, uid: str, mode: int) -> dict:
    uid = str(uid or '').strip()
    if not uid:
        return {}

    info_cache = _helper_cache(aseco)['tmx_trackinfo']
    cache_key = (uid, mode)
    if cache_key in info_cache:
        return dict(info_cache[cache_key])

    section = await _get_tmx_section(aseco)
    track_id, prefix = await _resolve_tmx_track_id(aseco, uid, section)
    if not track_id or not prefix:
        info_cache[cache_key] = {}
        return {}

    url = (
        f'https://{prefix}.tm-exchange.com/api/tracks'
        f'?fields=TrackId,TrackName,UId,AuthorTime,GoldTarget,SilverTarget,BronzeTarget,'
        f'PrimaryType,Style,Routes,Difficulty,Environment,Mood,Awards'
        f'&id={track_id}'
    )
    data = await _tmx_get_json(url)
    if not isinstance(data, dict):
        info_cache[cache_key] = {}
        return {}

    results = data.get('Results', [])
    if not results or not isinstance(results[0], dict):
        info_cache[cache_key] = {}
        return {}

    t = results[0]

    type_map = {
        0: 'Race',
        1: 'Puzzle',
        2: 'Platform',
        3: 'Stunts',
        4: 'Shortcut',
        5: 'Laps',
    }
    style_map = {
        0: 'Normal',
        1: 'Stunt',
        2: 'Maze',
        3: 'Offroad',
        4: 'Laps',
        5: 'Fullspeed',
        6: 'LOL',
        7: 'Tech',
        8: 'SpeedTech',
        9: 'RPG',
        10: 'PressForward',
        11: 'Trial',
        12: 'Grass',
    }
    mood_map = {
        0: 'Sunrise',
        1: 'Day',
        2: 'Sunset',
        3: 'Night',
    }
    route_map = {
        0: 'Single',
        1: 'Multiple',
        2: 'Symmetrical',
    }
    diff_map = {
        0: 'Beginner',
        1: 'Intermediate',
        2: 'Expert',
        3: 'Lunatic',
    }
    env_map = {
        1: 'Snow',
        2: 'Desert',
        3: 'Rally',
        4: 'Island',
        5: 'Coast',
        6: 'Bay',
        7: 'Stadium',
    }

    public_host = _tmx_public_host_for_prefix(prefix)
    site = _tmx_site_for_prefix(prefix)

    replayurl = ''
    try:
        replays_url = f'https://{prefix}.tm-exchange.com/api/replays?fields=ReplayId&trackId={track_id}&best=1'
        rdata = await _tmx_get_json(replays_url)
        if isinstance(rdata, dict):
            rres = rdata.get('Results', [])
            if rres and isinstance(rres[0], dict):
                rid = _safe_int(rres[0].get('ReplayId'), 0)
                if rid > 0:
                    replayurl = f'{public_host}/recordgbx/{rid}'
    except Exception:
        pass

    out = {
        'authortime': _fmt_track_value(mode, t.get('AuthorTime', 0)),
        'goldtime': _fmt_track_value(mode, t.get('GoldTarget', 0)),
        'silvertime': _fmt_track_value(mode, t.get('SilverTarget', 0)),
        'bronzetime': _fmt_track_value(mode, t.get('BronzeTarget', 0)),
        'authortime_ms': _safe_int(t.get('AuthorTime'), 0),
        'goldtime_ms': _safe_int(t.get('GoldTarget'), 0),
        'silvertime_ms': _safe_int(t.get('SilverTarget'), 0),
        'bronzetime_ms': _safe_int(t.get('BronzeTarget'), 0),
        'env': env_map.get(t.get('Environment'), ''),
        'mood': mood_map.get(t.get('Mood'), ''),
        'type': type_map.get(t.get('PrimaryType'), ''),
        'style': style_map.get(t.get('Style'), ''),
        'diffic': diff_map.get(t.get('Difficulty'), ''),
        'routes': route_map.get(t.get('Routes'), ''),
        'awards': str(t.get('Awards', '') or ''),
        'section': site,
        'imageurl': f'https://{public_host}/get.aspx?action=trackscreen&id={track_id}&.jpg',
        'pageurl': f'{public_host}/trackshow/{track_id}',
        'dloadurl': f'{public_host}/trackgbx/{track_id}',
        'replayurl': replayurl,
    }
    info_cache[cache_key] = dict(out)
    return out


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
