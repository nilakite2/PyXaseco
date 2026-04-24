"""
plugin_rasp_jukebox.py — Port of plugins/plugin.rasp_jukebox.php

Jukebox system: track queuing, /y voting for TMX adds and chat votes,
/list /jukebox /autojuke /add /history /xlist commands.
"""

from __future__ import annotations
import logging
import asyncio
import json
import pathlib
import re
import tempfile
import time
import html
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, format_time, strip_colors, display_manialink, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

TMX_HOST_ALIASES = {
    'tmnf': 'tmnf.exchange',
    'tmu':  'tmuf.exchange',
    'tmo':  'original.tm-exchange.com',
    'tms':  'sunrise.tm-exchange.com',
    'tmn':  'nations.tm-exchange.com',
}

DEFAULT_TMX_HOST = TMX_HOST_ALIASES['tmnf']
TMX_DOWNLOAD_DIR = 'TMX'
TMX_SEARCH_PREFIXES = {
    'TMO': 'original',
    'TMS': 'sunrise',
    'TMN': 'nations',
    'TMU': 'united',
    'TMNF': 'tmnforever',
}

# ---------------------------------------------------------------------------
# Module-level state (exported to other plugins)
# ---------------------------------------------------------------------------
jukebox: dict = {}       # {uid: {FileName, Name, Env, Login, Nick, source, tmx, uid}}
jb_buffer: list = []     # list of UIDs (track history)
jukebox_check: str = ''  # UID of intended next track
tmxplaying = False
tmxplayed  = False

# Settings
buffersize: int = 10
feature_jukebox: bool = True
feature_tmxadd: bool = True
jukebox_in_window: bool = False
jukebox_skipleft: bool = False
jukebox_adminnoskip: bool = True
jukebox_permadd: bool = False
autosave_matchsettings: str = ''
replays_counter: int = 0
replays_total: int = 0
_challenge_info_cache: dict[str, dict] = {}


def get_jukebox() -> dict:
    """Public accessor used by plugin_rasp_nextmap."""
    return jukebox


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',          _init_jbhistory)
    aseco.register_event('onEndRace',       _rasp_endrace)
    aseco.register_event('onNewChallenge2', _rasp_newtrack)
    aseco.register_event('onPlayerManialinkPageAnswer', _event_jukebox)

    aseco.add_chat_command('list',     'Lists tracks currently on the server (see: /list help)')
    aseco.add_chat_command('jukebox',  'Sets track to be played next (see: /jukebox help)')
    aseco.add_chat_command('jb',       'Alias for /jukebox')
    aseco.add_chat_command('autojuke', 'Jukeboxes track from /list (see: /autojuke help)')
    aseco.add_chat_command('aj',       'Alias for /autojuke')
    aseco.add_chat_command('add',      'Adds a track directly from TMX (<ID> {sec})')
    aseco.add_chat_command('y',        'Votes Yes for a TMX track or chat-based vote')
    aseco.add_chat_command('history',  'Shows the 10 most recently played tracks')
    aseco.add_chat_command('xlist',    'Lists tracks on TMX (see: /xlist help)')

    aseco.register_event('onChat_list',     chat_list)
    aseco.register_event('onChat_jukebox',  chat_jukebox)
    aseco.register_event('onChat_jb',       chat_jukebox)
    aseco.register_event('onChat_autojuke', chat_autojuke)
    aseco.register_event('onChat_aj',       chat_autojuke)
    aseco.register_event('onChat_add',      chat_add)
    aseco.register_event('onChat_y',        chat_y)
    aseco.register_event('onChat_history',  chat_history)
    aseco.register_event('onChat_xlist',    chat_xlist)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rasp_msg(aseco: 'Aseco', key: str) -> str:
    try:
        from pyxaseco.plugins.plugin_rasp import _rasp
        msgs = _rasp.get('messages', {})
        items = msgs.get(key.upper(), ['{#server}> {#error}' + key])
        return items[0] if items else '{#server}> {#error}' + key
    except Exception:
        return '{#server}> {#error}' + key


async def _jb_broadcast(aseco: 'Aseco', msg: str, at_score: bool = False):
    if jukebox_in_window:
        try:
            from pyxaseco.plugins.helpers import send_window_message
            await send_window_message(aseco, msg, at_score)
            return
        except Exception:
            pass
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage', aseco.format_colors(msg))


async def _reply(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)


def _trackhist_path(aseco: 'Aseco') -> pathlib.Path:
    return aseco._base_dir / aseco.settings.trackhist_file


def _is_admin_login(aseco: 'Aseco', login: str) -> bool:
    return (
        aseco.is_master_admin_login(login) or
        aseco.is_admin_login(login) or
        aseco.is_operator_login(login)
    )


def _is_login_online(aseco: 'Aseco', login: str) -> bool:
    return any(player.login == login for player in aseco.server.players.all())


def _prepend_jukebox_track(uid: str, track: dict):
    global jukebox
    jukebox = {uid: track, **jukebox}


def _pop_first_jukebox_track() -> tuple[str, dict] | tuple[None, None]:
    global jukebox
    if not jukebox:
        return None, None
    uid = next(iter(jukebox))
    track = jukebox.pop(uid)
    return uid, track


def _matchsettings_autosave_path(aseco: 'Aseco', filename: str) -> pathlib.Path:
    trackdir = getattr(getattr(aseco, 'server', None), 'trackdir', '') or ''
    if trackdir:
        return pathlib.Path(trackdir) / 'MatchSettings' / filename
    return aseco._base_dir / 'MatchSettings' / filename


def _ensure_random_filter(matchsettings_path: pathlib.Path):
    if not matchsettings_path.exists():
        return

    content = matchsettings_path.read_text(encoding='utf-8', errors='ignore')
    if '<random_map_order>1</random_map_order>' in content:
        return

    if re.search(r'</gameinfos>', content, re.IGNORECASE):
        content = re.sub(
            r'</gameinfos>',
            '</gameinfos>\n\n\t<filter>\n\t\t<random_map_order>1</random_map_order>\n\t</filter>',
            content,
            count=1,
            flags=re.IGNORECASE,
        )
        matchsettings_path.write_text(content, encoding='utf-8')


def _load_runtime_settings():
    global buffersize, feature_jukebox, feature_tmxadd, jukebox_in_window
    global jukebox_skipleft, jukebox_adminnoskip, jukebox_permadd
    global autosave_matchsettings

    try:
        import pyxaseco.plugins.plugin_rasp as rasp_mod
    except Exception:
        return

    buffersize = int(getattr(rasp_mod, 'buffersize', buffersize) or buffersize)
    feature_jukebox = bool(getattr(rasp_mod, 'feature_jukebox', feature_jukebox))
    feature_tmxadd = bool(getattr(rasp_mod, 'feature_tmxadd', feature_tmxadd))
    jukebox_in_window = bool(getattr(rasp_mod, 'jukebox_in_window', jukebox_in_window))
    jukebox_skipleft = bool(getattr(rasp_mod, 'jukebox_skipleft', jukebox_skipleft))
    jukebox_adminnoskip = bool(getattr(rasp_mod, 'jukebox_adminnoskip', jukebox_adminnoskip))
    jukebox_permadd = bool(getattr(rasp_mod, 'jukebox_permadd', jukebox_permadd))
    autosave_matchsettings = str(
        getattr(rasp_mod, 'autosave_matchsettings', autosave_matchsettings) or ''
    )

def _parse_gbx_metadata(path: pathlib.Path) -> dict:
    """
    Parse track metadata from the GBX header XML embedded near the start of the file.
    Extracts:
      - uid
      - name
      - author
      - environment
    """
    with open(path, 'rb') as f:
        data = f.read(65536)  # first 64 KiB is enough for the header in practice

    text = data.decode('utf-8', errors='ignore')

    ident_m = re.search(
        r'<ident\b[^>]*\buid="([^"]+)"[^>]*\bname="([^"]*)"[^>]*\bauthor="([^"]*)"',
        text,
        re.IGNORECASE
    )
    desc_m = re.search(
        r'<desc\b[^>]*\benvir="([^"]*)"',
        text,
        re.IGNORECASE
    )

    uid = ident_m.group(1).strip() if ident_m else ''
    name = html.unescape(ident_m.group(2)).strip() if ident_m else ''
    author = html.unescape(ident_m.group(3)).strip() if ident_m else ''
    environment = desc_m.group(1).strip() if desc_m else ''

    return {
        'uid': uid,
        'name': name,
        'author': author,
        'environment': environment,
    }

def _sanitize_windows_filename(name: str) -> str:
    """
    Produce a dedicated-server-safe ASCII filename stem.

    Rules:
      - strip TM color codes before calling this helper
      - normalize unicode
      - non-ascii / problematic chars become '_'
      - collapse repeated underscores
      - trim trailing separators/dots/spaces
    """
    raw = str(name or '').strip()
    raw = unicodedata.normalize('NFKD', raw)

    out: list[str] = []
    for ch in raw:
        # skip combining marks created by normalization
        if unicodedata.category(ch) == 'Mn':
            continue

        o = ord(ch)

        if (
            48 <= o <= 57 or   # 0-9
            65 <= o <= 90 or   # A-Z
            97 <= o <= 122 or  # a-z
            ch in '._-()'
        ):
            out.append(ch)
        elif ch.isspace():
            out.append('_')
        else:
            out.append('_')

    safe = ''.join(out)
    safe = re.sub(r'_+', '_', safe)
    safe = re.sub(r'\.+', '.', safe)
    safe = safe.strip(' ._-')

    return safe or 'Unnamed_Track'

async def _find_server_track_by_uid_or_filename(aseco: 'Aseco', uid: str, filename: str) -> dict | None:
    """
    Find a track from the dedicated server's live challenge list by UID or filename.
    Returns the raw challenge dict from GetChallengeList, or None if not found.
    """
    try:
        tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
    except Exception as e:
        logger.debug('[TMX] _find_server_track_by_uid_or_filename GetChallengeList failed: %s', e)
        return None

    want_uid = (uid or '').strip()
    want_file = (filename or '').replace('\\', '/').strip().lower()

    for t in tracks:
        t_uid = (t.get('UId', '') or t.get('Uid', '') or '').strip()
        t_file = (t.get('FileName', '') or '').replace('\\', '/').strip().lower()

        if want_uid and t_uid == want_uid:
            return t
        if want_file and t_file == want_file:
            return t

    return None

async def choose_jukebox_next(aseco: 'Aseco') -> bool:
    return await force_jukebox_next(aseco)

