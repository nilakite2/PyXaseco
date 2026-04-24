"""
toplists.py — Records-Eyepiece toplist windows + score-screen column widgets.

Score-screen column widgets (shown at onEndRace, hidden at onEndRace1):
  ML 91818  TopRankings       — avg rank from rs_rank table
  ML 91819  TopWinners        — wins from players table
  ML 91820  MostRecords       — mostrecords from players_extra
  ML 91821  MostFinished      — mostfinished from players_extra
  ML 91822  TopPlaytime       — TimePlayed from players (>3600 s)
  ML 91823  TopDonators       — donations from players_extra
  ML 91824  TopNations        — nation count from players (with flag)
  ML 91825  TopTracks         — highest-karma tracks from tracklist cache
  ML 91826  TopVoters         — karma vote count from rs_karma
  ML 91845  TopRoundscore     — roundpoints from players_extra
  ML 91846  TopWinningPayouts — winningpayout from players_extra
  ML 91847  TopVisitors       — visits from players_extra
  ML 91848  TopActivePlayers  — most recently active players (UpdatedAt)

These all use the same SCORETABLE_LISTS header template (15.5-wide widget).
The popup windows (opened by clicking bar widgets) are also here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from datetime import date
from pyxaseco.models import Gameinfo
from pyxaseco.helpers import format_time

from .ui import append_window_start, append_window_end, append_four_player_columns
from .config import _state, _effective_mode
from .utils import _clip, _sanitise_nick

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Manialink IDs — score-screen column widgets
# ---------------------------------------------------------------------------
ML_TOP_RANKINGS       = 91818
ML_TOP_WINNERS        = 91819
ML_MOST_RECORDS       = 91820
ML_MOST_FINISHED      = 91821
ML_TOP_PLAYTIME       = 91822
ML_TOP_DONATORS       = 91823
ML_TOP_NATIONS        = 91824
ML_TOP_TRACKS         = 91825
ML_TOP_VOTERS         = 91826
ML_TOP_ROUNDSCORE     = 91845
ML_TOP_WINNING_PAYOUTS= 91846
ML_TOP_VISITORS       = 91847
ML_TOP_ACTIVE_PLAYERS = 91848

# Popup-window IDs (manialink sent to a single login)
ML_WINDOW  = 91800
ML_SUBWIN  = 91801

_COUNTRY_CACHE: dict[str, str] | None = None

# ---------------------------------------------------------------------------
# Nations helpers (shared with the Top Nations window)
# ---------------------------------------------------------------------------

def _load_nations_xml(aseco: 'Aseco') -> dict[str, str]:
    global _COUNTRY_CACHE
    if _COUNTRY_CACHE is not None:
        return _COUNTRY_CACHE
    candidates = [
        Path(getattr(aseco, '_base_dir', '.')).resolve() / 'nations.xml',
        Path('.').resolve() / 'nations.xml',
    ]
    result: dict[str, str] = {}
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            root = ET.parse(candidate).getroot()
            for node in root.findall('.//nation'):
                code = (node.get('code') or '').strip().upper()
                name = (node.findtext('name') or '').strip()
                if code and name:
                    result[code] = name
            if result:
                logger.info('[Records-Eyepiece] Loaded nations.xml from %s', candidate)
                break
        except Exception as exc:
            logger.warning('[Records-Eyepiece] Failed to parse nations.xml at %s: %r', candidate, exc)
    _COUNTRY_CACHE = result
    return result


def _country_name(aseco: 'Aseco', code: str) -> str:
    code = (code or '').strip().upper()
    if not code:
        return 'Other Countries'
    return _load_nations_xml(aseco).get(code, code)


def _flag_path(code: str) -> str:
    code = (code or '').strip().upper()
    if code in ('OTH', 'UNI', ''):
        return 'tmtp://Skins/Avatars/Flags/other.dds'
    return f'tmtp://Skins/Avatars/Flags/{code}.dds'


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

async def _db_query(sql: str, params: tuple = ()) -> list[tuple]:
    """Run a SELECT and return rows as list of tuples. Returns [] on error."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return list(await cur.fetchall())
    except Exception as exc:
        logger.warning('[Records-Eyepiece] DB query failed: %r  SQL: %s', exc, sql[:80])
        return []


# ---------------------------------------------------------------------------
# Shared scoretable-list header/footer (SCORETABLE_LISTS template)
# ---------------------------------------------------------------------------

def _stl_header(ml_id: int, cfg: dict, n_entries: int) -> str:
    st  = _state.style
    lh  = _state.line_height
    px  = cfg.get('pos_x', 0.0)
    py  = cfg.get('pos_y', 0.0)
    ist = escape(cfg.get('icon_style', 'Icons128x128_1'))
    iss = escape(cfg.get('icon_substyle', 'Rankings'))
    ttl = escape(cfg.get('title', ''))
    wh  = lh * n_entries + 3.3

    bg_sty  = escape(getattr(st, 'score_bg_style',    'BgsPlayerCard'))
    bg_sub  = escape(getattr(st, 'score_bg_substyle', 'BgRacePlayerName'))
    ti_sty  = escape(getattr(st, 'score_title_style', 'BgsPlayerCard'))
    ti_sub  = escape(getattr(st, 'score_title_sub',   'ProgressBar'))
    col_def = escape(getattr(st, 'score_col_default',  'FFFF'))

    return (
        f'<manialink id="{ml_id}">'
        f'<frame posn="{px:.2f} {py:.2f} 0">'
        f'<quad posn="0 0 0.001" sizen="15.5 {wh:.2f}" style="{bg_sty}" substyle="{bg_sub}"/>'
        f'<quad posn="0.4 -0.36 0.002" sizen="14.7 2" style="{ti_sty}" substyle="{ti_sub}"/>'
        f'<quad posn="0.6 -0.15 0.004" sizen="2.5 2.5" style="{ist}" substyle="{iss}"/>'
        f'<label posn="3.2 -0.55 0.004" sizen="10.2 0" textsize="1" text="{ttl}"/>'
        f'<format textsize="1" textcolor="{col_def}"/>'
    )


