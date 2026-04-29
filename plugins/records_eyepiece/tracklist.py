from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_time, safe_manialink_text, strip_colors
from pyxaseco.models import Gameinfo

from .config import _state
from .helpers import _enrich_track_with_tmx
from .ui import append_window_start, append_window_end

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tracklist window constants
# ---------------------------------------------------------------------------

ML_WINDOW = 91800
ML_SUBWIN = 91801

TL_PAGE_SIZE = 20      # tracks per page (4 cols × 5 rows)
TL_COLS = 4
TL_ROWS = 5

COL_OFFSET = 19.05
ROW_OFFSET = 9.45
CARD_W = 17.75
CARD_H = 9.2

TL_PREV_BASE = 9181000    # prev page: -(TL_PREV_BASE + page)
TL_NEXT_BASE = 9181000    # next page: TL_NEXT_BASE + page + 1
TL_JB_BASE = 9182000      # jukebox: TL_JB_BASE + global_idx (1-based)
TL_DROP_BASE = 2000       # drop jb: -(TL_DROP_BASE + jb_pos)

_TRACK_ENV_IMAGES = {
    'stadium': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-stadium-enabled.png',
    'bay': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-bay-enabled.png',
    'coast': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-coast-enabled.png',
    'desert': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-desert-enabled.png',
    'speed': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-desert-enabled.png',
    'island': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-island-enabled.png',
    'rally': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-rally-enabled.png',
    'alpine': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-snow-enabled.png',
    'snow': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-snow-enabled.png',
}


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

async def _fetch_tracklist_data(aseco: 'Aseco') -> list:
    """
    Fetch all tracks from server and enrich with AuthorTime from DB.

    Returns list of dicts:
      uid, name, author, env, filename, authortime_ms, dbid, karma,
      goldtime_ms, silvertime_ms, bronzetime_ms, laprace, nblaps
    """
    try:
        tracks_raw = await aseco.client.query('GetChallengeList', 5000, 0) or []
    except Exception as e:
        logger.debug('[Eyepiece] GetChallengeList: %s', e)
        return []

    db_ids: dict = {}
    karma_map: dict = {}
    extra_meta: dict = {}

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        from pyxaseco.core.challenges_cache import get_metadata_map

        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # challenges table only has: Id, Uid, Name, Author, Environment
                    # AuthorTime is not stored in DB — comes from GBX GetChallengeList
                    await cur.execute(
                        'SELECT Id, Uid FROM challenges WHERE Uid IS NOT NULL'
                    )
                    for row in await cur.fetchall():
                        if row[1]:
                            db_ids[row[1]] = row[0]

                    await cur.execute(
                        'SELECT c.Uid, SUM(k.Score) AS karma '
                        'FROM rs_karma k '
                        'LEFT JOIN challenges c ON (k.ChallengeId = c.Id) '
                        'WHERE c.Uid IS NOT NULL '
                        'GROUP BY c.Uid'
                    )
                    for row in await cur.fetchall():
                        if row[0] is not None:
                            karma_map[row[0]] = int(row[1] or 0)
            extra_meta = await get_metadata_map(pool)
    except Exception as e:
        logger.debug('[Eyepiece] DB enrich for tracklist: %s', e)

    result = []
    for t in tracks_raw:
        uid = t.get('UId', '')
        env = t.get('Environnement', '')
        if env.upper() == 'SPEED':
            env = 'Desert'
        elif env.upper() == 'SNOW':
            env = 'Alpine'

        name = t.get('Name', '') or ''
        author = t.get('Author', '') or ''
        meta = extra_meta.get(uid, {})

        result.append({
            'uid': uid,
            'name': name,
            'name_orig': name,
            'name_plain': strip_colors(name, for_tm=False),
            'author': author,
            'env': env,
            'mood': '',
            'filename': t.get('FileName', '') or '',
            'authortime_ms': int(t.get('AuthorTime', 0) or meta.get('author_time', 0) or 0),
            'goldtime_ms': int(t.get('GoldTime', 0) or meta.get('gold_time', 0) or 0),
            'silvertime_ms': t.get('SilverTime', 0) or 0,
            'bronzetime_ms': t.get('BronzeTime', 0) or 0,
            'laprace': bool(t.get('LapRace', False)),
            'nblaps': t.get('NbLaps', 0) or 0,
            'dbid': db_ids.get(uid, int(meta.get('challenge_id', 0) or 0)),
            'added_at': meta.get('added_at') or '',
            'karma': karma_map.get(uid, 0),
        })

    return result