async def force_jukebox_next(aseco: 'Aseco') -> bool:
    """
    Force the first jukebox entry to become the next played map.

    In this runtime, ChooseNextChallenge() with the exact live server filename
    is more reliable than SetNextChallengeList([track_struct]).
    """
    global jukebox_check

    if not jukebox:
        logger.debug('[Jukebox] force_jukebox_next: jukebox empty')
        return False

    uid, track = next(iter(jukebox.items()))
    wanted_uid = (track.get('uid') or uid or '').strip()
    wanted_filename = (track.get('FileName') or '').strip()

    if not wanted_uid and not wanted_filename:
        logger.debug('[Jukebox] force_jukebox_next: missing uid and filename')
        return False

    logger.debug(
        '[Jukebox] force_jukebox_next: uid=%s filename=%r',
        wanted_uid,
        wanted_filename
    )

    try:
        server_track = await _find_server_track_by_uid_or_filename(aseco, wanted_uid, wanted_filename)

        live_filename = wanted_filename
        if server_track:
            live_filename = (server_track.get('FileName') or live_filename or '').strip()

        if not live_filename:
            logger.warning(
                '[Jukebox] force_jukebox_next: no live filename available for uid=%s',
                wanted_uid
            )
            return False

        await aseco.client.query_ignore_result('ChooseNextChallenge', live_filename)
        jukebox_check = wanted_uid

        logger.debug(
            '[Jukebox] force_jukebox_next: ChooseNextChallenge uid=%s filename=%r',
            wanted_uid,
            live_filename
        )
        return True

    except Exception as e:
        logger.warning(
            '[Jukebox] force_jukebox_next failed for uid=%s filename=%r: %s',
            wanted_uid,
            wanted_filename,
            e
        )
        return False

def _safe_track_filename(track_name: str, track_id: int) -> str:
    """
    Build a safe TMX filename for disk + MatchSettings.
    """
    clean_name = strip_colors(track_name, for_tm=False)
    safe_name = _sanitize_windows_filename(clean_name)
    return f'{safe_name}_({track_id}).Challenge.Gbx'


def _default_tmx_section(aseco: 'Aseco') -> str:
    game = str(getattr(getattr(aseco, 'server', None), 'game', '') or '').upper()
    if game == 'TMF':
        return 'TMNF' if getattr(aseco.server, 'packmask', '') == 'Stadium' else 'TMU'
    if game in ('TMN', 'TMS', 'TMO'):
        return game
    return 'TMNF'


def _tmx_api_url(section: str, endpoint: str, **params) -> str:
    prefix = TMX_SEARCH_PREFIXES.get((section or '').upper())
    if not prefix:
        raise ValueError(f'Unsupported TMX section: {section}')

    clean = {
        key: value
        for key, value in params.items()
        if value not in (None, '', [])
    }
    query = urllib.parse.urlencode(clean, doseq=True)
    return f'https://{prefix}.tm-exchange.com/api/{endpoint}?{query}'


def _tmx_get_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'PyXaseco/TMXSearch',
            'Accept': 'application/json',
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read()
    return json.loads(data.decode('utf-8', errors='replace'))


def _extract_tmx_author_name(track: dict) -> str:
    authors = track.get('Authors', [])
    if isinstance(authors, list):
        for author in authors:
            if not isinstance(author, dict):
                continue
            user = author.get('User', {})
            if isinstance(user, dict) and user.get('Name'):
                return str(user['Name'])
            if author.get('Name'):
                return str(author['Name'])

    uploader = track.get('Uploader', {})
    if isinstance(uploader, dict) and uploader.get('Name'):
        return str(uploader['Name'])

    return '?'


def _extract_tmx_environment(track: dict) -> str:
    env = track.get('Environment')
    if isinstance(env, str) and env:
        return env

    env_map = {
        1: 'Snow',
        2: 'Desert',
        3: 'Rally',
        4: 'Island',
        5: 'Coast',
        6: 'Bay',
        7: 'Stadium',
    }
    return env_map.get(int(env or 0), '')


def _normalise_tmx_track_row(track: dict, section: str) -> dict | None:
    try:
        track_id = int(track.get('TrackId', 0) or 0)
    except Exception:
        return None

    if track_id <= 0:
        return None

    return {
        'id': track_id,
        'name': str(track.get('TrackName', '') or ''),
        'author': _extract_tmx_author_name(track),
        'environment': _extract_tmx_environment(track),
        'section': section,
    }


def _user_match_rank(name: str, query: str) -> tuple[int, int, str]:
    left = str(name or '').strip().casefold()
    right = str(query or '').strip().casefold()
    if not left:
        return (3, 9999, left)
    if left == right:
        return (0, len(left), left)
    if left.startswith(right):
        return (1, len(left), left)
    if right and right in left:
        return (2, len(left), left)
    return (3, len(left), left)


def _tmx_user_matches(name: str, query: str) -> bool:
    left = str(name or '').strip().casefold()
    right = str(query or '').strip().casefold()
    if not left or not right:
        return False
    return left.startswith(right) or right in left


def _tmx_track_matches_name(track: dict, query: str) -> bool:
    left = str(track.get('TrackName', '') or '').strip().casefold()
    right = str(query or '').strip().casefold()
    if not right:
        return True
    return bool(left) and right in left


def _tmx_track_has_author_name(track: dict, author_name: str) -> bool:
    left = _extract_tmx_author_name(track).strip().casefold()
    right = str(author_name or '').strip().casefold()
    if not right:
        return True
    return bool(left) and left == right


def _tmx_track_has_author_id(track: dict, author_id: int | None) -> bool:
    if not author_id:
        return True

    authors = track.get('Authors', [])
    if isinstance(authors, list):
        for author in authors:
            if not isinstance(author, dict):
                continue
            user = author.get('User', {})
            if isinstance(user, dict):
                try:
                    if int(user.get('UserId', 0) or 0) == int(author_id):
                        return True
                except Exception:
                    pass

    uploader = track.get('Uploader', {})
    if isinstance(uploader, dict):
        try:
            return int(uploader.get('UserId', 0) or 0) == int(author_id)
        except Exception:
            return False

    return False


async def _search_tmx_users(section: str, query: str) -> list[dict]:
    if not query:
        return []

    seen_ids: set[int] = set()
    collected: list[dict] = []

    for key in ('name', 'query', 'search'):
        for page in range(3):
            try:
                url = _tmx_api_url(
                    section,
                    'users',
                    fields='UserId,Name',
                    page=page,
                    **{key: query},
                )
                data = await asyncio.to_thread(_tmx_get_json, url)
            except Exception as e:
                logger.debug('[XList] TMX user search failed for %s via %s page %s: %s', section, key, page, e)
                break

            results = data.get('Results', []) if isinstance(data, dict) else []
            if not isinstance(results, list) or not results:
                break

            page_matches = 0
            for row in results:
                if not isinstance(row, dict):
                    continue
                if not _tmx_user_matches(row.get('Name', ''), query):
                    continue
                try:
                    user_id = int(row.get('UserId', 0) or 0)
                except Exception:
                    continue
                if user_id in seen_ids:
                    continue
                seen_ids.add(user_id)
                collected.append(row)
                page_matches += 1

            if page_matches == 0:
                break
            if not bool(data.get('More')):
                break

    collected.sort(key=lambda row: _user_match_rank(row.get('Name', ''), query))
    return collected

async def _search_tmx_tracks_api(
    section: str,
    *,
    name: str = '',
    author_name: str = '',
    author_id: int | None = None,
) -> list[dict]:
    fields = 'TrackId,TrackName,Authors[],Uploader.UserId,Uploader.Name,Environment'
    variants: list[dict] = []

    if name:
        variants.extend([
            {'name': name},
            {'trackname': name},
            {'track': name},
            {'query': name},
        ])
    elif author_id is not None:
        variants.extend([
            {'authorid': author_id},
            {'authorId': author_id},
            {'userid': author_id},
            {'userId': author_id},
        ])
    if author_name:
        variants.extend([
            {'author': author_name},
            {'authorname': author_name},
        ])

    seen_ids: set[int] = set()

    for variant in variants:
        try:
            url = _tmx_api_url(section, 'tracks', fields=fields, page=0, **variant)
            data = await asyncio.to_thread(_tmx_get_json, url)
        except Exception as e:
            logger.debug('[XList] TMX track search failed for %s via %s: %s', section, variant, e)
            continue

        results = data.get('Results', []) if isinstance(data, dict) else []
        if not isinstance(results, list) or not results:
            continue

        tracks: list[dict] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            if name and not _tmx_track_matches_name(row, name):
                continue
            if author_name and not _tmx_track_has_author_name(row, author_name):
                continue
            if author_id is not None and not _tmx_track_has_author_id(row, author_id):
                continue
            normalised = _normalise_tmx_track_row(row, section)
            if not normalised:
                continue
            if normalised['id'] in seen_ids:
                continue
            seen_ids.add(normalised['id'])
            tracks.append(normalised)

        if tracks:
            return tracks

    return []


def _legacy_tmx_url(section: str, *, recent: bool = False, name: str = '', author: str = '', page: int = 0) -> str:
    prefix = TMX_SEARCH_PREFIXES.get((section or '').upper())
    if not prefix:
        raise ValueError(f'Unsupported TMX section: {section}')

    if recent:
        return f'https://{prefix}.tm-exchange.com/apiget.aspx?action=apirecent'

    query = ['action=apisearch']
    if name:
        query.append('track=' + urllib.parse.quote(name))
    if author:
        query.append('author=' + urllib.parse.quote(author))
    query.append(f'page={int(page)}')
    return f'https://{prefix}.tm-exchange.com/apiget.aspx?' + '&'.join(query)


def _legacy_tmx_get_text(url: str) -> str | None:
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'PyXaseco/TMXSearch',
            'Accept': '*/*',
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read()
    return data.decode('utf-8', errors='replace').strip()


async def _search_tmx_tracks_legacy(section: str, *, name: str = '', author: str = '', recent: bool = False) -> list[dict]:
    section = (section or '').upper()
    max_pages = 1 if section in ('TMO', 'TMS', 'TMN') else 25
    tracks: list[dict] = []
    seen_ids: set[int] = set()

    for page in range(max_pages):
        try:
            url = _legacy_tmx_url(section, recent=recent, name=name, author=author, page=page)
            text = await asyncio.to_thread(_legacy_tmx_get_text, url)
        except Exception as e:
            logger.debug('[XList] TMX request failed for %s page %s: %s', section, page, e)
            break

        if not text:
            break
        if chr(27) in text:
            logger.debug('[XList] TMX returned undecodable data for %s page %s', section, page)
            break

        page_added = 0
        for line in text.splitlines():
            fields = line.split('\t')
            if len(fields) < 6:
                continue
            try:
                track_id = int(fields[0])
            except Exception:
                continue
            if track_id in seen_ids:
                continue
            seen_ids.add(track_id)
            tracks.append({
                'id': track_id,
                'name': fields[1],
                'author': fields[3],
                'environment': fields[5],
                'section': section,
            })
            page_added += 1

        if recent or page_added == 0:
            break

    return tracks


async def _search_tmx_tracks(section: str, *, name: str = '', author: str = '', recent: bool = False) -> list[dict]:
    section = (section or '').upper()

    # `/xlist recent` still keeps the legacy endpoint until the exact
    # TMX API order parameter is pinned down for all TM1 sections.
    if recent:
        return await _search_tmx_tracks_legacy(section, recent=True)

    if author:
        users = await _search_tmx_users(section, author)
        seen_ids: set[int] = set()
        matches: list[dict] = []

        for user in users[:10]:
            user_name = str(user.get('Name', '') or '').strip()
            try:
                user_id = int(user.get('UserId', 0) or 0)
            except Exception:
                user_id = 0

            user_tracks = await _search_tmx_tracks_api(
                section,
                author_name=user_name,
                author_id=user_id or None,
            )
            for row in user_tracks:
                if row['id'] in seen_ids:
                    continue
                seen_ids.add(row['id'])
                matches.append(row)

        if not matches:
            matches = await _search_tmx_tracks_api(section, author_name=author)
        if matches:
            return matches

        return await _search_tmx_tracks_legacy(section, author=author)

    if name:
        matches = await _search_tmx_tracks_api(section, name=name)
        if matches:
            return matches

    return await _search_tmx_tracks_legacy(section, name=name)