def _stl_footer() -> str:
    return '</frame></manialink>'


def _stl_empty(ml_id: int) -> str:
    return f'<manialink id="{ml_id}"></manialink>'


def _stl_row_score_nick(line: int, score: str, nick: str, lh: float,
                         fmt: str, sc: str) -> str:
    """Standard row: score right-aligned at x=4, nickname at x=4.65."""
    y = lh * line + 3.0
    return (
        f'<label posn="4 -{y:.2f} 0.002" sizen="3.4 1.7"'
        f' halign="right" scale="0.9" textcolor="{escape(sc)}"'
        f' text="{escape(fmt)}{escape(score)}"/>'
        f'<label posn="4.65 -{y:.2f} 0.002" sizen="11.1 1.7"'
        f' scale="0.9" text="{escape(fmt)}{escape(nick)}"/>'
    )


def _stl_row_rank_nick(line: int, rank: int, score: str, nick: str, lh: float,
                        fmt: str, sc: str) -> str:
    """Row with rank number at x=2.1, score at x=5.7, nick at x=5.9."""
    y   = lh * line + 3.0
    return (
        f'<label posn="2.1 -{y:.2f} 0.002" sizen="1.7 1.7"'
        f' halign="right" scale="0.9" text="{escape(fmt)}{rank}."/>'
        f'<label posn="5.7 -{y:.2f} 0.002" sizen="3.8 1.7"'
        f' halign="right" scale="0.9" textcolor="{escape(sc)}"'
        f' text="{escape(fmt)}{escape(score)}"/>'
        f'<label posn="5.9 -{y:.2f} 0.002" sizen="10.2 1.7"'
        f' scale="0.9" text="{escape(fmt)}{escape(nick)}"/>'
    )


# ---------------------------------------------------------------------------
# Score-screen column widget builders (async, DB-backed)
# ---------------------------------------------------------------------------