async def _get_player_local_records(aseco: 'Aseco', player) -> dict:
    """
    Port of re_getPlayerLocalRecords():
    returns {uid: {rank, score}} for calling player.
    """
    pid = getattr(player, 'id', 0)
    if not pid:
        return {}

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool

        pool = await get_pool()
        if not pool:
            return {}

        is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.STNT
        order = 'DESC' if is_stnt else 'ASC'

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f'SELECT c.Uid, r.PlayerId, r.Score '
                    f'FROM records r '
                    f'LEFT JOIN challenges c ON (r.ChallengeId = c.Id) '
                    f'WHERE c.Uid IS NOT NULL '
                    f'ORDER BY r.ChallengeId ASC, r.Score {order}, r.Date ASC'
                )
                rows = await cur.fetchall()

        result: dict = {}
        last_uid = None
        pos = 1
        for uid, player_id, score in rows:
            if uid != last_uid:
                last_uid = uid
                pos = 1
            if uid not in result and player_id == pid:
                result[uid] = {'rank': pos, 'score': score}
            pos += 1
        return result

    except Exception as e:
        logger.debug('[Eyepiece] _get_player_local_records: %s', e)
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

        is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.STNT
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
        logger.debug('[Eyepiece] _get_player_track_stats: %s', e)
        return {}


def _get_maxrecs(aseco: 'Aseco') -> int:
    try:
        from pyxaseco.plugins.plugin_rasp import _rasp
        return int(_rasp.get('maxrecs', 50) or 50)
    except Exception:
        return 50


# ---------------------------------------------------------------------------
# Window builders
# ---------------------------------------------------------------------------