def parse_tmx_reference(ref: str, source: str = '') -> tuple[str, int]:
    """
    Supports:
      - plain numeric ID, optional source alias
      - full TMX page URL
      - full /trackgbx/<id> URL
    """
    ref = (ref or '').strip()
    source = (source or '').strip().lower()

    if not ref:
        raise ValueError('Missing TMX track reference')

    if ref.isdigit():
        if source:
            if source not in TMX_HOST_ALIASES:
                raise ValueError(f'Unsupported TMX source: {source}')
            return TMX_HOST_ALIASES[source], int(ref)
        return DEFAULT_TMX_HOST, int(ref)

    parsed = urllib.parse.urlparse(ref)
    host = parsed.netloc.lower()
    if host not in TMX_HOST_ALIASES.values():
        raise ValueError(f'Unsupported TMX host: {host}')

    path = parsed.path.strip('/')

    m = re.search(r'(?:^|/)trackshow/(\d+)(?:/|$)', path, re.IGNORECASE)
    if m:
        return host, int(m.group(1))

    m = re.search(r'(?:^|/)trackgbx/(\d+)(?:/|$)', path, re.IGNORECASE)
    if m:
        return host, int(m.group(1))

    m = re.search(r'(\d+)(?:/)?$', path)
    if m:
        return host, int(m.group(1))

    raise ValueError(f'Could not extract track id from: {ref}')