async def build_top_rankings_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_rankings
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_RANKINGS)

    entries = int(cfg.get('entries', 6))
    rows = await _db_query(
        'SELECT p.Login, p.NickName, r.avg '
        'FROM players p LEFT JOIN rs_rank r ON p.Id=r.PlayerId '
        'WHERE r.avg!=0 ORDER BY r.avg ASC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_RANKINGS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_RANKINGS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick  = str(row[1] or row[0] or '?')
        score = f'{float(row[2] or 0) / 10000:.1f}'
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_winners_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_winners
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_WINNERS)

    entries = int(cfg.get('entries', 6))
    rows = await _db_query(
        'SELECT Login, NickName, Wins FROM players '
        'WHERE Wins>0 ORDER BY Wins DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_WINNERS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_WINNERS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick  = str(row[1] or row[0] or '?')
        score = str(int(row[2] or 0))
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_most_records_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_most_records
    if not cfg.get('enabled', True):
        return _stl_empty(ML_MOST_RECORDS)

    entries = int(cfg.get('entries', 6))
    rows = await _db_query(
        'SELECT p.Login, p.NickName, pe.mostrecords '
        'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
        'ORDER BY pe.mostrecords DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_MOST_RECORDS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_MOST_RECORDS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick  = str(row[1] or row[0] or '?')
        score = str(int(row[2] or 0))
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_most_finished_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_most_finished
    if not cfg.get('enabled', True):
        return _stl_empty(ML_MOST_FINISHED)

    entries = int(cfg.get('entries', 6))
    rows = await _db_query(
        'SELECT p.Login, p.NickName, pe.mostfinished '
        'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
        'ORDER BY pe.mostfinished DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_MOST_FINISHED)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_MOST_FINISHED, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick  = str(row[1] or row[0] or '?')
        score = str(int(row[2] or 0))
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_playtime_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_playtime
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_PLAYTIME)

    entries = int(cfg.get('entries', 6))
    rows = await _db_query(
        'SELECT Login, NickName, TimePlayed FROM players '
        'WHERE TimePlayed>3600 ORDER BY TimePlayed DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_PLAYTIME)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_PLAYTIME, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick  = str(row[1] or row[0] or '?')
        score = f'{round(int(row[2] or 0) / 3600)} h'
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_donators_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_donators
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_DONATORS)

    entries = int(cfg.get('entries', 6))
    rows = await _db_query(
        'SELECT p.Login, p.NickName, pe.donations '
        'FROM players p LEFT JOIN players_extra pe ON p.Id=pe.playerID '
        'WHERE pe.donations!=0 ORDER BY pe.donations DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_DONATORS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_DONATORS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick  = str(row[1] or row[0] or '?')
        score = str(int(row[2] or 0))
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_nations_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_nations
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_NATIONS)

    entries = int(cfg.get('entries', 6))
# Flag code remapping for legacy ISO codes.
    _FLAGFIX = {'SCG': 'SRB', 'ROM': 'ROU', 'CAR': 'CMR'}

    rows = await _db_query(
        'SELECT COUNT(Nation) AS Count, Nation FROM players '
        'GROUP BY Nation ORDER BY Count DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_NATIONS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_NATIONS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        count = int(row[0] or 0)
        code  = _FLAGFIX.get(str(row[1] or '').upper(), str(row[1] or '').upper())
        y     = lh * i + 3.0
        flag_y = -(lh * i - 0.3) if i > 0 else 0.3
        name  = escape(_country_name(aseco, code))
        p.append(
            f'<label posn="4 -{y:.2f} 0.002" sizen="3.4 1.7"'
            f' halign="right" scale="0.9" textcolor="{escape(sc)}"'
            f' text="{escape(fmt)}{count}"/>'
            f'<quad posn="4.5 {flag_y:.2f} 0.003" sizen="2 2"'
            f' image="{escape(_flag_path(code))}"/>'
            f'<label posn="7.0 -{y:.2f} 0.002" sizen="8.5 1.7"'
            f' scale="0.9" text="{escape(fmt)}{name}"/>'
        )
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_tracks_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_tracks
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_TRACKS)

    entries = int(cfg.get('entries', 7))
    min_votes = 1
    try:
        from .config import _state as _s
        min_votes = int((_s.features_karma_min_votes if hasattr(_s, 'features_karma_min_votes')
                         else 1))
    except Exception:
        pass

    # Pull karma data from the DB (rs_karma join challenges)
    rows = await _db_query(
        'SELECT c.Name, '
        'SUM(CASE WHEN k.Score>0 THEN 1 ELSE 0 END) - SUM(CASE WHEN k.Score<0 THEN 1 ELSE 0 END) AS karma, '
        'COUNT(k.Score) AS votes '
        'FROM rs_karma k LEFT JOIN challenges c ON c.Id=k.ChallengeId '
        'WHERE c.Name IS NOT NULL '
        'GROUP BY k.ChallengeId '
        'HAVING votes >= %s AND karma >= 1 '
        'ORDER BY karma DESC LIMIT %s', (min_votes, entries))

    if not rows:
        return _stl_empty(ML_TOP_TRACKS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_TRACKS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        name  = str(row[0] or '?')
        karma = str(int(row[1] or 0))
        p.append(_stl_row_score_nick(i, karma, name, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_voters_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_voters
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_VOTERS)

    entries = int(cfg.get('entries', 7))
    rows = await _db_query(
        'SELECT COUNT(r.Score) AS vote_count, p.Login, p.NickName '
        'FROM rs_karma r, players p '
        'WHERE r.PlayerId=p.Id '
        'GROUP BY r.PlayerId ORDER BY vote_count DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_VOTERS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_VOTERS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        score = str(int(row[0] or 0))
        nick  = str(row[2] or row[1] or '?')
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_visitors_widget(aseco: 'Aseco') -> str:
    cfg = _state.stl_top_visitors
    if not cfg.get('enabled', True):
        return _stl_empty(ML_TOP_VISITORS)

    entries = int(cfg.get('entries', 7))
    rows = await _db_query(
        'SELECT pe.visits, p.Login, p.NickName '
        'FROM players_extra pe LEFT JOIN players p ON pe.playerID=p.Id '
        'WHERE visits>0 ORDER BY visits DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_VISITORS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_VISITORS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        score = str(int(row[0] or 0))
        nick  = str(row[2] or row[1] or '?')
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_roundscore_widget(aseco: 'Aseco') -> str:
    cfg = getattr(_state, 'stl_top_roundscore', {})
    if not cfg.get('enabled', False):
        return _stl_empty(ML_TOP_ROUNDSCORE)

    entries = int(cfg.get('entries', 7))
    rows = await _db_query(
        'SELECT pe.roundpoints, p.Login, p.NickName '
        'FROM players_extra pe LEFT JOIN players p ON pe.playerID=p.Id '
        'WHERE RoundPoints>0 ORDER BY RoundPoints DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_ROUNDSCORE)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_ROUNDSCORE, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        score = str(int(row[0] or 0))
        nick  = str(row[2] or row[1] or '?')
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_winning_payouts_widget(aseco: 'Aseco') -> str:
    cfg = getattr(_state, 'stl_top_winning_payouts', {})
    if not cfg.get('enabled', False):
        return _stl_empty(ML_TOP_WINNING_PAYOUTS)

    entries = int(cfg.get('entries', 7))
    rows = await _db_query(
        'SELECT pe.winningpayout, p.Login, p.NickName '
        'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
        'WHERE pe.winningpayout>0 AND p.NickName IS NOT NULL '
        'ORDER BY pe.winningpayout DESC LIMIT %s', (entries,))

    if not rows:
        return _stl_empty(ML_TOP_WINNING_PAYOUTS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_WINNING_PAYOUTS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        score = f'{int(row[0] or 0)} C'
        nick  = str(row[2] or row[1] or '?')
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


async def build_top_active_players_widget(aseco: 'Aseco') -> str:
    cfg = getattr(_state, 'stl_top_active_players', {})
    if not cfg.get('enabled', False):
        return _stl_empty(ML_TOP_ACTIVE_PLAYERS)

    entries = int(cfg.get('entries', 7))
    today = date.today().strftime('%Y-%m-%d %H:%M:%S')
    rows = await _db_query(
        f'SELECT Login, NickName, DATEDIFF(%s, UpdatedAt) AS Days '
        f'FROM players WHERE Wins>0 ORDER BY UpdatedAt DESC LIMIT %s',
        (today, entries))

    if not rows:
        return _stl_empty(ML_TOP_ACTIVE_PLAYERS)

    fmt = getattr(_state.style, 'score_fmt_codes', '')
    sc  = getattr(_state.style, 'score_col_scores', 'DDDF')
    lh  = _state.line_height
    p   = [_stl_header(ML_TOP_ACTIVE_PLAYERS, cfg, min(len(rows), entries))]
    for i, row in enumerate(rows[:entries]):
        nick = str(row[1] or row[0] or '?')
        days = int(row[2] or 0)
        score = 'Today' if days == 0 else f'-{days} d'
        p.append(_stl_row_score_nick(i, score, nick, lh, fmt, sc))
    p.append(_stl_footer())
    return ''.join(p)


# ---------------------------------------------------------------------------
# Broadcast all score-column widgets at onEndRace
# ---------------------------------------------------------------------------

async def draw_all_score_columns(aseco: 'Aseco') -> None:
    """Send all enabled score-screen toplist column widgets to everyone."""
    async def _bc(xml: str) -> None:
        await aseco.client.query_ignore_result('SendDisplayManialinkPage', xml, 0, False)

    await _bc(await build_top_rankings_widget(aseco))
    await _bc(await build_top_winners_widget(aseco))
    await _bc(await build_most_records_widget(aseco))
    await _bc(await build_most_finished_widget(aseco))
    await _bc(await build_top_playtime_widget(aseco))
    await _bc(await build_top_donators_widget(aseco))
    await _bc(await build_top_nations_widget(aseco))
    await _bc(await build_top_tracks_widget(aseco))
    await _bc(await build_top_voters_widget(aseco))
    await _bc(await build_top_visitors_widget(aseco))
    await _bc(await build_top_roundscore_widget(aseco))
    await _bc(await build_top_winning_payouts_widget(aseco))
    await _bc(await build_top_active_players_widget(aseco))


async def hide_all_score_columns(aseco: 'Aseco') -> None:
    """Hide all score-screen toplist column widgets."""
    ids = (ML_TOP_RANKINGS, ML_TOP_WINNERS, ML_MOST_RECORDS, ML_MOST_FINISHED,
           ML_TOP_PLAYTIME, ML_TOP_DONATORS, ML_TOP_NATIONS, ML_TOP_TRACKS,
           ML_TOP_VOTERS, ML_TOP_VISITORS, ML_TOP_ROUNDSCORE,
           ML_TOP_WINNING_PAYOUTS, ML_TOP_ACTIVE_PLAYERS)
    combined = ''.join(f'<manialink id="{mid}"></manialink>' for mid in ids)
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', combined, 0, False)


# ---------------------------------------------------------------------------
# Popup windows (opened by clicking bar widgets) — single-login send
# ---------------------------------------------------------------------------


async def _query_toplist_rows(aseco: 'Aseco', key: str, limit: int = 100) -> list[tuple]:
    if key == 'TOPRANKS':
        return await _db_query(
            'SELECT p.Login, p.NickName, r.avg '
            'FROM players p LEFT JOIN rs_rank r ON p.Id=r.PlayerId '
            'WHERE r.avg!=0 ORDER BY r.avg ASC LIMIT %s', (limit,))
    if key == 'TOPNATIONS':
        return await _db_query(
            'SELECT COUNT(Nation) AS Count, Nation FROM players '
            'GROUP BY Nation ORDER BY Count DESC LIMIT %s', (limit,))
    if key == 'TOPWINNERS':
        return await _db_query(
            'SELECT Login, NickName, Wins FROM players '
            'WHERE Wins>0 ORDER BY Wins DESC LIMIT %s', (limit,))
    if key == 'MOSTRECORDS':
        return await _db_query(
            'SELECT p.Login, p.NickName, pe.mostrecords '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.mostrecords>0 ORDER BY pe.mostrecords DESC LIMIT %s', (limit,))
    if key == 'MOSTFINISHED':
        return await _db_query(
            'SELECT p.Login, p.NickName, pe.mostfinished '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.mostfinished>0 ORDER BY pe.mostfinished DESC LIMIT %s', (limit,))
    if key == 'TOPPLAYTIME':
        return await _db_query(
            'SELECT Login, NickName, TimePlayed FROM players '
            'WHERE TimePlayed>3600 ORDER BY TimePlayed DESC LIMIT %s', (limit,))
    if key == 'TOPDONATORS':
        return await _db_query(
            'SELECT p.Login, p.NickName, pe.donations '
            'FROM players p LEFT JOIN players_extra pe ON p.Id=pe.playerID '
            'WHERE pe.donations!=0 ORDER BY pe.donations DESC LIMIT %s', (limit,))
    if key == 'TOPTRACKS':
        return await _db_query(
            'SELECT c.Name, '
            'SUM(CASE WHEN k.Score>0 THEN 1 ELSE 0 END) - SUM(CASE WHEN k.Score<0 THEN 1 ELSE 0 END) AS karma, '
            'COUNT(k.Score) AS votes '
            'FROM rs_karma k LEFT JOIN challenges c ON c.Id=k.ChallengeId '
            'WHERE c.Name IS NOT NULL '
            'GROUP BY k.ChallengeId '
            'HAVING karma >= 1 '
            'ORDER BY karma DESC LIMIT %s', (limit,))
    if key == 'TOPVOTERS':
        return await _db_query(
            'SELECT p.Login, p.NickName, COUNT(k.Id) AS votes '
            'FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId '
            'GROUP BY k.PlayerId ORDER BY votes DESC LIMIT %s', (limit,))
    if key == 'TOPVISITORS':
        return await _db_query(
            'SELECT pe.visits, p.Login, p.NickName '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.visits>0 ORDER BY pe.visits DESC LIMIT %s', (limit,))
    if key == 'TOPACTIVE':
        today = date.today().strftime('%Y-%m-%d %H:%M:%S')
        return await _db_query(
            'SELECT Login, NickName, DATEDIFF(%s, UpdatedAt) AS Days '
            'FROM players WHERE Wins>0 ORDER BY UpdatedAt DESC LIMIT %s', (today, limit))
    if key == 'TOPROUNDSCORE':
        return await _db_query(
            'SELECT p.Login, p.NickName, pe.roundpoints '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.roundpoints>0 ORDER BY pe.roundpoints DESC LIMIT %s', (limit,))
    if key == 'TOPWINNINGPAYOUTS':
        return await _db_query(
            'SELECT p.Login, p.NickName, pe.winningpayout '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.winningpayout>0 ORDER BY pe.winningpayout DESC LIMIT %s', (limit,))
    return []


def _build_toplist_window_entry(title: str, icon_style: str, icon_substyle: str, action_id: int,
                                rows: list[dict], *, special_nations: bool = False, special_suffix: str | bool = False) -> str:
    st = _state.style
    fmt = getattr(st, 'score_fmt_codes', '')
    score_col = getattr(st, 'score_col_scores', 'DDDF')
    hi_style = escape(getattr(st, 'hi_other_style', 'BgsPlayerCard'))
    hi_sub = escape(getattr(st, 'hi_other_sub', 'BgRacePlayerName'))
    p: list[str] = []
    p.append('<format textsize="1" textcolor="FFFF"/>')
    p.append('<quad posn="0 0 0.02" sizen="17.75 46.88" style="BgsPlayerCard" substyle="BgRacePlayerName"/>')
    p.append(f'<quad posn="14.15 -43.33 0.03" sizen="4 4" action="{action_id}" style="Icons64x64_1" substyle="TrackInfo"/>')
    p.append('<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="BgsPlayerCard" substyle="ProgressBar"/>')
    p.append(f'<quad posn="0.6 0 0.05" sizen="2.5 2.5" style="{escape(icon_style)}" substyle="{escape(icon_substyle)}"/>')
    p.append(f'<label posn="3.2 -0.55 0.05" sizen="17.3 0" textsize="1" text="{escape(title)}"/>')
    if rows:
        p.append('<frame posn="0 -2.7 0.04">')
        for idx, item in enumerate(rows[:25], start=1):
            line = idx - 1
            if special_nations:
                code = str(item.get('nation') or 'OTH')
                count = str(item.get('score') or '0')
                nation_name = str(item.get('nickname') or code)
                flag_y = 0.3 if line == 0 else -(1.75 * line - 0.3)
                p.append(f'<label posn="3.15 -{1.75 * line:.2f} 0.02" sizen="2.65 1.7" halign="right" scale="0.9" textcolor="{escape(score_col)}" text="{escape(fmt)}{escape(count)}"/>')
                p.append(f'<quad posn="3.9 {flag_y:.2f} 0.02" sizen="2 2" image="{escape(_flag_path(code))}"/>')
                p.append(f'<label posn="6.6 -{1.75 * line:.2f} 0.02" sizen="11.2 1.7" scale="0.9" text="{escape(fmt)}{escape(nation_name)}"/>')
            else:
                rank = str(item.get('rank', idx))
                score = str(item.get('score', ''))
                if special_suffix not in (False, None, ''):
                    score += str(special_suffix)
                nick = _clip(_sanitise_nick(str(item.get('nickname', '?'))), 40)
                if item.get('online'):
                    y_bg = (((1.75 * line - 0.2) > 0) and -(1.75 * line - 0.2) or 0.2)
                    p.append(f'<quad posn="0.4 {y_bg:.2f} 0.01" sizen="16.95 1.83" style="{hi_style}" substyle="{hi_sub}"/>')
                p.append(f'<label posn="2.6 -{1.75 * line:.2f} 0.02" sizen="2 1.7" halign="right" scale="0.9" text="{rank}."/>')
                p.append(f'<label posn="6.4 -{1.75 * line:.2f} 0.02" sizen="4 1.7" halign="right" scale="0.9" textcolor="{escape(score_col)}" text="{escape(fmt)}{escape(score)}"/>')
                p.append(f'<label posn="6.9 -{1.75 * line:.2f} 0.02" sizen="11.2 1.7" scale="0.9" text="{escape(nick)}"/>')
        p.append('</frame>')
    return ''.join(p)


async def _build_toplist_window(aseco: 'Aseco', login: str, page: int = 0) -> str:
    players = [p.login for p in aseco.server.players.all()]
    gamemode = getattr(aseco.server.gameinfo, 'mode', -1)

    toplists: list[dict] = []

    async def add_generic(
        *,
        manialinkid: str,
        title: str,
        icon_style: str,
        icon_substyle: str,
        key: str,
        action_id: int,
        special: bool | str = False,
    ) -> None:
        rows = await _query_toplist_rows(aseco, key, 100)
        if not rows:
            return

        parsed: list[dict] = []
        mode = _effective_mode(aseco)
        is_stunts = (mode == Gameinfo.STNT)

        if key == 'TOPNATIONS':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (count, nation)
                count = int(row[0] or 0)
                code = str(row[1] or 'OTH')
                parsed.append({
                    'rank': idx,
                    'score': str(count),
                    'nation': code,
                    'nickname': _country_name(aseco, code),
                })

        elif key == 'TOPTRACKS':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (challenge_name, karma, votes)
                parsed.append({
                    'rank': idx,
                    'score': str(int(row[1] or 0)),
                    'nickname': _sanitise_nick(str(row[0] or '?')),
                    'login': '',
                    'online': False,
                })

        elif key == 'TOPVISITORS':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (visits, login, nickname)
                visits = str(int(row[0] or 0))
                login_id = str(row[1] or '')
                nick = _sanitise_nick(str(row[2] or login_id or '?'))
                parsed.append({
                    'rank': idx,
                    'score': visits,
                    'nickname': nick,
                    'login': login_id,
                    'online': login_id in players,
                })

        elif key == 'TOPPLAYTIME':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (login, nickname, seconds)
                login_id = str(row[0] or '')
                nick = _sanitise_nick(str(row[1] or login_id or '?'))
                hours = str(round(int(row[2] or 0) / 3600))
                parsed.append({
                    'rank': idx,
                    'score': hours,
                    'nickname': nick,
                    'login': login_id,
                    'online': login_id in players,
                })

        elif key == 'TOPRANKS':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (login, nickname, avg)
                login_id = str(row[0] or '')
                nick = _sanitise_nick(str(row[1] or login_id or '?'))
                score = f'{float(row[2] or 0) / 10000:.1f}'
                parsed.append({
                    'rank': idx,
                    'score': score,
                    'nickname': nick,
                    'login': login_id,
                    'online': login_id in players,
                })

        elif key == 'TOPACTIVE':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (login, nickname, days)
                login_id = str(row[0] or '')
                nick = _sanitise_nick(str(row[1] or login_id or '?'))
                days = int(row[2] or 0)
                score = 'Today' if days == 0 else f'-{days} d'
                parsed.append({
                    'rank': idx,
                    'score': score,
                    'nickname': nick,
                    'login': login_id,
                    'online': login_id in players,
                })

        elif key == 'TOPDONATORS':
            for idx, row in enumerate(rows[:25], start=1):
                # row = (login, nickname, donations)
                login_id = str(row[0] or '')
                nick = _sanitise_nick(str(row[1] or login_id or '?'))
                score = str(int(row[2] or 0))
                parsed.append({
                    'rank': idx,
                    'score': score,
                    'nickname': nick,
                    'login': login_id,
                    'online': login_id in players,
                })

        else:
            for idx, row in enumerate(rows[:25], start=1):
                # default row = (login, nickname, score)
                login_id = str(row[0] or '')
                nick = _sanitise_nick(str(row[1] or login_id or '?'))
                score = str(row[2] if len(row) > 2 else '')
                parsed.append({
                    'rank': idx,
                    'score': score,
                    'nickname': nick,
                    'login': login_id,
                    'online': login_id in players,
                })

        toplists.append({
            'manialinkid': manialinkid,
            'icon_style': icon_style,
            'icon_substyle': icon_substyle,
            'title': title,
            'rows': parsed,
            'special': special,
            'action_id': action_id,
        })

    # Preserve the expected display order.
    dedi_cfg = _state.dedi.get(_effective_mode(aseco))
    if gamemode != Gameinfo.STNT and getattr(dedi_cfg, 'enabled', False):
        from .widgets.records_dedi import _get_dedi_records
        dedi_rows = []

        for idx, rec in enumerate((_get_dedi_records() or [])[:25], start=1):
            if not isinstance(rec, dict):
                continue

            login_id = str(rec.get('login') or rec.get('Login') or '')
            raw_score = rec.get('score')
            if raw_score is None:
                raw_score = rec.get('Best') or rec.get('Score')

            score_text = rec.get('score_text')
            if not score_text:
                try:
                    score_text = format_time(int(raw_score or 0))
                except Exception:
                    score_text = '--'

            dedi_rows.append({
    # Number these rows sequentially in the More Ranking window.
                'rank': idx,
                'score': str(score_text or '--'),
                'nickname': _sanitise_nick(str(rec.get('nickname') or rec.get('NickName') or login_id or '?')),
                'login': login_id,
                'online': login_id in players,
            })
        toplists.append({
            'manialinkid': '04',
            'icon_style': 'Icons128x128_1',
            'icon_substyle': 'Rankings',
            'title': getattr(dedi_cfg, 'title', 'Dedimania Records'),
            'rows': dedi_rows,
            'special': False,
            'action_id': 91804,
        })

    # Local Records
    local_rows_raw = list(getattr(aseco.server, 'records', []) or [])
    local_rows = []
    mode = _effective_mode(aseco)
    is_stunts = (mode == Gameinfo.STNT)

    for idx, rec in enumerate(local_rows_raw[:25], start=1):
        login_id = rec.player.login if rec.player else ''
        raw = int(rec.score or 0)
        score = str(raw) if is_stunts else format_time(raw)
        local_rows.append({
            'rank': idx,
            'score': score,
            'nickname': _sanitise_nick(rec.player.nickname if rec.player else '?'),
            'login': login_id,
            'online': login_id in players,
        })
    toplists.append({
        'manialinkid': '05',
        'icon_style': 'Icons128x128_1',
        'icon_substyle': 'Rankings',
        'title': getattr(_state.local.get(_effective_mode(aseco)), 'title', 'Local Records'),
        'rows': local_rows,
        'special': False,
        'action_id': 91805,
    })

    await add_generic(
        manialinkid='10',
        title='Top Rankings',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPRANKS',
        action_id=91810,
    )
    await add_generic(
        manialinkid='11',
        title='Top Winners',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPWINNERS',
        action_id=91811,
    )
    await add_generic(
        manialinkid='12',
        title='Most Records',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='MOSTRECORDS',
        action_id=91812,
    )
    await add_generic(
        manialinkid='13',
        title='Most Finished',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='MOSTFINISHED',
        action_id=91813,
    )
    await add_generic(
        manialinkid='14',
        title='Hours Played',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPPLAYTIME',
        action_id=91814,
    )
    await add_generic(
        manialinkid='98',
        title='Top Active Players',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPACTIVE',
        action_id=91898,
    )
    await add_generic(
        manialinkid='159',
        title='Top Visitors',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPVISITORS',
        action_id=918159,
    )
    await add_generic(
        manialinkid='09',
        title='Top Nations',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPNATIONS',
        action_id=91809,
        special=True,
    )
    await add_generic(
        manialinkid='17',
        title='Top Voters',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPVOTERS',
        action_id=91817,
    )
    await add_generic(
        manialinkid='16',
        title='Top Tracks',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPTRACKS',
        action_id=91816,
    )
    await add_generic(
        manialinkid='15',
        title='Top Donators',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        key='TOPDONATORS',
        action_id=91815,
        special=' C',
    )

    total_pages = max(1, (len(toplists) + 3) // 4)
    page = max(0, min(page, total_pages - 1))

    buttons = '<frame posn="67.05 -53.2 0">'
    if page > 0:
        buttons += f'<quad posn="4.95 6 0.12" sizen="3.2 3.2" action="-{9187250 + page - 1}" style="Icons64x64_1" substyle="ArrowPrev"/>'
    else:
        buttons += '<quad posn="4.95 6 0.12" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        buttons += '<quad posn="4.95 6 0.13" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'

    if page < total_pages - 1:
        buttons += f'<quad posn="8.25 6 0.12" sizen="3.2 3.2" action="{9187250 + page + 1}" style="Icons64x64_1" substyle="ArrowNext"/>'
    else:
        buttons += '<quad posn="8.25 6 0.12" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        buttons += '<quad posn="8.25 6 0.13" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
    buttons += '</frame>'

    p: list[str] = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title=f'Top Rankings   |   Page {page + 1}/{total_pages}',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        content_frame_pos='2.5 -5.7 1',
    )
    p.append(buttons)

    pos = 0
    for idx in range(page * 4, page * 4 + 4):
        if idx >= len(toplists):
            break
        tl = toplists[idx]
        p.append(f'<frame posn="{19.05 * pos:.2f} 0 1">')
        p.append(_build_toplist_window_entry(
            tl['title'],
            tl['icon_style'],
            tl['icon_substyle'],
            tl['action_id'],
            tl['rows'],
            special_nations=(tl['special'] is True),
            special_suffix=(tl['special'] if isinstance(tl['special'], str) else False),
        ))
        p.append('</frame>')
        pos += 1

    append_window_end(p)
    return ''.join(p)


async def _build_generic_toplist_window(
    aseco: 'Aseco',
    key: str,
) -> str:
    LIMIT = 100

    title: str
    entries: list[tuple[str, str]] = []

    async def _fetch(sql: str, params: tuple = ()) -> list[tuple]:
        return await _db_query(sql, params)

    if key == 'TOPRANKS':
        title = 'Top Rankings'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, r.avg '
            'FROM players p LEFT JOIN rs_rank r ON p.Id=r.PlayerId '
            'WHERE r.avg!=0 ORDER BY r.avg ASC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), f'{float(r[2] or 0) / 10000:.1f}') for r in rows]

    elif key == 'TOPWINNERS':
        title = 'Top Winners'
        rows = await _fetch(
            'SELECT Login, NickName, Wins FROM players '
            'WHERE Wins>0 ORDER BY Wins DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int(r[2] or 0))) for r in rows]

    elif key == 'MOSTRECORDS':
        title = 'Most Records'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, pe.mostrecords '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.mostrecords>0 ORDER BY pe.mostrecords DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int(r[2] or 0))) for r in rows]

    elif key == 'MOSTFINISHED':
        title = 'Most Finished'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, pe.mostfinished '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.mostfinished>0 ORDER BY pe.mostfinished DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int(r[2] or 0))) for r in rows]

    elif key == 'TOPPLAYTIME':
        title = 'Hours Played'
        rows = await _fetch(
            'SELECT Login, NickName, TimePlayed FROM players '
            'WHERE TimePlayed>3600 ORDER BY TimePlayed DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int((int(r[2] or 0) + 1800) // 3600))) for r in rows]

    elif key == 'TOPDONATORS':
        title = 'Top Donators'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, pe.donations '
            'FROM players p LEFT JOIN players_extra pe ON p.Id=pe.playerID '
            'WHERE pe.donations!=0 ORDER BY pe.donations DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), f"{int(r[2] or 0)} C") for r in rows]

    elif key == 'TOPTRACKS':
        title = 'Top Tracks'
        rows = await _fetch(
            'SELECT c.Name, AVG(k.Score) AS avgscore '
            'FROM rs_karma k LEFT JOIN challenges c ON c.Id=k.ChallengeId '
            'WHERE c.Name IS NOT NULL GROUP BY k.ChallengeId ORDER BY avgscore DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[0] or '?'), str(int(r[1] or 0))) for r in rows]

    elif key == 'TOPROUNDSCORE':
        title = 'Top Roundscore'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, pe.roundpoints '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.roundpoints>0 ORDER BY pe.roundpoints DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int(r[2] or 0))) for r in rows]

    elif key == 'TOPWINNINGPAYOUTS':
        title = 'Top Winning Payouts'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, pe.winningpayout '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE pe.winningpayout>0 ORDER BY pe.winningpayout DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int(r[2] or 0))) for r in rows]

    elif key == 'TOPVOTERS':
        title = 'Top Voters'
        rows = await _fetch(
            'SELECT p.Login, p.NickName, COUNT(k.Id) AS votes '
            'FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId '
            'GROUP BY k.PlayerId ORDER BY votes DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[1] or r[0]), str(int(r[2] or 0))) for r in rows]

    elif key == 'TOPVISITORS':
        title = 'Top Visitors'
        rows = await _fetch(
            'SELECT pe.visits, p.Login, p.NickName '
            'FROM players_extra pe LEFT JOIN players p ON p.Id=pe.playerID '
            'WHERE visits>0 ORDER BY visits DESC LIMIT %s', (LIMIT,))
        entries = [(str(r[2] or r[1]), str(int(r[0] or 0))) for r in rows]

    elif key == 'TOPACTIVE':
        title = 'Top Active Players'
        today = date.today().strftime('%Y-%m-%d %H:%M:%S')
        rows = await _fetch(
            'SELECT Login, NickName, DATEDIFF(%s, UpdatedAt) AS Days '
            'FROM players WHERE Wins>0 ORDER BY UpdatedAt DESC LIMIT %s',
            (today, LIMIT))
        entries = [
            (str(r[1] or r[0]), 'Today' if int(r[2] or 0) == 0 else f'-{int(r[2])} d')
            for r in rows
        ]

    else:
        return ''

    if not entries:
        return ''

    cols = [entries[0:25], entries[25:50], entries[50:75], entries[75:100]]

    p: list[str] = []
    append_window_start(
        p, ml_window=ML_WINDOW, ml_subwin=ML_SUBWIN,
        title=title,
        icon_style='Icons128x128_1', icon_substyle='Rankings',
        content_frame_pos='2.5 -5.7 0.05',
    )
    p.append(f'<format textsize="1" textcolor="{escape(getattr(_state.style, "col_default", "FFFF"))}"/>')
    append_four_player_columns(p)

    x_offsets = [0.0, 19.05, 38.10, 57.15]
    for x_off, col in zip(x_offsets, cols):
        for line, (nick, score) in enumerate(col[:25]):
            y = 1.83 * line
            p.append(
                f'<label posn="{2.75+x_off:.2f} -{y:.2f} 0.03"'
                f' sizen="2.5 1.7" halign="right" scale="0.9" textsize="1"'
                f' text="{escape(score)}"/>'
            )
            p.append(
                f'<label posn="{6.2+x_off:.2f} -{y:.2f} 0.03"'
                f' sizen="11.2 1.7" scale="0.9" textsize="1"'
                f' text="{escape(nick)}"/>'
            )

    append_window_end(p)
    return ''.join(p)


async def _build_top_nations_window(aseco: 'Aseco') -> str:
    rows: list[tuple[str, int]] = []
    _FLAGFIX = {'SCG': 'SRB', 'ROM': 'ROU', 'CAR': 'CMR'}
    try:
        data = await _db_query(
            'SELECT COALESCE(NULLIF(Nation,""),"OTH") AS NationCode, COUNT(*) AS Cnt '
            'FROM players GROUP BY NationCode ORDER BY Cnt DESC LIMIT 100')
        rows = [(_FLAGFIX.get(str(r[0] or 'OTH').upper(), str(r[0] or 'OTH').upper()),
                 int(r[1] or 0)) for r in data]
    except Exception as exc:
        logger.warning('[Records-Eyepiece] Top Nations window DB query failed: %r', exc)

    cols = [rows[0:25], rows[25:50], rows[50:75], rows[75:100]]
    p: list[str] = []
    append_window_start(
        p, ml_window=ML_WINDOW, ml_subwin=ML_SUBWIN,
        title='Top Nations',
        icon_style='Icons128x128_1', icon_substyle='Rankings',
        content_frame_pos='2.5 -5.7 0.05',
    )
    p.append('<format textsize="1" textcolor="FFFF"/>')
    append_four_player_columns(p)

    x_offsets = [0.0, 19.05, 38.10, 57.15]
    for x_off, block in zip(x_offsets, cols):
        for line, (code, count) in enumerate(block):
            y      = 1.83 * line
            flag_y = 0.3 if line == 0 else -(1.83 * line - 0.3)
            p.append(
                f'<label posn="{2.75+x_off:.2f} -{y:.2f} 0.03"'
                f' sizen="2.5 1.7" halign="right" scale="0.9" textsize="1" text="{count}"/>'
            )
            p.append(
                f'<quad posn="{3.5+x_off:.2f} {flag_y:.2f} 0.03"'
                f' sizen="2 2" image="{escape(_flag_path(code))}"/>'
            )
            p.append(
                f'<label posn="{6.2+x_off:.2f} -{y:.2f} 0.03"'
                f' sizen="11.2 1.7" scale="0.9" textsize="1"'
                f' text="{escape(_country_name(aseco, code))}"/>'
            )

    append_window_end(p)
    return ''.join(p)