def _build_tracklist_window(aseco, page, tracks, player, player_recs, title):
    """
    Port of re_buildTracklistWindow() card-grid ManiaLink.

    Layout (from PHP):
      Window: frame posn="-40.1 30.45"
      Content frame: posn="2.5 -5.7 0.05"
      Cards: 4 cols × 5 rows
    """
    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import jukebox, jb_buffer
    except ImportError:
        jukebox = {}
        jb_buffer = []

    maxrecs = 50
    try:
        from pyxaseco.plugins.plugin_rasp import _rasp
        maxrecs = _rasp.get('maxrecs', 50)
    except Exception:
        pass

    total = len(tracks)
    max_pages = max(1, (total + TL_PAGE_SIZE - 1) // TL_PAGE_SIZE)
    page = max(0, min(page, max_pages - 1))

    # Pagination buttons
    btn = '<frame posn="52.2 -53.2 0.04">'
    if page > 0:
        prev5 = max(0, page - 5)
        btn += (
            f'<quad posn="6.6 0 0.01" sizen="3.2 3.2" action="-{TL_PREV_BASE + 1}" style="Icons64x64_1" substyle="ArrowFirst"/>'
            f'<quad posn="9.9 0 0.01" sizen="3.2 3.2" action="-{TL_PREV_BASE + prev5 + 1}" style="Icons64x64_1" substyle="ArrowFastPrev"/>'
            f'<quad posn="13.2 0 0.01" sizen="3.2 3.2" action="-{TL_PREV_BASE + page}" style="Icons64x64_1" substyle="ArrowPrev"/>'
        )
    else:
        btn += (
            '<quad posn="6.6 0 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            '<quad posn="9.9 0 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            '<quad posn="13.2 0 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        )

    if page < max_pages - 1:
        next5 = min(max_pages - 1, page + 5)
        btn += (
            f'<quad posn="16.5 0 0.01" sizen="3.2 3.2" action="{TL_NEXT_BASE + page + 1}" style="Icons64x64_1" substyle="ArrowNext"/>'
            f'<quad posn="19.8 0 0.01" sizen="3.2 3.2" action="{TL_NEXT_BASE + next5}" style="Icons64x64_1" substyle="ArrowFastNext"/>'
            f'<quad posn="23.1 0 0.01" sizen="3.2 3.2" action="{TL_NEXT_BASE + max_pages - 1}" style="Icons64x64_1" substyle="ArrowLast"/>'
        )
    else:
        btn += (
            '<quad posn="16.5 0 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            '<quad posn="19.8 0 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            '<quad posn="23.1 0 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        )
    btn += '</frame>'

    win_title = f'Tracks on this Server   |   Page {page+1}/{max_pages}   |   {total} Track{"s" if total != 1 else ""}'
    if title:
        win_title += f'  {title}'

    p = []
    p.append(f'<manialink id="{ML_SUBWIN}"></manialink>')
    p.append(f'<manialink id="{ML_WINDOW}">')
#    p.append('<quad posn="-64 48 18.49" sizen="128 96" bgcolor="0009"/>')
    p.append('<frame posn="-40.1 30.45 18.50">')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>')
    p.append('<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>')
    p.append('<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>')
    p.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="NewTrack"/>')
    p.append(f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="{win_title}"/>')
    p.append('<label posn="2.7 -54.1 0.04" sizen="30 1" textsize="1" scale="0.7" textcolor="000F" text="RECORDS-EYEPIECE/PyXaseco"/>')
    p.append('<frame posn="77.4 1.3 0.05">')
    p.append('<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>')
    p.append('<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>')
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ML_WINDOW}" style="Icons64x64_1" substyle="Close"/>')
    p.append('</frame>')
    p.append(btn)

    p.append('<frame posn="2.5 -5.7 0.05">')

    cur_challenge_uid = getattr(getattr(aseco.server, 'challenge', None), 'uid', '')

    col = 0
    row = 0
    start = page * TL_PAGE_SIZE

    for i in range(start, min(start + TL_PAGE_SIZE, total)):
        track = tracks[i]
        uid = track['uid']
        name = track['name']
        author = track['author']
        env = track['env']
        atime_ms = track['authortime_ms']
        karma = track['karma']
        global_idx = i + 1

        juked = 0
        jb_login = ''
        for jpos, (juid, jitem) in enumerate(jukebox.items(), 1):
            if jitem.get('uid') == uid or juid == uid:
                juked = jpos
                jb_login = jitem.get('Login', '')
                break

        is_recent = uid in jb_buffer
        is_juked = juked > 0

        x_off = col * COL_OFFSET
        y_off = row * ROW_OFFSET

        p.append(f'<frame posn="{x_off:.2f} -{y_off:.2f} 1">')

        env_key = _track_environment(track)
        env_image = _TRACK_ENV_IMAGES.get(env_key)
        if env_image:
            p.append(f'<quad posn="0.7 -0.28 0.06" sizen="3 2.2" image="{env_image}"/>')
        else:
            p.append('<quad posn="0.7 -0.35 0.06" sizen="3 1.96" style="Icons128x128_1" substyle="Challenge"/>')

        can_drop = (aseco.allow_ability(player, 'dropjukebox') or jb_login == player.login)

        if is_recent and is_juked:
            p.append('<format textsize="1" textcolor="FFF8"/>')
            p.append(f'<quad posn="0 0 0.02" sizen="{CARD_W} {CARD_H}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
            if can_drop:
                p.append(f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="-{TL_DROP_BASE + juked}" style="Icons64x64_1" substyle="Close"/>')
            p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="Bgs1InRace" substyle="BgListLine"/>')
            p.append(f'<label posn="3.8 -0.55 0.05" sizen="17.3 0" textcolor="000F" textsize="1" text="Track #{i+1}"/>')
            p.append(f'<label posn="1 -2.7 0.04" sizen="16 2" scale="1" text="{safe_manialink_text(name, keep_colors=False)}"/>')
            p.append(f'<label posn="1 -4.5 0.04" sizen="17.3 2" scale="0.9" text="{safe_manialink_text(f"by {author}", keep_colors=False)}"/>')

        elif is_recent:
            p.append('<format textsize="1" textcolor="FFF8"/>')
            p.append(f'<quad posn="0 0 0.02" sizen="{CARD_W} {CARD_H}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
            p.append(f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="{TL_JB_BASE + global_idx}" style="Icons64x64_1" substyle="Add"/>')
            p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
            p.append(f'<label posn="3.8 -0.55 0.05" sizen="17.3 0" textsize="1" text="Track #{i+1}"/>')
            p.append(f'<label posn="1 -2.7 0.04" sizen="16 2" scale="1" text="{safe_manialink_text(name, keep_colors=False)}"/>')
            p.append(f'<label posn="1 -4.5 0.04" sizen="17.3 2" scale="0.9" text="{safe_manialink_text(f"by {author}", keep_colors=False)}"/>')

        elif is_juked:
            p.append('<format textsize="1" textcolor="FFFF"/>')
            p.append(f'<quad posn="0 0 0.02" sizen="{CARD_W} {CARD_H}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
            if can_drop:
                p.append(f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="-{TL_DROP_BASE + juked}" style="Icons64x64_1" substyle="Close"/>')
            p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="Bgs1InRace" substyle="BgListLine"/>')
            p.append(f'<label posn="3.8 -0.55 0.05" sizen="17.3 0" textcolor="000F" textsize="1" text="Track #{i+1}"/>')
            p.append(f'<label posn="1 -2.7 0.04" sizen="16 2" scale="1" text="{name}"/>')
            p.append(f'<label posn="1 -4.5 0.04" sizen="17.3 2" scale="0.9" text="by {author}"/>')

        else:
            p.append('<format textsize="1" textcolor="FFFF"/>')
            p.append(f'<quad posn="0 0 0.02" sizen="{CARD_W} {CARD_H}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
            p.append(f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="{TL_JB_BASE + global_idx}" style="Icons64x64_1" substyle="Add"/>')
            p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="BgsPlayerCard" substyle="ProgressBar"/>')
            p.append(f'<label posn="3.8 -0.55 0.05" sizen="17.3 0" textsize="1" text="Track #{i+1}"/>')
            p.append(f'<label posn="1 -2.7 0.04" sizen="16 2" scale="1" text="{name}"/>')
            p.append(f'<label posn="1 -4.5 0.04" sizen="17.3 2" scale="0.9" text="by {author}"/>')

        if uid == cur_challenge_uid:
            p.append('<quad posn="15.3 0.4 0.06" sizen="3.4 3.4" style="BgRaceScore2" substyle="Fame"/>')

        atime_str = format_time(atime_ms) if atime_ms else '--:--'
        p.append('<quad posn="0.7 -6.9 0.04" sizen="1.6 1.5" style="BgRaceScore2" substyle="ScoreReplay"/>')
        p.append(f'<label posn="2.4 -7.15 0.04" sizen="5 1.5" scale="0.75" text="{atime_str}"/>')

        rec = player_recs.get(uid)
        rank = rec['rank'] if rec and 1 <= rec['rank'] <= maxrecs else 0
        rank_str = f'{rank:0{len(str(maxrecs))}d}.' if rank > 0 else '$ZNone'
        p.append('<quad posn="6.3 -6.8 0.04" sizen="2 1.6" style="Icons128x128_1" substyle="Rankings"/>')
        p.append(f'<label posn="8.1 -7.15 0.04" sizen="3.8 1.5" scale="0.75" text="{rank_str}"/>')

        p.append('<quad posn="11.2 -6.8 0.04" sizen="1.6 1.6" style="Icons64x64_1" substyle="StateFavourite"/>')
        p.append(f'<label posn="12.8 -7.15 0.04" sizen="2.2 1.5" scale="0.75" text="L{karma}"/>')

        p.append('</frame>')

        row += 1
        if row >= TL_ROWS:
            row = 0
            col += 1

    append_window_end(p)
    return ''.join(p)


def _build_tracklist_filter_window(aseco: 'Aseco', player) -> str:
    """
    Port of re_buildTracklistFilterWindow() — card-grid of filter options.
    Each card has an action that opens the tracklist with that filter applied.
    Action IDs: 91840–91846.
    """
    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    is_stnt = (mode == Gameinfo.STNT)
    score_label = 'Score' if is_stnt else 'Time'

    filters = [
        (91846, 'No Author ' + score_label, 'Challenge',
         f'Only tracks where no author {score_label.lower()} is available.'),
        (91845, 'No Gold ' + score_label, 'Challenge',
         f'Only tracks where no gold {score_label.lower()} is available.'),
        (91853, 'No Silver ' + score_label, 'Challenge',
         f'Only tracks where no silver {score_label.lower()} is available.'),
        (91854, 'No Bronze ' + score_label, 'Challenge',
         f'Only tracks where no bronze {score_label.lower()} is available.'),
        (91842, 'Only Recent Tracks', 'LoadTrack',
         'Only tracks played recently.'),
        (91841, 'No Recent Tracks', 'LoadTrack',
         'Only tracks NOT played recently.'),
        (91843, 'No Rank', 'Rankings',
         'Only tracks you have no rank on.'),
        (91844, 'Only Ranked', 'Rankings',
         'Only tracks you have a rank on.'),
        (91840, 'Jukeboxed Only', 'NewTrack',
         'Only tracks currently in the jukebox.'),
        (91851, 'Only MultiLap', 'Laps',
         'Only multilap tracks.'),
        (91852, 'No MultiLap', 'Laps',
         'Only non-multilap tracks.'),
    ]

    p = []
    p.append(f'<manialink id="{ML_SUBWIN}"></manialink>')
    p.append(f'<manialink id="{ML_WINDOW}">')
#    p.append('<quad posn="-64 48 18.49" sizen="128 96" bgcolor="0009"/>')
    p.append('<frame posn="-40.1 30.45 18.50">')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>')
    p.append('<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>')
    p.append('<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>')
    p.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="NewTrack"/>')
    p.append('<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="Filter options for Tracklist"/>')
    p.append('<frame posn="77.4 1.3 0.05">')
    p.append('<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>')
    p.append('<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>')
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ML_WINDOW}" style="Icons64x64_1" substyle="Close"/>')
    p.append('</frame>')
    p.append('<frame posn="2.5 -5.7 0.05">')

    col, row = 0, 0
    for action_id, title, icon, desc in filters:
        x_off = col * COL_OFFSET
        y_off = row * ROW_OFFSET
        p.append(f'<frame posn="{x_off:.2f} -{y_off:.2f} 1">')
        p.append('<format textsize="1" textcolor="FFFF"/>')
        p.append(f'<quad posn="0 0 0.02" sizen="{CARD_W} {CARD_H}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
        p.append(f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="{action_id}" style="Icons64x64_1" substyle="Add"/>')
        p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="BgsPlayerCard" substyle="ProgressBar"/>')
        p.append(f'<quad posn="0.6 0 0.05" sizen="2.5 2.5" style="Icons128x128_1" substyle="{icon}"/>')
        p.append(f'<label posn="3.2 -0.55 0.05" sizen="17.3 0" textsize="1" text="{title}"/>')
        p.append(f'<label posn="1 -2.7 0.04" sizen="16 2" scale="0.9" autonewline="1" text="{desc}"/>')
        p.append('</frame>')

        row += 1
        if row >= TL_ROWS:
            row = 0
            col += 1

    p.append('</frame>')
    p.append('</frame>')
    p.append('</manialink>')
    return ''.join(p)


def _track_environment(track: dict) -> str:
    return str(track.get('env') or track.get('environment') or '').strip().lower()


def _track_mood(track: dict) -> str:
    return str(track.get('mood') or '').strip().lower()


def _track_is_multilap(track: dict) -> bool:
    name = str(track.get('filename') or '').lower()
    return 'multilap' in name or 'multi lap' in name or ' laps ' in name


def _track_has_medal(track: dict, medal: str) -> bool:
    key = medal.lower() + 'time_ms'
    value = track.get(key, None)
    try:
        return int(value or 0) > 0
    except Exception:
        return False


async def _enrich_tracks_with_tmx(aseco: 'Aseco', tracks: list, *, need_mood=False, need_env=False, need_times=False, limit: int | None = None, offset: int = 0):
    """
    Enrich track dicts with native challenge info first, then TMX as fallback.
    """
    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    if limit is None:
        seq = tracks[offset:]
    else:
        seq = tracks[offset:offset + limit]

    for track in seq:
        try:
            await _enrich_track_with_tmx(
                aseco, track, mode,
                need_mood=need_mood,
                need_env=need_env,
                need_times=need_times,
            )
        except Exception as e:
            logger.debug('[Eyepiece] Track enrich failed for %s: %s', track.get('uid', ''), e)



def _build_tracklist_sorting_window(aseco: 'Aseco') -> str:
    options = [
        (91870, 'Best Player Rank', 'Rankings', 'Tracks where your best rank is strongest.'),
        (91871, 'Worst Player Rank', 'Rankings', 'Tracks where your rank is weakest.'),
        (91872, 'Shortest Author Time', 'Challenge', 'Sort by shortest author time first.'),
        (91873, 'Longest Author Time', 'Challenge', 'Sort by longest author time first.'),
        (91874, 'Newest Tracks First', 'Buddies', 'Newest database entries first.'),
        (91875, 'Oldest Tracks First', 'Buddies', 'Oldest database entries first.'),
        (91876, 'By Trackname', 'TrackInfo', 'Alphabetical by track name.'),
        (91877, 'By Authorname', 'Buddies', 'Alphabetical by author.'),
        (91878, 'Best Karma', 'StateFavourite', 'Highest karma first.'),
        (91879, 'Worst Karma', 'StateFavourite', 'Lowest karma first.'),
    ]

    p = []
    p.append(f'<manialink id="{ML_SUBWIN}"></manialink>')
    p.append(f'<manialink id="{ML_WINDOW}">')
#    p.append('<quad posn="-64 48 18.49" sizen="128 96" bgcolor="0009"/>')
    p.append('<frame posn="-40.1 30.45 18.50">')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>')
    p.append('<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>')
    p.append('<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>')
    p.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="Rankings"/>')
    p.append('<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="Sorting options for Tracklist"/>')
    p.append('<frame posn="77.4 1.3 0.05">')
    p.append('<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>')
    p.append('<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>')
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ML_WINDOW}" style="Icons64x64_1" substyle="Close"/>')
    p.append('</frame>')
    p.append('<frame posn="2.5 -5.7 0.05">')

    col = row = 0
    for action_id, title, icon, desc in options:
        x_off = col * COL_OFFSET
        y_off = row * ROW_OFFSET
        p.append(f'<frame posn="{x_off:.2f} -{y_off:.2f} 1">')
        p.append('<format textsize="1" textcolor="FFFF"/>')
        p.append(f'<quad posn="0 0 0.02" sizen="{CARD_W} {CARD_H}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
        p.append(f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="{action_id}" style="Icons64x64_1" substyle="Add"/>')
        p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="BgsPlayerCard" substyle="ProgressBar"/>')
        p.append(f'<quad posn="0.6 0 0.05" sizen="2.5 2.5" style="Icons128x128_1" substyle="{icon}"/>')
        p.append(f'<label posn="3.2 -0.55 0.05" sizen="17.3 0" textsize="1" text="{title}"/>')
        p.append(f'<label posn="1 -2.7 0.04" sizen="16 2" scale="0.9" autonewline="1" text="{desc}"/>')
        p.append('</frame>')
        row += 1
        if row >= TL_ROWS:
            row = 0
            col += 1

    p.append('</frame></frame></manialink>')
    return ''.join(p)


def _build_trackauthorlist_window(page: int, authors: list[str]) -> str:
    max_pages = max(1, (len(authors) + 79) // 80)
    page = max(0, min(page, max_pages - 1))
    p = []
    win_title = f'Track Authors   |   Page {page+1}/{max_pages}   |   {len(authors)} Author{"s" if len(authors) != 1 else ""}'
    p.append(f'<manialink id="{ML_SUBWIN}"></manialink>')
    p.append(f'<manialink id="{ML_WINDOW}">')
#    p.append('<quad posn="-64 48 18.49" sizen="128 96" bgcolor="0009"/>')
    p.append('<frame posn="-40.1 30.45 18.50">')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>')
    p.append('<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>')
    p.append('<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>')
    p.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="Buddies"/>')
    p.append(f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="{win_title}"/>')
    p.append('<frame posn="77.4 1.3 0.05"><quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>')
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ML_WINDOW}" style="Icons64x64_1" substyle="Close"/></frame>')
    # paging
    btn = '<frame posn="52.2 -53.2 0.04">'
    if page > 0:
        prev5 = max(0, page - 5)
        btn += (
            f'<quad posn="6.6 0 0.01" sizen="3.2 3.2" action="-9187001" style="Icons64x64_1" substyle="ArrowFirst"/>'
            f'<quad posn="9.9 0 0.01" sizen="3.2 3.2" action="-{9187000 + prev5 + 1}" style="Icons64x64_1" substyle="ArrowFastPrev"/>'
            f'<quad posn="13.2 0 0.01" sizen="3.2 3.2" action="-{9187000 + page}" style="Icons64x64_1" substyle="ArrowPrev"/>'
        )
    if page < max_pages - 1:
        next5 = min(max_pages - 1, page + 5)
        btn += (
            f'<quad posn="16.5 0 0.01" sizen="3.2 3.2" action="{9187000 + page + 1}" style="Icons64x64_1" substyle="ArrowNext"/>'
            f'<quad posn="19.8 0 0.01" sizen="3.2 3.2" action="{9187000 + next5}" style="Icons64x64_1" substyle="ArrowFastNext"/>'
            f'<quad posn="23.1 0 0.01" sizen="3.2 3.2" action="{9187000 + max_pages - 1}" style="Icons64x64_1" substyle="ArrowLast"/>'
        )
    btn += '</frame>'
    p.append(btn)
    line_height = 2.2
    line = 0
    offset = 0.0
    array_count = page * 80
    for author in authors[page*80:page*80+80]:
        p.append(f'<quad posn="{0+offset:.2f} -{line_height*line+1:.2f} 0.10" sizen="17 2.2" action="-{9188000 + array_count}" style="Bgs1InRace" substyle="BgIconBorder"/>')
        p.append(f'<label posn="{1+offset:.2f} -{line_height*line+1.3:.2f} 0.11" sizen="16.5 0" textsize="1" scale="0.9" textcolor="05CF" text="{author}"/>')
        array_count += 1
        line += 1
        if line >= 20:
            offset += 19.05
            line = 0
    p.append('</frame></frame></manialink>')
    return ''.join(p)

# ---------------------------------------------------------------------------
# Send / close helpers
# ---------------------------------------------------------------------------

async def _send_tracklist_window(
    aseco: 'Aseco',
    player,
    page: int = 0,
    filter_cmd: str = '',
    search: str = '',
):
    """
    Fetch data, apply filter, build and send the card-grid window to the player.
    Stores state on player object for pagination.
    """
    from .widgets.common import _send

    all_tracks = await _fetch_tracklist_data(aseco)
    track_by_uid = {t['uid']: t for t in all_tracks if t.get('uid')}
    player_recs = await _get_player_local_records(aseco, player)
    player_stats = await _get_player_track_stats(aseco, player)
    maxrecs = _get_maxrecs(aseco)
    is_stnt = getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.STNT

    fc = filter_cmd.upper()
    if fc in ('SUNRISE', 'DAY', 'SUNSET', 'NIGHT'):
        await _enrich_tracks_with_tmx(aseco, all_tracks, need_mood=True)
    elif fc in ('STADIUM', 'BAY', 'COAST', 'DESERT', 'SPEED', 'ISLAND', 'RALLY', 'ALPINE', 'SNOW'):
        await _enrich_tracks_with_tmx(aseco, all_tracks, need_env=True)
    elif fc in ('NOAUTHOR', 'NOGOLD', 'NOSILVER', 'NOBRONZE'):
        await _enrich_tracks_with_tmx(aseco, all_tracks, need_times=True)

    title = ''
    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import jukebox, jb_buffer
    except ImportError:
        jukebox = {}
        jb_buffer = []

    fc = filter_cmd.upper()
    if fc == 'NORECENT':
        tracks = [t for t in all_tracks if t['uid'] not in jb_buffer]
        title = '(Filter: No Recent)'
    elif fc == 'ONLYRECENT':
        tracks = [t for t in all_tracks if t['uid'] in jb_buffer]
        title = '(Filter: Only Recent)'
    elif fc == 'JUKEBOX':
        jb_uids = set(jukebox.keys())
        tracks = [t for t in all_tracks if t['uid'] in jb_uids]
        title = '(Filter: Only Jukebox)'
    elif fc == 'NORANK':
        tracks = [
            t for t in all_tracks
            if t['uid'] in player_stats
            and (
                t['uid'] not in player_recs
                or int(player_recs[t['uid']].get('rank', 0) or 0) > maxrecs
            )
        ]
        title = '(Filter: Not Ranked)'
    elif fc == 'ONLYRANK':
        tracks = [t for t in all_tracks if t['uid'] in player_recs]
        title = '(Filter: Only Ranked)'
    elif fc == 'NOFINISH':
        tracks = [t for t in all_tracks if t['uid'] not in player_stats]
        title = '(Filter: Not Finished)'
    elif fc == 'NOAUTHOR':
        tracks = []
        for t in all_tracks:
            uid = t['uid']
            if uid not in player_stats:
                continue
            target = int(t.get('authortime_ms') or 0)
            if target <= 0:
                continue
            best = int(player_stats[uid].get('best', 0) or 0)
            if (is_stnt and best < target) or ((not is_stnt) and best > target):
                tracks.append(t)
        title = '(Filter: No Author)'
    elif fc == 'NOGOLD':
        tracks = []
        for t in all_tracks:
            uid = t['uid']
            if uid not in player_stats:
                continue
            target = int(t.get('goldtime_ms') or 0)
            if target <= 0:
                continue
            best = int(player_stats[uid].get('best', 0) or 0)
            if (is_stnt and best < target) or ((not is_stnt) and best > target):
                tracks.append(t)
        title = '(Filter: No Gold)'
    elif fc == 'NOSILVER':
        tracks = [t for t in all_tracks if not _track_has_medal(t, 'silver')]
        title = '(Filter: No Silver Time)'
    elif fc == 'NOBRONZE':
        tracks = [t for t in all_tracks if not _track_has_medal(t, 'bronze')]
        title = '(Filter: No Bronze Time)'
    elif fc in ('STADIUM', 'BAY', 'COAST', 'ISLAND', 'RALLY'):
        tracks = [t for t in all_tracks if _track_environment(t) == fc.lower()]
        title = f'(Filter: {fc.title()})'
    elif fc in ('DESERT', 'SPEED'):
        tracks = [t for t in all_tracks if _track_environment(t) in ('desert', 'speed')]
        title = '(Filter: Desert/Speed)'
    elif fc in ('ALPINE', 'SNOW'):
        tracks = [t for t in all_tracks if _track_environment(t) in ('alpine', 'snow')]
        title = '(Filter: Alpine/Snow)'
    elif fc in ('SUNRISE', 'DAY', 'SUNSET', 'NIGHT'):
        tracks = [t for t in all_tracks if _track_mood(t) == fc.lower()]
        title = f'(Filter: Mood {fc.title()})'
    elif fc == 'MULTILAP':
        tracks = [t for t in all_tracks if _track_is_multilap(t) or bool(t.get('laprace')) or int(t.get('nblaps') or 0) > 1]
        title = '(Filter: MultiLap)'
    elif fc == 'NOMULTILAP':
        tracks = [t for t in all_tracks if not (_track_is_multilap(t) or bool(t.get('laprace')) or int(t.get('nblaps') or 0) > 1)]
        title = '(Filter: No MultiLap)'
    elif fc == 'AUTHOR':
        tracks = all_tracks
        title = ''
    elif fc == 'NORECENT':
        tracks = [
            track_by_uid[uid]
            for uid, _data in sorted(
                ((uid, data) for uid, data in player_stats.items() if uid in track_by_uid),
                key=lambda item: item[1].get('last_date', 0)
            )
        ]
        title = '(Filter: No Recent)'
    elif fc == 'SHORTEST':
        tracks = sorted(all_tracks, key=lambda t: t['authortime_ms'] or 999999999)
        title = '(Sorting: Shortest)'
    elif fc == 'LONGEST':
        tracks = sorted(all_tracks, key=lambda t: t['authortime_ms'] or 0, reverse=True)
        title = '(Sorting: Longest)'
    elif fc == 'NEWEST':
        tracks = sorted(all_tracks, key=lambda t: (t.get('added_at') or '', t['dbid']), reverse=True)
        title = '(Sorting: Newest First)'
    elif fc == 'OLDEST':
        tracks = sorted(all_tracks, key=lambda t: (t.get('added_at') or '9999-12-31 23:59:59', t['dbid']))
        title = '(Sorting: Oldest First)'
    elif fc == 'BEST':
        tracks = sorted(
            [t for t in all_tracks if t['uid'] in player_recs],
            key=lambda t: player_recs[t['uid']]['rank']
        )
        title = '(Sorting: Best Rank)'
    elif fc == 'WORST':
        tracks = sorted(
            [t for t in all_tracks if t['uid'] in player_recs],
            key=lambda t: player_recs[t['uid']]['rank'],
            reverse=True
        )
        title = '(Sorting: Worst Rank)'
    elif fc == 'BESTKARMA':
        tracks = sorted(all_tracks, key=lambda t: t['karma'], reverse=True)
        title = '(Sorting: Best Karma)'
    elif fc == 'WORSTKARMA':
        tracks = sorted(all_tracks, key=lambda t: t['karma'])
        title = '(Sorting: Worst Karma)'
    elif fc == 'TRACK':
        tracks = sorted(all_tracks, key=lambda t: strip_colors(t['name'], for_tm=False).lower())
        title = '(Sorting: By Name)'
    elif fc == 'SORTAUTHOR':
        tracks = sorted(all_tracks, key=lambda t: t['author'].lower())
        title = '(Sorting: By Author)'
    elif search:
        sl = search.lower()
        tracks = [
            t for t in all_tracks
            if sl in strip_colors(t['name'], for_tm=False).lower()
            or sl in t['author'].lower()
        ]
        title = f'(Search: {search})'
    else:
        tracks = all_tracks

    player._tl_tracks = tracks
    player._tl_recs = player_recs
    player._tl_page = page
    player._tl_filter = filter_cmd
    player._tl_search = search
    player._tl_title = title

    page_start = max(0, page) * TL_PAGE_SIZE
    await _enrich_tracks_with_tmx(
        aseco,
        tracks,
        need_mood=False,
        need_env=True,
        need_times=True,
        limit=TL_PAGE_SIZE,
        offset=page_start,
    )
    xml = _build_tracklist_window(aseco, page, tracks, player, player_recs, title)
    await _send(aseco, player.login, xml)


async def _close_tracklist_window(aseco: 'Aseco', login: str):
    from .widgets.common import _send

    xml = f'<manialink id="{ML_WINDOW}"></manialink><manialink id="{ML_SUBWIN}"></manialink>'
    await _send(aseco, login, xml)

async def _send_trackauthorlist_window(aseco: 'Aseco', player, page: int = 0):
    from .widgets.common import _send
    all_tracks = await _fetch_tracklist_data(aseco)
    authors = sorted({strip_colors(t.get('author', ''), for_tm=False) for t in all_tracks if t.get('author')}, key=lambda a: a.lower())
    player._tl_authors = authors
    player._tl_author_page = page
    xml = _build_trackauthorlist_window(page, authors)
    await _send(aseco, player.login, xml)