def _stream_download_to_file(url: str, dest: pathlib.Path):
    """
    Stream download to disk with no artificial size limit.
    Uses a temporary file and atomic replace.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix='tmx_', suffix='.part', dir=str(dest.parent))

    try:
        with open(fd, 'wb', closefd=True) as out:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'PyXaseco/1.0',
                    'Accept': '*/*',
                }
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                while True:
                    chunk = resp.read(1024 * 1024)  # 1 MiB chunks, no total size cap
                    if not chunk:
                        break
                    out.write(chunk)

        pathlib.Path(tmp_name).replace(dest)

    except Exception:
        try:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise


async def download_tmx_track(ref: str, tracks_root: pathlib.Path, source: str = '') -> tuple[pathlib.Path, str, str, int, dict]:
    """
    Download a TMX-family track GBX.
    Returns:
      (absolute_path, relative_insert_path, host, track_id, metadata)
    """
    host, track_id = parse_tmx_reference(ref, source)

    temp_rel = pathlib.Path(TMX_DOWNLOAD_DIR) / f'_tmp_{track_id}.Challenge.Gbx'
    temp_abs = tracks_root / temp_rel
    url = f'https://{host}/trackgbx/{track_id}'

    await asyncio.to_thread(_stream_download_to_file, url, temp_abs)

    metadata = await asyncio.to_thread(_parse_gbx_metadata, temp_abs)
    track_name = metadata.get('name') or f'Track {track_id}'

    final_rel = pathlib.Path(TMX_DOWNLOAD_DIR) / _safe_track_filename(track_name, track_id)
    final_abs = tracks_root / final_rel

    final_abs.parent.mkdir(parents=True, exist_ok=True)
    if final_abs.exists():
        final_abs.unlink()
    temp_abs.replace(final_abs)

    return final_abs, str(final_rel).replace('\\', '/'), host, track_id, metadata


async def admin_add_tmx_track(
    aseco: 'Aseco',
    ref: str,
    login: str = '',
    source: str = '',
    use_add_challenge: bool = False
) -> tuple[bool, str]:
    tracks_root = pathlib.Path(
        getattr(
            aseco.settings,
            'tracks_root',
            aseco._base_dir.parent / 'GameData' / 'Tracks' / 'Challenges'
        )
    ).resolve()

    try:
        abs_path, rel_insert, host, track_id, metadata = await download_tmx_track(ref, tracks_root, source)

        uid = metadata.get('uid', '').strip()
        if not uid:
            try:
                abs_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False, 'Could not read map UID from downloaded GBX.'

        # Reject duplicate by live server list
        try:
            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            for t in track_list:
                t_uid = (t.get('UId', '') or t.get('Uid', '') or '').strip()
                if t_uid == uid:
                    try:
                        abs_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return False, 'This map is already on the server.'
        except Exception as e:
            logger.warning('[TMX] Could not check existing server track list for UID duplicate: %s', e)

        server_track = None

        # Insert into dedicated server
        try:
            method = 'AddChallenge' if use_add_challenge else 'InsertChallenge'
            await aseco.client.query_ignore_result(method, rel_insert)
            await aseco.release_event('onTracklistChanged', ['add', rel_insert])
        except Exception as e:
            try:
                abs_path.unlink(missing_ok=True)
            except Exception:
                pass
            logger.warning('[TMX] %s failed for %s: %s', method, rel_insert, e)
            raise

        # Ensure MatchSettings.txt contains the track
        try:
            await asyncio.to_thread(
                _ensure_matchsettings_entry,
                _matchsettings_path(aseco),
                rel_insert,
                uid
            )
        except Exception as e:
            logger.warning('[TMX] Could not update MatchSettings.txt immediately: %s', e)

        # Reload dedicated tracklist from MatchSettings
        try:
            await aseco.client.query_ignore_result(
                'LoadMatchSettings',
                'MatchSettings/MatchSettings.txt'
            )
        except Exception as e:
            logger.warning('[TMX] LoadMatchSettings after add failed: %s', e)

        # Now wait for the track to become visible in live GetChallengeList
        for _ in range(15):
            server_track = await _find_server_track_by_uid_or_filename(aseco, uid, rel_insert)
            if server_track:
                break
            await asyncio.sleep(0.2)

        if server_track:
            logger.debug(
                '[TMX] Live challenge list now contains added track: uid=%s file=%r',
                uid,
                server_track.get('FileName', '')
            )
        else:
            logger.warning(
                '[TMX] Track added on disk/MatchSettings but still not visible in live GetChallengeList: uid=%s file=%s',
                uid,
                rel_insert
            )

        # Sync LocalDB challenge row and capture the exact live filename/name/author/env
        server_filename = rel_insert

        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
            pool = await get_pool()
            if pool:
                name = metadata.get('name', '')
                author = metadata.get('author', '')
                env = metadata.get('environment', '')

                if server_track:
                    t_uid = (server_track.get('UId', '') or server_track.get('Uid', '') or '').strip()
                    t_file = server_track.get('FileName', '')
                    uid = t_uid or uid
                    server_filename = t_file or server_filename
                    name = server_track.get('Name', name)
                    author = server_track.get('Author', author)
                    env = server_track.get('Environnement', env)

                if uid:
                    async with pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                'INSERT INTO challenges (Uid, Name, Author, Environment) '
                                'VALUES (%s, %s, %s, %s) '
                                'ON DUPLICATE KEY UPDATE Name=VALUES(Name), Author=VALUES(Author), Environment=VALUES(Environment)',
                                (uid, name, author, env)
                            )
        except Exception as e:
            logger.warning('[TMX] Inserted track but could not sync LocalDB challenge row: %s', e)

        raw_name = metadata.get('name', f'Track {track_id}')
        display_name = strip_colors(raw_name, for_tm=False)

        # /admin add: auto-queue newly added map
        if use_add_challenge:
            try:
                if not server_track:
                    logger.warning(
                        '[TMX] Track added on disk but not visible yet in live GetChallengeList: uid=%s file=%s',
                        uid, rel_insert
                    )

                live_filename = server_filename
                if server_track:
                    live_filename = server_track.get('FileName', live_filename) or live_filename

                jukebox[uid] = {
                    'FileName': live_filename,
                    'Name': raw_name,
                    'Env': metadata.get('environment', ''),
                    'Login': login,
                    'Nick': '',
                    'source': 'TMX',
                    'tmx': True,
                    'uid': uid,
                }
                await aseco.release_event('onJukeboxChanged', ['add', jukebox[uid]])
                logger.debug(
                    '[TMX] Admin add: auto-jukeboxed %s uid=%s server_filename=%s',
                    rel_insert,
                    uid,
                    live_filename
                )
            except Exception as _je:
                logger.debug('[TMX] Admin add jukebox failed: %s', _je)

        return True, display_name

    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}'
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        logger.warning('[TMX] Could not add track %s: %s', ref, e)
        return False, str(e)

def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;')
    )

def _matchsettings_path(aseco: 'Aseco') -> pathlib.Path:
    return (
        aseco._base_dir.parent
        / 'GameData'
        / 'Tracks'
        / 'MatchSettings'
        / 'MatchSettings.txt'
    )


def _challenge_file_value(rel_insert: str) -> str:
    rel_insert = (rel_insert or '').replace('/', '\\').lstrip('\\')
    if rel_insert.lower().startswith('challenges\\'):
        return rel_insert
    return f'Challenges\\{rel_insert}'


def _remove_matchsettings_entry_by_uid(matchsettings_path: pathlib.Path, uid: str):
    """
    Remove the single <challenge> block whose <ident> matches *uid* exactly.

    Previously used re.DOTALL regex which allowed <file>.*?</file> to span
    across </challenge> tag boundaries, causing the entry BEFORE the target
    to be consumed together with the target entry (two removals for one call).
    Replaced with xml.etree.ElementTree parsing which is boundary-safe.
    """
    if not matchsettings_path.exists() or not uid:
        return

    import xml.etree.ElementTree as _ET

    content = matchsettings_path.read_text(encoding='utf-8', errors='ignore')

    try:
        root = _ET.fromstring(content.encode('utf-8'))
    except _ET.ParseError:
        # Malformed XML — fall back to a safe single-line regex that cannot
        # cross <challenge> boundaries (no re.DOTALL, [^<]* instead of .*).
        pattern = re.compile(
            r'[ \t]*<challenge>[ \t]*\r?\n'
            r'[ \t]*<file>[^<]*</file>[ \t]*\r?\n'
            rf'[ \t]*<ident>[ \t]*{re.escape(uid)}[ \t]*</ident>[ \t]*\r?\n'
            r'[ \t]*</challenge>[ \t]*(\r?\n)?',
            re.IGNORECASE
        )
        new_content = re.sub(pattern, '', content)
        if new_content != content:
            matchsettings_path.write_text(new_content, encoding='utf-8')
        return

    target_uid = uid.strip().lower()
    removed = False
    for ch in list(root.findall('challenge')):
        ident_el = ch.find('ident')
        if ident_el is not None and (ident_el.text or '').strip().lower() == target_uid:
            root.remove(ch)
            removed = True

    if not removed:
        return

    _ET.indent(root, space='\t')
    xml_body = _ET.tostring(root, encoding='unicode')
    new_content = '<?xml version="1.0" encoding="utf-8" ?>\n' + xml_body + '\n'
    matchsettings_path.write_text(new_content, encoding='utf-8')


def _ensure_matchsettings_entry(matchsettings_path: pathlib.Path, rel_insert: str, uid: str):
    matchsettings_path.parent.mkdir(parents=True, exist_ok=True)
    file_value = _challenge_file_value(rel_insert)

    if not matchsettings_path.exists():
        content = (
            '<?xml version="1.0" encoding="utf-8" ?>\n'
            '<playlist>\n'
            '\t<challenge>\n'
            f'\t\t<file>{_xml_escape(file_value)}</file>\n'
            f'\t\t<ident>{_xml_escape(uid)}</ident>\n'
            '\t</challenge>\n'
            '</playlist>\n'
        )
        matchsettings_path.write_text(content, encoding='utf-8')
        return

    content = matchsettings_path.read_text(encoding='utf-8', errors='ignore')

    if uid and re.search(rf'<ident>\s*{re.escape(uid)}\s*</ident>', content, re.IGNORECASE):
        return

    if re.search(rf'<file>\s*{re.escape(file_value)}\s*</file>', content, re.IGNORECASE):
        return

    block = (
        '\t<challenge>\n'
        f'\t\t<file>{_xml_escape(file_value)}</file>\n'
        f'\t\t<ident>{_xml_escape(uid)}</ident>\n'
        '\t</challenge>\n'
    )

    if re.search(r'</playlist>', content, re.IGNORECASE):
        content = re.sub(
            r'</playlist>',
            lambda _m: block + '</playlist>',
            content,
            count=1,
            flags=re.IGNORECASE
        )
    else:
        if not content.endswith('\n'):
            content += '\n'
        content += block + '</playlist>\n'

    matchsettings_path.write_text(content, encoding='utf-8')

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def _init_jbhistory(aseco: 'Aseco', _data):
    global jb_buffer, buffersize
    _load_runtime_settings()
    jb_buffer.clear()
    try:
        hist_file = _trackhist_path(aseco)
        if hist_file.exists():
            lines = hist_file.read_text(encoding='utf-8', errors='ignore').splitlines()
            jb_buffer.extend(l.strip() for l in lines if l.strip())
            # keep only most recent buffersize entries, minus current (last)
            jb_buffer[:] = jb_buffer[-buffersize:]
            if jb_buffer:
                jb_buffer.pop()  # rasp_newtrack will add it back
    except Exception as exc:
        logger.debug('[Jukebox] Could not restore track history: %s', exc)


async def _rasp_endrace(aseco: 'Aseco', _data):
    global jukebox_check, tmxplaying, replays_counter, replays_total
    from pyxaseco.plugins.plugin_rasp_votes import tmxadd

    if aseco.server.isrelay:
        return

    # cancel any pending TMX vote
    if tmxadd:
        aseco.console('Vote by {1} to add {2} reset!',
                      tmxadd.get('login', '?'),
                      strip_colors(tmxadd.get('name', '?')))
        msg = _get_rasp_msg(aseco, 'JUKEBOX_CANCEL')
        await _jb_broadcast(aseco, msg, True)
        tmxadd.clear()
        try:
            from pyxaseco.plugins.plugin_rasp_votes import _vote_panels_off
            await _vote_panels_off(aseco)
        except Exception:
            pass

    jukebox_check = ''

    if jukebox:
        next_uid = None
        next_track = None

        if jukebox_skipleft:
            while jukebox:
                cand_uid, cand_track = _pop_first_jukebox_track()
                if not cand_uid or not cand_track:
                    break

                requester = cand_track.get('Login', '')
                if _is_login_online(aseco, requester) or (jukebox_adminnoskip and _is_admin_login(aseco, requester)):
                    _prepend_jukebox_track(cand_uid, cand_track)
                    next_uid = cand_uid
                    next_track = cand_track
                    break

                aseco.console_text(
                    '{RASP Jukebox} Skipping Next Challenge {1} because requester {2} left',
                    strip_colors(cand_track.get('Name', '')),
                    strip_colors(cand_track.get('Nick', '')),
                )
                skip_msg = format_text(
                    _get_rasp_msg(aseco, 'JUKEBOX_SKIPLEFT'),
                    strip_colors(cand_track.get('Name', '')),
                    strip_colors(cand_track.get('Nick', '')),
                )
                await _jb_broadcast(aseco, skip_msg, True)
                await aseco.release_event('onJukeboxChanged', ['skip', cand_track])
        else:
            next_uid, next_track = _pop_first_jukebox_track()
            if next_uid and next_track:
                _prepend_jukebox_track(next_uid, next_track)

        if not next_uid or not next_track:
            return

        jukebox_check = next_uid

        if next_track.get('tmx'):
            try:
                live_track = await _find_server_track_by_uid_or_filename(
                    aseco,
                    next_track.get('uid', next_uid),
                    next_track.get('FileName', ''),
                )
                if not live_track:
                    await aseco.client.query_ignore_result('AddChallenge', next_track.get('FileName', ''))
                    await aseco.release_event('onTracklistChanged', ['juke', next_track.get('FileName', '')])
            except Exception as exc:
                logger.warning('[Jukebox] Could not AddChallenge for %s: %s', next_track.get('FileName', ''), exc)
                return

        if not await force_jukebox_next(aseco):
            return

        game = aseco.server.get_game()
        is_tmu_env = (game == 'TMF' and getattr(aseco.server, 'packmask', 'Stadium') != 'Stadium')
        stripped_name = strip_colors(next_track.get('Name', ''))
        stripped_nick = strip_colors(next_track.get('Nick', ''))

        if is_tmu_env:
            if next_track.get('tmx'):
                logmsg = (
                    f'{{RASP Jukebox}} Setting Next Challenge to [{next_track.get("Env", "")}] '
                    f'{stripped_name}, file downloaded from {next_track.get("source", "")}'
                )
                tmxplaying = next_track.get('FileName', '')
            else:
                logmsg = (
                    f'{{RASP Jukebox}} Setting Next Challenge to [{next_track.get("Env", "")}] '
                    f'{stripped_name}, requested by {stripped_nick}'
                )
            message = format_text(
                _get_rasp_msg(aseco, 'JUKEBOX_NEXTENV'),
                next_track.get('Env', ''),
                stripped_name,
                stripped_nick,
            )
        else:
            if next_track.get('tmx'):
                logmsg = (
                    f'{{RASP Jukebox}} Setting Next Challenge to {stripped_name}, '
                    f'file downloaded from {next_track.get("source", "")}'
                )
                tmxplaying = next_track.get('FileName', '')
            else:
                logmsg = (
                    f'{{RASP Jukebox}} Setting Next Challenge to {stripped_name}, '
                    f'requested by {stripped_nick}'
                )
            message = format_text(
                _get_rasp_msg(aseco, 'JUKEBOX_NEXT'),
                stripped_name,
                stripped_nick,
            )

        aseco.console_text(logmsg)
        await _jb_broadcast(aseco, message, True)
    else:
        replays_counter = 0
        replays_total = 0

    if autosave_matchsettings:
        try:
            await aseco.client.query_ignore_result(
                'SaveMatchSettings',
                f'MatchSettings/{autosave_matchsettings}',
            )
            if aseco.settings.writetracklist_random:
                await asyncio.to_thread(
                    _ensure_random_filter,
                    _matchsettings_autosave_path(aseco, autosave_matchsettings),
                )
        except Exception as exc:
            logger.warning('[Jukebox] SaveMatchSettings failed: %s', exc)


async def _rasp_newtrack(aseco: 'Aseco', data):
    global jukebox, jb_buffer, jukebox_check, tmxplaying, tmxplayed
    global replays_counter, replays_total

    if aseco.server.isrelay:
        return

    uid = data.uid if hasattr(data, 'uid') else getattr(data, 'uid', '')

    # Update history buffer
    if jb_buffer:
        prev = jb_buffer[-1]
        if prev != uid:
            pass  # keep it
        else:
            jb_buffer.pop()

    if len(jb_buffer) >= buffersize:
        jb_buffer.pop(0)
    jb_buffer.append(uid)

    # Write history
    try:
        hist_file = _trackhist_path(aseco)
        hist_file.parent.mkdir(parents=True, exist_ok=True)
        hist_file.write_text('\n'.join(jb_buffer), encoding='utf-8')
    except Exception as exc:
        logger.debug('[Jukebox] Could not persist track history: %s', exc)

    # Process jukebox
    if jukebox:
        if uid in jukebox:
            play = jukebox[uid]
            if play.get('source') == 'Replay':
                replays_counter += 1
            else:
                replays_counter = 0
            if str(play.get('source', '')).endswith('Replay'):
                replays_total += 1
            else:
                replays_total = 0
            del jukebox[uid]
            await aseco.release_event('onJukeboxChanged', ['play', play])
        elif jukebox_check and jukebox_check in jukebox:
            stuck = jukebox[jukebox_check]
            del jukebox[jukebox_check]
            await aseco.release_event('onJukeboxChanged', ['drop', stuck])

    # Remove previous TMX track
    if tmxplayed:
        if not jukebox_permadd:
            try:
                await aseco.client.query_ignore_result('RemoveChallenge', tmxplayed)
                await aseco.release_event('onTracklistChanged', ['unjuke', tmxplayed])
            except Exception:
                pass
        tmxplayed = False

    if tmxplaying:
        tmxplayed = tmxplaying
        tmxplaying = False


# ---------------------------------------------------------------------------
# /y — vote yes
# ---------------------------------------------------------------------------

async def chat_y(aseco: 'Aseco', command: dict):
    global jukebox, plrvotes_ref

    from pyxaseco.plugins.plugin_rasp_votes import chatvote, tmxadd, plrvotes
    from pyxaseco.plugins.plugin_rasp_votes import allow_spec_voting

    player = command['author']
    login = player.login

    # Use spectatorstatus % 10 for canonical spectator detection instead of isspectator.
    _raw_ss = getattr(player, 'spectatorstatus', None)
    _player_is_spec = ((int(_raw_ss) % 10) != 0) if _raw_ss is not None else bool(player.isspectator)
    if _player_is_spec and not aseco.is_any_admin(player) and not allow_spec_voting:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_SPECTATORS'))
        return

    if login in plrvotes:
        await _reply(aseco, login, '{#server}> {#error}You have already voted!')
        return

    # TMX add vote
    if tmxadd and tmxadd.get('votes', -1) >= 0:
        votes_needed = tmxadd['votes'] - 1
        if votes_needed > 0:
            tmxadd['votes'] = votes_needed
            msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_Y'),
                              votes_needed,
                              '' if votes_needed == 1 else 's',
                              strip_colors(tmxadd.get('name', '')))
            await _jb_broadcast(aseco, msg)
            plrvotes.append(login)
        else:
            # Pass — add to jukebox
            uid = tmxadd['uid']
            jukebox[uid] = {
                'FileName': tmxadd.get('filename', ''),
                'Name':     tmxadd.get('name', ''),
                'Env':      tmxadd.get('environment', ''),
                'Login':    tmxadd.get('login', ''),
                'Nick':     tmxadd.get('nick', ''),
                'source':   tmxadd.get('source', 'TMX'),
                'tmx':      True,
                'uid':      uid,
            }
            msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_PASS'),
                              strip_colors(tmxadd.get('name', '')))
            await _jb_broadcast(aseco, msg)
            tmxadd.clear()
            await aseco.release_event('onJukeboxChanged', ['add', jukebox[uid]])

    # Chat vote
    elif chatvote and chatvote.get('votes', -1) >= 0:
        votes_needed = chatvote['votes'] - 1
        if votes_needed > 0:
            chatvote['votes'] = votes_needed
            msg = format_text(_get_rasp_msg(aseco, 'VOTE_Y'),
                              votes_needed,
                              '' if votes_needed == 1 else 's',
                              chatvote.get('desc', ''))
            from pyxaseco.plugins.plugin_rasp_votes import vote_in_window
            if vote_in_window:
                await _jb_broadcast(aseco, msg)
            else:
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessage', aseco.format_colors(msg))
            plrvotes.append(login)
        else:
            # Pass — execute vote action
            msg = format_text(_get_rasp_msg(aseco, 'VOTE_PASS'), chatvote.get('desc', ''))
            from pyxaseco.plugins.plugin_rasp_votes import vote_in_window
            if vote_in_window:
                await _jb_broadcast(aseco, msg)
            else:
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessage', aseco.format_colors(msg))

            vtype = chatvote.get('type', -1)
            vlogin = chatvote.get('login', '')

            if vtype == 0:  # endround
                await aseco.client.query_ignore_result('ForceEndRound')
                aseco.console('Vote by {1} forced round end!', vlogin)

            elif vtype == 1:  # ladder
                from pyxaseco.plugins.plugin_rasp_votes import ladder_fast_restart
                uid = aseco.server.challenge.uid
                if ladder_fast_restart:
                    await aseco.client.query_ignore_result('ChallengeRestart')
                else:
                    # prepend to jukebox and skip
                    rev = dict(reversed(list(jukebox.items())))
                    rev[uid] = {
                        'FileName': aseco.server.challenge.filename,
                        'Name':     aseco.server.challenge.name,
                        'Env':      aseco.server.challenge.environment,
                        'Login':    vlogin,
                        'Nick':     chatvote.get('nick', ''),
                        'source':   'Ladder',
                        'tmx':      False,
                        'uid':      uid,
                    }
                    jukebox.clear()
                    jukebox.update(dict(reversed(list(rev.items()))))
                    await aseco.release_event('onJukeboxChanged', ['restart', jukebox[uid]])
                    await aseco.client.query_ignore_result('NextChallenge')
                aseco.console('Vote by {1} restarted track for ladder!', vlogin)

            elif vtype == 2:  # replay
                uid = aseco.server.challenge.uid
                rev = dict(reversed(list(jukebox.items())))
                rev[uid] = {
                    'FileName': aseco.server.challenge.filename,
                    'Name':     aseco.server.challenge.name,
                    'Env':      aseco.server.challenge.environment,
                    'Login':    vlogin,
                    'Nick':     chatvote.get('nick', ''),
                    'source':   'Replay',
                    'tmx':      False,
                    'uid':      uid,
                }
                jukebox.clear()
                jukebox.update(dict(reversed(list(rev.items()))))
                await aseco.release_event('onJukeboxChanged', ['replay', jukebox[uid]])
                aseco.console('Vote by {1} replays track after finish!', vlogin)

            elif vtype == 3:  # skip
                await force_jukebox_next(aseco)
                await aseco.client.query_ignore_result('NextChallenge')
                aseco.console('Vote by {1} skips this track!', vlogin)

            elif vtype == 4:  # kick
                target = chatvote.get('target', '')
                try:
                    await aseco.client.query_ignore_result('Kick', target)
                    aseco.console('Vote by {1} kicked player {2}!', vlogin, target)
                except Exception as e:
                    logger.warning('[Votes] Kick failed: %s', e)

            elif vtype == 6:  # ignore
                target = chatvote.get('target', '')
                try:
                    await aseco.client.query_ignore_result('Ignore', target)
                    if target not in aseco.server.mutelist:
                        aseco.server.mutelist.append(target)
                    aseco.console('Vote by {1} ignored player {2}!', vlogin, target)
                except Exception as e:
                    logger.warning('[Votes] Ignore failed: %s', e)

            chatvote.clear()
    else:
        await _reply(aseco, login, '{#server}> {#error}There is no vote in progress!')


# ---------------------------------------------------------------------------
# /list
# ---------------------------------------------------------------------------

async def chat_list(aseco: 'Aseco', command: dict):
    player = command['author']
    login  = player.login
    param  = (command.get('params') or '').strip()
    params = param.split() if param else ['']

    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await _reply(aseco, login, msg)
        return

    if params[0] == 'help':
        header = '{#black}/list$g will show tracks in rotation on the server:'
        data = [
            ['...', '{#black}help',           'Displays this help information'],
            ['...', '{#black}nofinish',        "Shows tracks you haven't completed"],
            ['...', '{#black}norank',          "Shows tracks you don't have a rank on"],
            ['...', '{#black}nogold',          "Shows tracks you didn't beat gold time on"],
            ['...', '{#black}noauthor',        "Shows tracks you didn't beat author time on"],
            ['...', '{#black}norecent',        "Shows tracks you didn't play recently"],
            ['...', '{#black}best$g/{#black}worst',
                                               'Shows tracks with your best/worst records'],
            ['...', '{#black}longest$g/{#black}shortest',
                                               'Shows the longest/shortest tracks'],
            ['...', '{#black}newest$g/{#black}oldest #',
                                               'Shows newest/oldest # tracks (def: 50)'],
            ['...', '{#black}xxx',             'Where xxx is part of a track or author name'],
            [],
            ['Pick an Id number from the list, and use {#black}/jukebox #'],
        ]
        display_manialink(aseco, login, header,
                          ['Icons64x64_1', 'TrackInfo', -0.01],
                          data, [1.1, 0.05, 0.3, 0.75], 'OK')
        return

    # -----------------------------------------------------------------------
    # Dispatch to filter functions
    # -----------------------------------------------------------------------
    p0 = params[0].lower()

    if p0 == 'best':
        try:
            from pyxaseco.plugins.chat_records2 import _disp_recs as disp_recs
            await disp_recs(aseco, {'author': player, 'params': ''}, best=True)
        except Exception:
            await _reply(aseco, login, '{#server}> {#error}Record list unavailable.')
        return

    if p0 == 'worst':
        try:
            from pyxaseco.plugins.chat_records2 import _disp_recs as disp_recs
            await disp_recs(aseco, {'author': player, 'params': ''}, best=False)
        except Exception:
            await _reply(aseco, login, '{#server}> {#error}Record list unavailable.')
        return

    if p0 in ('nofinish', 'norank', 'nogold', 'noauthor', 'norecent'):
        try:
            if p0 == 'nofinish':
                await _get_challenges_no_finish(aseco, player)
            elif p0 == 'norank':
                await _get_challenges_no_rank(aseco, player)
            elif p0 == 'nogold':
                await _get_challenges_no_target(aseco, player, author=False)
            elif p0 == 'noauthor':
                await _get_challenges_no_target(aseco, player, author=True)
            else:
                await _get_challenges_no_recent(aseco, player)
        except Exception as exc:
            logger.debug('[List] %s filter failed: %s', p0, exc)
            await _reply(aseco, login, '{#server}> {#error}Filter unavailable.')
        _show_or_error(aseco, player, login)
        return

    if p0 in ('longest', 'shortest'):
        await _get_challenges_by_length(aseco, player, shortest=(p0 == 'shortest'))
        _show_or_error(aseco, player, login)
        return

    if p0 in ('newest', 'oldest'):
        count = 50
        if len(params) >= 2 and params[1].isdigit():
            count = max(1, int(params[1]))
        await _get_challenges_by_add(aseco, player, newest=(p0 == 'newest'), count=count)
        _show_or_error(aseco, player, login)
        return

    # Default: search by name/author or wildcard
    wildcard = param if (param and p0 not in ('', '*')) else '*'
    await _get_all_challenges(aseco, player, wildcard=wildcard)

    if not getattr(player, 'tracklist', None):
        await _reply(aseco, login, '{#server}> {#error}No tracks found, try again!')
        return
    display_manialink_multi(aseco, player)


def _show_or_error(aseco, player, login):
    """After a filter call: show results or report no tracks. Non-async helper."""
    import asyncio
    if not getattr(player, 'tracklist', None):
        asyncio.ensure_future(
            aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                aseco.format_colors('{#server}> {#error}No tracks found, try again!'),
                player.login
            )
        )
    else:
        display_manialink_multi(aseco, player)


async def _get_best_local_times(aseco: 'Aseco') -> dict:
    """Return {uid: best_score_ms} for every track from the local records table."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return {}
        is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == 4
        # For Stunts highest score wins; for all others lowest time wins
        agg = 'MAX' if is_stnt else 'MIN'
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f'SELECT c.Uid, {agg}(r.Score) AS BestScore '
                    f'FROM records r '
                    f'LEFT JOIN challenges c ON (r.ChallengeId = c.Id) '
                    f'WHERE c.Uid IS NOT NULL '
                    f'GROUP BY c.Uid'
                )
                rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows if row[0] and row[1] is not None}
    except Exception as e:
        logger.debug('[List] _get_best_local_times: %s', e)
        return {}


async def _get_player_track_stats(aseco: 'Aseco', player) -> dict:
    """Return per-track best score and most recent play date for one player."""
    pid = getattr(player, 'id', 0)
    if not pid:
        return {}
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return {}
        is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == 4
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT c.Uid, t.score, t.date '
                    'FROM rs_times t '
                    'LEFT JOIN challenges c ON (t.challengeID = c.Id) '
                    'WHERE t.playerID = %s AND c.Uid IS NOT NULL',
                    (pid,)
                )
                rows = await cur.fetchall()
        stats = {}
        for uid, score, played_at in rows:
            if not uid:
                continue
            data = stats.setdefault(uid, {'best': score, 'last_date': int(played_at or 0)})
            if is_stnt:
                if score > data['best']:
                    data['best'] = score
            else:
                if score < data['best']:
                    data['best'] = score
            if played_at and int(played_at) > data['last_date']:
                data['last_date'] = int(played_at)
        return stats
    except Exception as e:
        logger.debug('[List] _get_player_track_stats: %s', e)
        return {}


def _set_paginated_msgs(player, header: str, widths: list, columns: list, rows: list,
                        icon: list | None = None, page_size: int = 15):
    """Populate player.msgs with a header block and paginated table pages."""
    player.msgs = [[1, header, widths, icon or ['Icons128x128_1', 'NewTrack', 0.02]]]
    page = [columns]
    for row in rows:
        page.append(row)
        if len(page) - 1 >= page_size:
            player.msgs.append(page)
            page = [columns]
    if len(page) > 1:
        player.msgs.append(page)


def _append_tracklist_entry(player, row: dict, uid: str):
    player.tracklist.append({
        'name': row.get('Name', ''),
        'author': row.get('Author', ''),
        'environment': row.get('Environnement', ''),
        'filename': row.get('FileName', ''),
        'uid': uid,
    })


def _format_list_author(author: str, tid: int, clickable: bool):
    if clickable and tid <= 1900:
        return [author, -(100 + tid)]
    return author


def _format_diff(diff: int, is_stnt: bool) -> str:
    if is_stnt:
        return f'-{diff}'
    sec = diff // 1000
    hun = (diff % 1000) // 10
    return f'+{sec}.{hun:02d}'


async def _get_track_target_value(aseco: 'Aseco', row: dict, uid: str, *, author: bool, is_stnt: bool) -> int:
    """Resolve author/gold target from server data, then current challenge, then GetChallengeInfo."""
    primary_key = 'AuthorScore' if (author and is_stnt) else 'AuthorTime' if author else 'GoldTime'

    target = int(row.get(primary_key, 0) or 0)
    if target > 0:
        return target

    cur = getattr(aseco.server, 'challenge', None)
    if cur and getattr(cur, 'uid', '') == uid:
        cur_value = getattr(cur, 'authortime' if author else 'goldtime', 0) or 0
        if int(cur_value) > 0:
            return int(cur_value)

    filename = str(row.get('FileName', '') or '').strip()
    if not filename:
        return 0

    try:
        info = _challenge_info_cache.get(filename)
        if info is None:
            info = await aseco.client.query('GetChallengeInfo', filename) or {}
            _challenge_info_cache[filename] = dict(info) if isinstance(info, dict) else {}
        if info:
            return int(info.get(primary_key, 0) or 0)
    except Exception as e:
        logger.debug('[List] GetChallengeInfo target fallback failed for %s: %s', uid, e)

    return 0


async def _get_challenges_no_finish(aseco: 'Aseco', player):
    """Tracks in the current rotation the player has never completed."""
    player.tracklist = []
    tracks = await _get_challenges_cache(aseco)
    finished = set((await _get_player_track_stats(aseco, player)).keys())
    clickable = getattr(aseco.settings, 'clickable_lists', False)
    rows = []
    tid = 1
    for row in tracks:
        uid = row.get('UId', '')
        if not uid or uid in finished:
            continue
        _append_tracklist_entry(player, row, uid)
        rows.append([
            f'{tid:03d}.',
            '-- ',
            _fmt_track_name(row.get('Name', ''), uid, tid, clickable),
            _format_list_author(row.get('Author', ''), tid, clickable),
        ])
        tid += 1
    _set_paginated_msgs(
        player,
        "Tracks You Haven't Completed:",
        [1.08, 0.12, 0.1, 0.58, 0.28],
        ['Id', 'Rec', 'Name', 'Author'],
        rows,
    )


async def _get_challenges_no_rank(aseco: 'Aseco', player):
    """Tracks the player finished but does not hold a ranked local record on."""
    player.tracklist = []
    tracks = await _get_challenges_cache(aseco)
    track_by_uid = {row.get('UId', ''): row for row in tracks}
    stats = await _get_player_track_stats(aseco, player)
    rec_ranks = await _get_player_rec_ranks(aseco, player)
    maxrecs = _get_maxrecs(aseco)
    clickable = getattr(aseco.settings, 'clickable_lists', False)
    rows = []
    tid = 1
    for row in tracks:
        uid = row.get('UId', '')
        if not uid or uid not in stats:
            continue
        rank = rec_ranks.get(uid, 0)
        if 1 <= rank <= maxrecs:
            continue
        src = track_by_uid.get(uid, row)
        _append_tracklist_entry(player, src, uid)
        rows.append([
            f'{tid:03d}.',
            '-- ',
            _fmt_track_name(src.get('Name', ''), uid, tid, clickable),
            _format_list_author(src.get('Author', ''), tid, clickable),
        ])
        tid += 1
    _set_paginated_msgs(
        player,
        "Tracks You Have No Rank On:",
        [1.08, 0.12, 0.1, 0.58, 0.28],
        ['Id', 'Rec', 'Name', 'Author'],
        rows,
    )


async def _get_challenges_no_target(aseco: 'Aseco', player, author: bool):
    """Tracks the player finished without beating gold/author target."""
    player.tracklist = []
    is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == 4
    tracks = await _get_challenges_cache(aseco)
    stats = await _get_player_track_stats(aseco, player)
    clickable = getattr(aseco.settings, 'clickable_lists', False)
    rows = []
    tid = 1

    if author:
        title = "Tracks You Didn't Beat Author Time On:"
        target_key = 'AuthorScore' if is_stnt else 'AuthorTime'
    else:
        title = "Tracks You Didn't Beat Gold Time On:"
        target_key = 'GoldTime'

    for row in tracks:
        uid = row.get('UId', '')
        if not uid or uid not in stats:
            continue
        best = stats[uid]['best']
        target = await _get_track_target_value(aseco, row, uid, author=author, is_stnt=is_stnt)
        if target <= 0:
            continue
        if is_stnt:
            if best >= target:
                continue
            diff = target - best
        else:
            if best <= target:
                continue
            diff = best - target
        _append_tracklist_entry(player, row, uid)
        rows.append([
            f'{tid:03d}.',
            _fmt_track_name(row.get('Name', ''), uid, tid, clickable),
            _format_list_author(row.get('Author', ''), tid, clickable),
            _format_diff(diff, is_stnt),
        ])
        tid += 1

    _set_paginated_msgs(
        player,
        title,
        [1.18, 0.12, 0.56, 0.28, 0.16],
        ['Id', 'Name', 'Author', 'Time'],
        rows,
    )


async def _get_challenges_no_recent(aseco: 'Aseco', player):
    """Tracks ordered by how long ago the player last played them."""
    player.tracklist = []
    tracks = await _get_challenges_cache(aseco)
    track_by_uid = {row.get('UId', ''): row for row in tracks}
    stats = await _get_player_track_stats(aseco, player)
    rec_ranks = await _get_player_rec_ranks(aseco, player)
    maxrecs = _get_maxrecs(aseco)
    clickable = getattr(aseco.settings, 'clickable_lists', False)

    rows = []
    tid = 1
    ordered = sorted(
        ((uid, data) for uid, data in stats.items() if uid in track_by_uid),
        key=lambda item: item[1].get('last_date', 0)
    )
    for uid, data in ordered:
        row = track_by_uid[uid]
        _append_tracklist_entry(player, row, uid)
        rank = rec_ranks.get(uid, 0)
        rec_str = f'{rank:02d}.' if 1 <= rank <= maxrecs else '-- '
        played_at = int(data.get('last_date', 0) or 0)
        date_str = time.strftime('%Y/%m/%d', time.localtime(played_at)) if played_at else '----/--/--'
        rows.append([
            f'{tid:03d}.',
            rec_str,
            _fmt_track_name(row.get('Name', ''), uid, tid, clickable),
            _format_list_author(row.get('Author', ''), tid, clickable),
            date_str,
        ])
        tid += 1

    _set_paginated_msgs(
        player,
        "Tracks You Didn't Play Recently:",
        [1.30, 0.12, 0.1, 0.52, 0.28, 0.18],
        ['Id', 'Rec', 'Name', 'Author', 'Date'],
        rows,
    )


async def _get_all_challenges(aseco: 'Aseco', player, wildcard: str = '*'):
    """
    Port of getAllChallenges() from rasp.funcs.php.
    Fetches all tracks from the server and filters by name/author wildcard.
    Fills player.tracklist and player.msgs (paginated ManiaLink).
    """
    player.tracklist = []

    # Fetch player's record ranks (uid → rank)
    rec_ranks = await _get_player_rec_ranks(aseco, player)

    # Fetch full track list from server
    tracks = await _get_challenges_cache(aseco)

    header = 'Tracks On This Server:'
    col_has_rec = True  # always show Rec column
    clickable = getattr(aseco.settings, 'clickable_lists', False)

    best_times = await _get_best_local_times(aseco)

    msg  = [['Id', 'Rec', 'Name', 'Time', 'Author']]
    tid  = 1
    lines = 0
    player.msgs = [[1, header, [1.2, 0.12, 0.1, 0.52, 0.16, 0.28],
                    ['Icons128x128_1', 'NewTrack', 0.02]]]

    for row in tracks:
        name   = row.get('Name', '')
        author = row.get('Author', '')
        uid    = row.get('UId', '')
        fname  = row.get('FileName', '')

        # Wildcard filter
        if wildcard != '*':
            from pyxaseco.helpers import strip_colors as _sc
            if (wildcard.lower() not in _sc(name, for_tm=False).lower() and
                    wildcard.lower() not in author.lower()):
                continue

        # Store in tracklist for /jb
        player.tracklist.append({
            'name':        name,
            'author':      author,
            'environment': row.get('Environnement', ''),
            'filename':    fname,
            'uid':         uid,
        })

        # Format track name
        trackname = _fmt_track_name(name, uid, tid, clickable)
        # Format author (clickable → list by author)
        trackauthor = author
        if clickable and tid <= 1900:
            trackauthor = [author, -(100 + tid)]

        # Record rank
        rank = rec_ranks.get(uid, 0)
        maxrecs = _get_maxrecs(aseco)
        rec_str = f'{rank:02d}.' if (1 <= rank <= maxrecs) else '-- '

        best_ms  = best_times.get(uid, 0)
        time_str = format_time(best_ms) if best_ms else '--:--'
        msg.append([f'{tid:03d}.', rec_str, trackname, time_str, trackauthor])
        tid += 1
        lines += 1
        if lines >= 15:
            player.msgs.append(msg)
            lines = 0
            msg = [['Id', 'Rec', 'Name', 'Time', 'Author']]

    if len(msg) > 1:
        player.msgs.append(msg)


async def _get_challenges_by_length(aseco: 'Aseco', player, shortest: bool):
    """Port of getChallengesByLength() - sort by author time."""
    player.tracklist = []
    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    if mode == 4:  # Stunts
        return

    tracks = await _get_challenges_cache(aseco)
    clickable = getattr(aseco.settings, 'clickable_lists', False)
    best_times = await _get_best_local_times(aseco)

    # Sort by AuthorTime
    sorted_tracks = sorted(
        [(row.get('UId', ''), row) for row in tracks if int(row.get('AuthorTime', 0) or 0) > 0],
        key=lambda x: x[1].get('AuthorTime', 0),
        reverse=not shortest
    )

    label = 'Shortest' if shortest else 'Longest'
    header = f'{label} Tracks On This Server:'
    msg   = [['Id', 'Name', 'Time', 'Author', 'AuthTime']]
    tid   = 1
    lines = 0
    player.msgs = [[1, header, [1.36, 0.12, 0.52, 0.16, 0.28, 0.16],
                    ['Icons128x128_1', 'NewTrack', 0.02]]]

    for uid, row in sorted_tracks:
        name   = row.get('Name', '')
        author = row.get('Author', '')
        atime  = row.get('AuthorTime', 0)

        player.tracklist.append({
            'name': name, 'author': author,
            'environment': row.get('Environnement', ''),
            'filename': row.get('FileName', ''), 'uid': uid,
        })

        trackname   = _fmt_track_name(name, uid, tid, clickable)
        trackauthor = [author, -(100 + tid)] if (clickable and tid <= 1900) else author
        best_ms = best_times.get(uid, 0)
        time_str = format_time(best_ms) if best_ms else '--:--'

        msg.append([f'{tid:03d}.', trackname, time_str, trackauthor, format_time(atime)])
        tid += 1; lines += 1
        if lines >= 15:
            player.msgs.append(msg)
            lines = 0
            msg = [['Id', 'Name', 'Time', 'Author', 'AuthTime']]

    if len(msg) > 1:
        player.msgs.append(msg)


async def _get_challenges_by_add(aseco: 'Aseco', player, newest: bool, count: int):
    """Port of getChallengesByAdd() - sort by DB insertion order."""
    player.tracklist = []

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    tracks     = await _get_challenges_cache(aseco)
    track_by_uid = {row.get('UId', ''): row for row in tracks}
    best_times = await _get_best_local_times(aseco)

    clickable = getattr(aseco.settings, 'clickable_lists', False)
    label     = 'Newest' if newest else 'Oldest'
    header    = f'{label} Tracks On This Server:'
    msg       = [['Id', 'Name', 'Time', 'Author']]
    tid       = 1
    lines     = 0
    player.msgs = [[1, header, [1.2, 0.12, 0.52, 0.16, 0.28],
                    ['Icons128x128_1', 'NewTrack', 0.02]]]

    ordered_uids = []
    if pool:
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    order = 'DESC' if newest else 'ASC'
                    await cur.execute(f'SELECT Uid FROM challenges ORDER BY Id {order}')
                    rows = await cur.fetchall()
                    ordered_uids = [r[0] for r in rows if r[0] in track_by_uid]
        except Exception:
            pass

    if not ordered_uids:
        # Fallback: use server order
        ordered_uids = [row.get('UId', '') for row in tracks]
        if newest:
            ordered_uids = list(reversed(ordered_uids))

    added = 0
    for uid in ordered_uids:
        if uid not in track_by_uid:
            continue
        row    = track_by_uid[uid]
        name   = row.get('Name', '')
        author = row.get('Author', '')

        player.tracklist.append({
            'name': name, 'author': author,
            'environment': row.get('Environnement', ''),
            'filename': row.get('FileName', ''), 'uid': uid,
        })

        trackname   = _fmt_track_name(name, uid, tid, clickable)
        trackauthor = [author, -(100 + tid)] if (clickable and tid <= 1900) else author
        best_ms = best_times.get(uid, 0)
        time_str = format_time(best_ms) if best_ms else '--:--'

        msg.append([f'{tid:03d}.', trackname, time_str, trackauthor])
        tid += 1; lines += 1; added += 1
        if lines >= 15:
            player.msgs.append(msg)
            lines = 0
            msg = [['Id', 'Name', 'Time', 'Author']]
        if added >= count:
            break

    if len(msg) > 1:
        player.msgs.append(msg)


def _fmt_track_name(name: str, uid: str, tid: int, clickable: bool):
    """Format track name: grey if in jb_buffer, clickable if enabled."""
    from pyxaseco.helpers import strip_colors
    if uid in jb_buffer:
        return '{#grey}' + strip_colors(name, for_tm=False)
    display = '{#black}' + name
    if clickable and tid <= 1900:
        return [display, tid + 100]
    return display


async def _get_challenges_cache(aseco: 'Aseco') -> list:
    """Fetch full track list from server (mirrors getChallengesCache)."""
    try:
        tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
        return [dict(t) for t in tracks]
    except Exception as e:
        logger.debug('[List] GetChallengeList failed: %s', e)
        return []


async def _get_player_rec_ranks(aseco: 'Aseco', player) -> dict:
    """Fetch player's record rank per track uid from DB. Returns {uid: rank}."""
    pid = getattr(player, 'id', 0)
    if not pid:
        return {}
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return {}
        is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == 4
        order   = 'DESC' if is_stnt else 'ASC'
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f'SELECT c.Uid, r.PlayerId FROM records r '
                    f'LEFT JOIN challenges c ON (r.ChallengeId=c.Id) '
                    f'WHERE c.Uid IS NOT NULL '
                    f'ORDER BY r.ChallengeId ASC, r.Score {order}, r.Date ASC'
                )
                rows = await cur.fetchall()
        result: dict = {}
        last_uid  = None
        pos       = 1
        seen_uids: set = set()
        for uid, player_id in rows:
            if uid != last_uid:
                last_uid = uid
                pos      = 1
                seen_uids.clear()
            if uid in result:
                pos += 1
                continue
            if player_id == pid and uid not in result:
                result[uid] = pos
            pos += 1
        return result
    except Exception as e:
        logger.debug('[List] get_player_rec_ranks: %s', e)
        return {}


def _get_maxrecs(aseco: 'Aseco') -> int:
    try:
        from pyxaseco.plugins.plugin_rasp import _rasp
        return _rasp.get('maxrecs', 50)
    except Exception:
        return 50


async def chat_jukebox(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    param = str(command.get('params') or '').strip()

    if not (feature_jukebox or aseco.allow_ability(player, 'chat_jukebox')):
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_JUKEBOX'))
        return

    if param.isdigit() and int(param) >= 0:
        idx = int(param) - 1
        tracklist = getattr(player, 'tracklist', [])
        if not tracklist:
            await _reply(aseco, login, _get_rasp_msg(aseco, 'LIST_HELP'))
            return
        # Check for existing jukebox entry by this player
        if not aseco.allow_ability(player, 'chat_jb_multi'):
            for item in jukebox.values():
                if item.get('Login') == login:
                    await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_ALREADY'))
                    return
        if 0 <= idx < len(tracklist):
            t = tracklist[idx]
            uid = t.get('uid', '')
            if uid in jukebox:
                await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_DUPL'))
                return
            jukebox[uid] = {
                'FileName': t.get('filename', ''),
                'Name':     t.get('name', ''),
                'Env':      t.get('environment', ''),
                'Login':    login,
                'Nick':     player.nickname,
                'source':   'Jukebox',
                'tmx':      False,
                'uid':      uid,
            }
            msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX'),
                              strip_colors(t.get('name', '')),
                              strip_colors(player.nickname))
            await _jb_broadcast(aseco, msg)
            await aseco.release_event('onJukeboxChanged', ['add', jukebox[uid]])
        else:
            await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_NOTFOUND'))

    elif param == 'list':
        if jukebox:
            msg = _get_rasp_msg(aseco, 'JUKEBOX_LIST')
            for i, item in enumerate(jukebox.values(), 1):
                msg += f'{{#highlite}}{i}{{#emotic}}.[{{#highlite}}{strip_colors(item["Name"])}{{#emotic}}], '
            await _reply(aseco, login, msg.rstrip(', '))
        else:
            await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_EMPTY'))

    elif param == 'display':
        if jukebox:
            header = 'Upcoming tracks in the jukebox:'
            rows = [['Id', 'Name (click to drop)', 'Requester']]
            for i, item in enumerate(jukebox.values(), 1):
                name = f'{{#black}}{strip_colors(item["Name"])}'
                if aseco.settings.clickable_lists and i <= 100:
                    can_drop = (aseco.allow_ability(player, 'dropjukebox') or
                                item.get('Login') == login)
                    if can_drop:
                        name = [name, -2000 - i]
                rows.append([f'{i:02d}.', name, f'{{#black}}{strip_colors(item["Nick"])}'])
            pages = [rows[j:j+15] for j in range(0, len(rows), 15)]
            player.msgs = [[1, header, [1.1, 0.1, 0.6, 0.4],
                            ['Icons128x128_1', 'LoadTrack', 0.02]]]
            player.msgs.extend(pages)
            display_manialink_multi(aseco, player)
        else:
            await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_EMPTY'))

    elif param == 'drop':
        uid_to_drop = ''
        name_to_drop = ''
        for uid, item in jukebox.items():
            if item.get('Login') == login:
                uid_to_drop = uid
                name_to_drop = item.get('Name', '')
                break
        if uid_to_drop:
            drop = jukebox.pop(uid_to_drop)
            msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_DROP'),
                              strip_colors(player.nickname),
                              strip_colors(name_to_drop))
            await _jb_broadcast(aseco, msg)
            await aseco.release_event('onJukeboxChanged', ['drop', drop])
        else:
            await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_NODROP'))

    elif param in ('help', ''):
        header = '{#black}/jukebox$g will add a track to the jukebox:'
        data = [
            ['...', '{#black}help',    'Displays this help information'],
            ['...', '{#black}list',    'Shows upcoming tracks'],
            ['...', '{#black}display', 'Displays upcoming tracks and requesters'],
            ['...', '{#black}drop',    'Drops your currently added track'],
            ['...', '{#black}##',      'Adds track where ## is the Id from /list'],
        ]
        display_manialink(aseco, login, header,
                          ['Icons64x64_1', 'TrackInfo', -0.01],
                          data, [0.9, 0.05, 0.15, 0.7], 'OK')
    else:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'JUKEBOX_HELP'))


# ---------------------------------------------------------------------------
# /autojuke
# ---------------------------------------------------------------------------

async def chat_autojuke(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    param = str(command.get('params') or '').strip()
    if param.isdigit() and int(param) >= 0:
        # Redirect to /jukebox #
        command['params'] = param
        await chat_jukebox(aseco, command)
    else:
        await _reply(aseco, login, '{#server}> {#error}Usage: /autojuke <#>')


# ---------------------------------------------------------------------------
# /add (TMX download — stub)
# ---------------------------------------------------------------------------

async def chat_add(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    raw = str(command.get('params') or '').strip()

    if aseco.server.isrelay:
        await _reply(aseco, login, format_text(aseco.get_chat_message('NOTONRELAY')))
        return

    if not (feature_jukebox and feature_tmxadd):
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_ADD'))
        return

    import pyxaseco.plugins.plugin_rasp_votes as rasp_votes

    _raw_ss = getattr(player, 'spectatorstatus', None)
    _player_is_spec = ((int(_raw_ss) % 10) != 0) if _raw_ss is not None else bool(player.isspectator)
    if _player_is_spec and not rasp_votes.allow_spec_startvote:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_SPECTATORS'))
        return

    if rasp_votes.tmxadd or rasp_votes.chatvote:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'VOTE_ALREADY'))
        return

    args = raw.split()
    if not args:
        await _reply(aseco, login, '{#server}> {#error}You must include a TMX Track_ID!')
        return

    section = _default_tmx_section(aseco)
    if len(args) >= 2 and args[-1].upper() in TMX_SEARCH_PREFIXES:
        section = args.pop().upper()

    ref = args[0]
    tracks_root = pathlib.Path(
        getattr(
            aseco.settings,
            'tracks_root',
            aseco._base_dir.parent / 'GameData' / 'Tracks' / 'Challenges'
        )
    ).resolve()

    try:
        abs_path, rel_insert, _host, _track_id, metadata = await download_tmx_track(
            ref, tracks_root, section.lower()
        )
    except urllib.error.HTTPError as e:
        await _reply(aseco, login, f'{{#server}}> {{#error}}HTTP {e.code}')
        return
    except urllib.error.URLError as e:
        await _reply(aseco, login, f'{{#server}}> {{#error}}{e.reason}')
        return
    except Exception as e:
        await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return

    try:
        size_kb = int((abs_path.stat().st_size + 1023) // 1024)
    except Exception:
        size_kb = 0
    if size_kb > 1024:
        try:
            abs_path.unlink(missing_ok=True)
        except Exception:
            pass
        await _reply(aseco, login, format_text(_get_rasp_msg(aseco, 'TRACK_TOO_LARGE'), size_kb))
        return

    uid = str(metadata.get('uid', '') or '').strip()
    name = str(metadata.get('name', '') or '').strip()
    environment = str(metadata.get('environment', '') or '').strip()
    if not uid or not name:
        try:
            abs_path.unlink(missing_ok=True)
        except Exception:
            pass
        await _reply(aseco, login, '{#server}> {#error}No such track on TMX!')
        return

    server_track = await _find_server_track_by_uid_or_filename(aseco, uid, rel_insert)
    if server_track:
        try:
            abs_path.unlink(missing_ok=True)
        except Exception:
            pass
        await _reply(aseco, login, _get_rasp_msg(aseco, 'ADD_PRESENTJB'))
        player.tracklist = [{
            'name': server_track.get('Name', ''),
            'author': server_track.get('Author', ''),
            'environment': server_track.get('Environnement', ''),
            'filename': server_track.get('FileName', ''),
            'uid': (server_track.get('UId', '') or server_track.get('Uid', '') or ''),
        }]
        await chat_jukebox(aseco, {'author': player, 'params': '1'})
        return

    if uid in jukebox:
        try:
            abs_path.unlink(missing_ok=True)
        except Exception:
            pass
        await _reply(aseco, login, _get_rasp_msg(aseco, 'ADD_DUPL'))
        return

    try:
        ok = await aseco.client.query('CheckChallengeForCurrentServerParams', rel_insert)
        reason = ''
    except Exception as e:
        ok = False
        reason = str(e)

    if not ok:
        try:
            abs_path.unlink(missing_ok=True)
        except Exception:
            pass
        await _reply(
            aseco,
            login,
            format_text(_get_rasp_msg(aseco, 'JUKEBOX_IGNORED'), strip_colors(name), reason or 'server params')
        )
        return

    rasp_votes.tmxadd.clear()
    rasp_votes.tmxadd.update({
        'filename': rel_insert,
        'votes': rasp_votes._required_votes(aseco, rasp_votes.vote_ratios[5]),
        'name': name,
        'environment': environment,
        'login': login,
        'nick': player.nickname,
        'source': 'TMX',
        'uid': uid,
        'section': section,
    })
    rasp_votes.plrvotes.clear()
    rasp_votes.r_expire_num = 0
    rasp_votes.ta_show_num = 0
    try:
        from pyxaseco.plugins.plugin_track import time_playing
        rasp_votes.ta_expire_start = time_playing(aseco)
    except Exception:
        rasp_votes.ta_expire_start = 0.0

    msg = format_text(
        _get_rasp_msg(aseco, 'JUKEBOX_ADD'),
        strip_colors(player.nickname),
        strip_colors(name),
        'TMX',
        rasp_votes.tmxadd['votes'],
    ).replace('{br}', '\n')
    await rasp_votes._broadcast_tmxadd(aseco, msg)
    await rasp_votes._vote_panels_on(aseco, login)

    if rasp_votes.auto_vote_starter:
        await chat_y(aseco, command)


# ---------------------------------------------------------------------------
# /history
# ---------------------------------------------------------------------------

async def chat_history(aseco: 'Aseco', command: dict):
    player = command['author']
    if not jb_buffer:
        await _reply(aseco, player.login,
                     '{#server}> {#error}No track history available!')
        return
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        msg = _get_rasp_msg(aseco, 'HISTORY')
        for i, uid in enumerate(reversed(jb_buffer[-10:]), 1):
            name = uid
            if pool:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT Name FROM challenges WHERE Uid=%s", (uid,))
                        row = await cur.fetchone()
                        if row:
                            name = strip_colors(row[0])
            msg += f'{{#highlite}}{i}{{#emotic}}.[{{#highlite}}{name}{{#emotic}}], '
        await _reply(aseco, player.login, msg.rstrip(', '))
    except Exception as e:
        logger.warning('[History] Error: %s', e)
        await _reply(aseco, player.login, '{#server}> {#error}Error reading track history.')


# ---------------------------------------------------------------------------
# /xlist (TMX search)
# ---------------------------------------------------------------------------

async def chat_xlist(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    raw = str(command.get('params') or '').strip()
    params = raw.split() if raw else []
    section = _default_tmx_section(aseco)

    if not params or params[0].lower() == 'help':
        header = '{#black}/xlist$g will show tracks on TMX:'
        rows = [
            ['...', '{#black}help', 'Displays this help information'],
            ['...', '{#black}recent', 'Lists the 10 most recent tracks'],
            ['...', '{#black}xxx', 'Lists tracks matching a name or author'],
            ['...', '{#black}auth:yyy', 'Lists tracks matching author'],
            ['...', '{#black}tmx', 'Selects a TMX section from TMO,TMS,TMN,TMNF,TMU'],
            ['...', '{#black}tag #', 'Tag search is planned but not implemented yet'],
            [],
            ['Pick a TMX Id number from the list, and use {#black}/add # {sec}'],
        ]
        display_manialink(
            aseco, login, header,
            ['Icons64x64_1', 'TrackInfo', -0.01],
            rows, [1.2, 0.05, 0.35, 0.8], 'OK'
        )
        return

    if params[-1].upper() in TMX_SEARCH_PREFIXES:
        section = params.pop().upper()

    if params and params[0].lower() == 'tag':
        await _reply(aseco, login, '{#server}> {#error}/xlist tag is not implemented yet.')
        return

    recent = params and params[0].lower() == 'recent'
    name = ''
    author = ''
    if recent:
        tracks = await _search_tmx_tracks(section, recent=True)
    else:
        rebuilt = [token.replace('%20', ' ') for token in params]
        for token in rebuilt:
            if token.lower().startswith('auth:'):
                part = token[5:].strip()
                author = part if not author else f'{author} {part}'
            else:
                name = token if not name else f'{name} {token}'

        if author:
            tracks = await _search_tmx_tracks(section, author=author)
        else:
            tracks = await _search_tmx_tracks(section, name=name)
            if not tracks and name:
                tracks = await _search_tmx_tracks(section, author=name)

    if not tracks:
        await _reply(aseco, login, '{#server}> {#error}No tracks found, or TMX is down!')
        return

    adminadd = bool(aseco.allow_ability(player, 'add'))
    clickable = getattr(aseco.settings, 'clickable_lists', False)
    player.tracklist = []
    header = f'Tracks On TMX Section {{#black}}{section}$g:'

    if adminadd:
        widths = [1.55, 0.12, 0.16, 0.6, 0.1, 0.4, 0.17]
        columns = ['Id', 'TMX', 'Name (click to /add)', '$nAdmin', 'Author', 'Env']
    else:
        widths = [1.45, 0.12, 0.16, 0.6, 0.4, 0.17]
        columns = ['Id', 'TMX', 'Name (click to /add)', 'Author', 'Env']

    player.msgs = [[1, header, widths, ['Icons128x128_1', 'LoadTrack', 0.02]]]
    page = [columns]
    tid = 1
    for row in tracks[:500]:
        tmxid = f'{{#black}}{row["id"]}'
        name_cell = f'{{#black}}{row["name"]}'
        author_cell = row['author']

        if clickable and tid <= 500:
            tmxid = [tmxid, tid + 5200]
            name_cell = [name_cell, tid + 5700]
            author_cell = [author_cell, tid + 6700]

        player.tracklist.append({
            'id': row['id'],
            'section': row['section'],
            'author': row['author'],
            'name': row['name'],
        })

        if adminadd:
            add_cell = ['Add', tid + 6200] if (clickable and tid <= 500) else 'Add'
            page.append([f'{tid:03d}.', tmxid, name_cell, add_cell, author_cell, row['environment']])
        else:
            page.append([f'{tid:03d}.', tmxid, name_cell, author_cell, row['environment']])

        tid += 1
        if len(page) - 1 >= 15:
            player.msgs.append(page)
            page = [columns]

    if len(page) > 1:
        player.msgs.append(page)

    display_manialink_multi(aseco, player)


# ---------------------------------------------------------------------------
# ManiaLink click handler
# ---------------------------------------------------------------------------

async def _event_jukebox(aseco: 'Aseco', answer: list):
    if len(answer) < 3:
        return
    action = int(answer[2])
    login = answer[1]
    player = aseco.server.players.get_player(login)
    if not player:
        return

    if 101 <= action <= 2000:
        aseco.console('player {1} clicked command "/jukebox {2}"', login, action - 100)
        await chat_jukebox(aseco, {'author': player, 'params': str(action - 100)})

    elif -7900 <= action <= -6001:
        track_idx = abs(action) - 6001
        tracklist = getattr(player, 'tracklist', [])
        if track_idx < len(tracklist):
            try:
                from pyxaseco.plugins.plugin_mania_karma import chat_karma
                aseco.console('player {1} clicked /karma {2}', login, track_idx + 1)
                await chat_karma(aseco, {'author': player, 'params': str(track_idx + 1)})
            except ImportError:
                pass

    elif -2000 <= action <= -101:
        tracklist = getattr(player, 'tracklist', [])
        idx = abs(action) - 101
        if idx < len(tracklist):
            author = tracklist[idx].get('author', '')
            await chat_list(aseco, {'author': player, 'params': author})

    elif -2100 <= action <= -2001:
        idx = abs(action) - 2001
        if aseco.allow_ability(player, 'dropjukebox'):
            aseco.console('player {1} clicked /admin dropjukebox {2}', login, idx + 1)
            try:
                from pyxaseco.plugins.chat_admin import chat_admin
                await chat_admin(aseco, {'author': player, 'params': f'dropjukebox {idx + 1}'})
            except Exception:
                pass
        else:
            await chat_jukebox(aseco, {'author': player, 'params': 'drop'})
        if jukebox:
            await chat_jukebox(aseco, {'author': player, 'params': 'display'})

    elif 5201 <= action <= 5700:
        idx = action - 5201
        tracklist = getattr(player, 'tracklist', [])
        if idx < len(tracklist):
            track = tracklist[idx]
            try:
                from pyxaseco.plugins.plugin_tmxinfo import chat_tmxinfo
                aseco.console('player {1} clicked command "/tmxinfo {2} {3}"',
                              login, track.get('id', ''), track.get('section', ''))
                await chat_tmxinfo(
                    aseco,
                    {'author': player, 'params': f'{track.get("id", "")} {track.get("section", "")}'.strip()}
                )
            except Exception:
                pass

    elif 5701 <= action <= 6200:
        idx = action - 5701
        tracklist = getattr(player, 'tracklist', [])
        if idx < len(tracklist):
            track = tracklist[idx]
            aseco.console('player {1} clicked command "/add {2} {3}"',
                          login, track.get('id', ''), track.get('section', ''))
            await chat_add(
                aseco,
                {'author': player, 'params': f'{track.get("id", "")} {track.get("section", "")}'.strip()}
            )

    elif 6201 <= action <= 6700:
        idx = action - 6201
        tracklist = getattr(player, 'tracklist', [])
        if idx < len(tracklist):
            track = tracklist[idx]
            try:
                from pyxaseco.plugins.chat_admin import chat_admin
                aseco.console('player {1} clicked command "/admin add {2} {3}"',
                              login, track.get('id', ''), track.get('section', ''))
                await chat_admin(
                    aseco,
                    {'author': player, 'params': f'add {track.get("id", "")} {track.get("section", "")}'.strip()}
                )
            except Exception:
                pass

    elif 6701 <= action <= 7200:
        idx = action - 6701
        tracklist = getattr(player, 'tracklist', [])
        if idx < len(tracklist):
            track = tracklist[idx]
            author = str(track.get('author', '') or '').replace(' ', '%20')
            section = str(track.get('section', '') or '').strip()
            aseco.console('player {1} clicked command "/xlist auth:{2} {3}"',
                          login, author, section)
            await chat_xlist(
                aseco,
                {'author': player, 'params': f'auth:{author} {section}'.strip()}
            )
