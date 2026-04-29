"""
widgets/score_widgets.py — Phase 3 & 4 score-state widgets for Records-Eyepiece.

Phase 3:  RoundScoreWidget (ML 91831)
Phase 4:  ScoreTable list widgets shown at score screen:
            LocalRecordsForScore  (ML 91816)
            DediRecordsForScore   (ML 91815)
            TopAverageTimesForScore (ML 91834)
            DonationWidget        (ML 91843)
            WinningPayoutWidget   (ML 91842)

All score-state widgets are sent on onEndRace and hidden on onEndRace1/onNewChallenge.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from ..config import _state, _effective_mode
from ..utils import _clip, _sanitise_nick

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Manialink IDs
# ---------------------------------------------------------------------------
ML_ROUND_SCORE          = 91831
ML_LOCAL_SCORE          = 91816
ML_DEDI_SCORE           = 91815
ML_AVG_TIMES            = 91834
ML_DONATION             = 91843
ML_WINNING_PAYOUT       = 91842

# Map gamemode int -> XML tag name used in config
_GM_TAG = {
    Gameinfo.RNDS: 'rounds',
    Gameinfo.TA:   'time_attack',
    Gameinfo.TEAM: 'team',
    Gameinfo.LAPS: 'laps',
    Gameinfo.STNT: 'stunts',
    Gameinfo.CUP:  'cup',
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _empty(ml_id: int) -> str:
    return f'<manialink id="{ml_id}"></manialink>'


async def _broadcast(aseco: 'Aseco', xml: str) -> None:
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', xml, 0, False)


def _scoretable_header(ml_id: int, cfg: dict, widget_height: float) -> str:
    """
    Build the standard scoretable-list widget header.
    """
    st = _state.style
    # Score widget uses its own bg/title style fields stored in style_score_*
    bg_style    = getattr(st, 'score_bg_style',    'BgsPlayerCard')
    bg_sub      = getattr(st, 'score_bg_substyle', 'BgRacePlayerName')
    title_style = getattr(st, 'score_title_style', 'BgsPlayerCard')
    title_sub   = getattr(st, 'score_title_sub',   'ProgressBar')
    col_default = getattr(st, 'score_col_default',  'FFFF')

    px  = cfg.get('pos_x', 0.0)
    py  = cfg.get('pos_y', 0.0)
    ist = escape(cfg.get('icon_style', 'Icons128x128_1'))
    iss = escape(cfg.get('icon_substyle', 'Rankings'))
    ttl = escape(cfg.get('title', ''))

    p = []
    p.append(f'<manialink id="{ml_id}">')
    p.append(f'<frame posn="{px:.2f} {py:.2f} 0">')
    p.append(f'<quad posn="0 0 0.001" sizen="15.5 {widget_height:.2f}"'
             f' style="{bg_style}" substyle="{bg_sub}"/>')
    # Title bar
    p.append(f'<quad posn="0.4 -0.36 0.002" sizen="14.7 2"'
             f' style="{title_style}" substyle="{title_sub}"/>')
    p.append(f'<quad posn="0.6 -0.15 0.004" sizen="2.5 2.5"'
             f' style="{ist}" substyle="{iss}"/>')
    p.append(f'<label posn="3.2 -0.55 0.004" sizen="10.2 0"'
             f' textsize="1" text="{ttl}"/>')
    p.append(f'<format textsize="1" textcolor="{col_default}"/>')
    return ''.join(p)


def _scoretable_footer() -> str:
    return '</frame></manialink>'


def _scoretable_row(line: int, rank: int, score_text: str, nick: str,
                    score_color: str, fmt: str, lh: float) -> str:
    """Single entry row"""
    offset = 3.0
    y = lh * line + offset
    fc = escape(fmt)
    sc = escape(score_color)
    st_score = escape(score_text)
    st_nick  = escape(nick)
    p = []
    p.append(f'<label posn="2.1 -{y:.2f} 0.002" sizen="1.7 1.7"'
             f' halign="right" scale="0.9"'
             f' text="{fc}{rank}."/>')
    p.append(f'<label posn="5.7 -{y:.2f} 0.002" sizen="3.8 1.7"'
             f' halign="right" scale="0.9" textcolor="{sc}"'
             f' text="{fc}{st_score}"/>')
    p.append(f'<label posn="5.9 -{y:.2f} 0.002" sizen="10.2 1.7"'
             f' scale="0.9"'
             f' text="{fc}{st_nick}"/>')
    return ''.join(p)


def _get_score_cfg(key: str) -> dict:
    """Return scoretable-list config dict for a given key (e.g. 'local_records')."""
    return getattr(_state, f'stl_{key}', {})


# ---------------------------------------------------------------------------
# Phase 4a — LocalRecordsForScore (ML 91816)
# ---------------------------------------------------------------------------

def build_local_records_for_score(aseco: 'Aseco') -> str:
    cfg = _get_score_cfg('local_records')
    if not cfg.get('enabled', True):
        return _empty(ML_LOCAL_SCORE)

    mode = _effective_mode(aseco)
    is_stnt = (mode == Gameinfo.STNT)
    lh     = _state.line_height
    entries= int(cfg.get('entries', 8))
    fmt    = getattr(_state.style, 'score_fmt_codes', '')
    sc     = getattr(_state.style, 'score_col_scores', 'DDDF')

    # Collect records from server
    records = []
    try:
        rlist = aseco.server.records
        count = rlist.count() if hasattr(rlist, 'count') else len(getattr(rlist, 'record_list', []))
        for i in range(min(count, entries)):
            rec = rlist.get_record(i) if hasattr(rlist, 'get_record') else getattr(rlist, 'record_list', [])[i]
            if not rec:
                continue
            score = getattr(rec, 'score', 0) or 0
            nick  = getattr(getattr(rec, 'player', None), 'nickname', '?') or '?'
            score_text = str(int(score)) if is_stnt else format_time(int(score))
            records.append((i + 1, score_text, nick))
    except Exception as e:
        logger.debug('[RE] LocalRecordsForScore: %s', e)

    if not records:
        return _empty(ML_LOCAL_SCORE)

    widget_height = lh * min(len(records), entries) + 3.3
    p = [_scoretable_header(ML_LOCAL_SCORE, cfg, widget_height)]
    for idx, (rank, score_text, nick) in enumerate(records[:entries]):
        p.append(_scoretable_row(idx, rank, score_text, nick, sc, fmt, lh))
    p.append(_scoretable_footer())
    return ''.join(p)


# ---------------------------------------------------------------------------
# Phase 4b — DediRecordsForScore (ML 91815)
# ---------------------------------------------------------------------------

def build_dedi_records_for_score(aseco: 'Aseco') -> str:
    cfg = _get_score_cfg('dedimania_records')
    if not cfg.get('enabled', True):
        return _empty(ML_DEDI_SCORE)

    lh     = _state.line_height
    entries= int(cfg.get('entries', 8))
    fmt    = getattr(_state.style, 'score_fmt_codes', '')
    sc     = getattr(_state.style, 'score_col_scores', 'DDDF')

    records = []
    try:
        from .records_dedi import _get_dedi_records

        for i, rec in enumerate(_get_dedi_records() or []):
            if not isinstance(rec, dict):
                continue
            nick = str(rec.get('nickname') or rec.get('NickName') or rec.get('login') or rec.get('Login') or '?')
            score_text = str(rec.get('score_text') or '')
            if not score_text:
                best = int(rec.get('Best') or rec.get('Score') or rec.get('score') or 0)
                if best <= 0:
                    continue
                score_text = format_time(best)
            records.append((i + 1, score_text, nick))
            if len(records) >= entries:
                break
    except Exception as e:
        logger.debug('[RE] DediRecordsForScore: %s', e)

    if not records:
        return _empty(ML_DEDI_SCORE)

    widget_height = lh * len(records) + 3.3
    p = [_scoretable_header(ML_DEDI_SCORE, cfg, widget_height)]
    for idx, (rank, score_text, nick) in enumerate(records):
        p.append(_scoretable_row(idx, rank, score_text, nick, sc, fmt, lh))
    p.append(_scoretable_footer())
    return ''.join(p)


# ---------------------------------------------------------------------------
# Phase 4c — TopAverageTimesForScore (ML 91834)
# ---------------------------------------------------------------------------

def build_avg_times_for_score(aseco: 'Aseco') -> str:
    cfg = _get_score_cfg('top_average_times')
    if not cfg.get('enabled', True):
        return _empty(ML_AVG_TIMES)

    mode    = _effective_mode(aseco)
    is_stnt = (mode == Gameinfo.STNT)
    lh      = _state.line_height
    entries = int(cfg.get('entries', 9))
    fmt     = getattr(_state.style, 'score_fmt_codes', '')
    sc      = getattr(_state.style, 'score_col_scores', 'DDDF')

    # avg_times: dict[login -> list[int]] accumulated in events
    avg_times = getattr(_state, 'avg_times', {})

    if not avg_times:
        return _empty(ML_AVG_TIMES)

    # Build averages keyed by login
    data = []
    for login, times in avg_times.items():
        if not times:
            continue
        avg = int(sum(times) / len(times))
        # Find nickname from connected players
        player = aseco.server.players.get_player(login)
        nick = getattr(player, 'nickname', login) or login
        data.append({'score': avg, 'nickname': nick})

    if not data:
        return _empty(ML_AVG_TIMES)

    # Sort ascending (or descending for stunts)
    data.sort(key=lambda x: x['score'], reverse=is_stnt)

    widget_height = lh * min(len(data), entries) + 3.3
    p = [_scoretable_header(ML_AVG_TIMES, cfg, widget_height)]
    for idx, item in enumerate(data[:entries]):
        score_text = (str(item['score']) if is_stnt
                      else format_time(item['score']))
        p.append(_scoretable_row(idx, idx + 1, score_text,
                                 item['nickname'], sc, fmt, lh))
    p.append(_scoretable_footer())
    return ''.join(p)


# ---------------------------------------------------------------------------
# Phase 4d — DonationWidget (ML 91843)
# ---------------------------------------------------------------------------

def build_donation_widget(aseco: 'Aseco') -> str:
    cfg = getattr(_state, 'donation_cfg', {})
    if not cfg.get('enabled', False):
        return _empty(ML_DONATION)

    amounts  = cfg.get('amounts', [20, 50, 100, 200, 500, 1000])
    bg_style = cfg.get('bg_style', 'BgsPlayerCard')
    bg_sub   = cfg.get('bg_substyle', 'BgRacePlayerName')
    btn_style= cfg.get('button_style', 'Bgs1InRace')
    btn_sub  = cfg.get('button_substyle', 'BgIconBorder')
    btn_color= cfg.get('button_color', '000F')
    icon_sty = cfg.get('icon_style', 'Icons128x128_1')
    icon_sub = cfg.get('icon_substyle', 'Coppers')
    text_col = cfg.get('text_color', 'FC0F')
    px       = cfg.get('pos_x', -47.9)
    py       = cfg.get('pos_y', 18.2)

    widget_height = 6.55 + len(amounts) * 1.85

    p = []
    p.append(f'<manialink id="{ML_DONATION}">')
    p.append(f'<frame posn="{px:.2f} {py:.2f} 0">')
    p.append(f'<format textsize="1"/>')
    p.append(f'<quad posn="0 0 0.001" sizen="4.6 {widget_height:.2f}"'
             f' style="{escape(bg_style)}" substyle="{escape(bg_sub)}"/>')
    p.append(f'<quad posn="0.7 -0.3 0.002" sizen="3.2 2.7"'
             f' style="{escape(icon_sty)}" substyle="{escape(icon_sub)}"/>')
    p.append(f'<label posn="2.3 -3.4 0.1" sizen="3.65 2"'
             f' halign="center" scale="0.9" text="PLEASE"/>')
    p.append(f'<label posn="2.3 -4.9 0.1" sizen="6.35 2"'
             f' halign="center" textcolor="{escape(text_col)}"'
             f' scale="0.6" text="DONATE"/>')

    p.append(f'<format textsize="1" textcolor="{escape(btn_color)}"/>')
    offset = 6.75
    for i, amount in enumerate(amounts):
        row = i * 1.8
        action = 918165 + i
        p.append(f'<quad posn="0.2 -{offset+row:.2f} 0.2" sizen="4.2 1.7"'
                 f' action="{action}"'
                 f' style="{escape(btn_style)}" substyle="{escape(btn_sub)}"/>')
        p.append(f'<label posn="2.2 -{offset+row+0.35:.2f} 0.3"'
                 f' sizen="4 2.5" halign="center" scale="0.8"'
                 f' text="{amount}$n $mC"/>')

    p.append('</frame></manialink>')
    return ''.join(p)


# ---------------------------------------------------------------------------
# Phase 4e — WinningPayoutWidget (ML 91842)
# ---------------------------------------------------------------------------

def build_winning_payout_widget(aseco: 'Aseco') -> str:
    cfg = getattr(_state, 'winning_payout_cfg', {})
    if not cfg.get('enabled', False):
        return _empty(ML_WINNING_PAYOUT)

    mode = _effective_mode(aseco)
    if mode == Gameinfo.TEAM:
        return _empty(ML_WINNING_PAYOUT)

    lh       = _state.line_height
    st       = _state.style
    col_def  = getattr(st, 'score_col_default', 'FFFF')
    col_cop  = cfg.get('col_coppers', 'FF9F')
    col_won  = cfg.get('col_won', '5F0F')
    col_dis  = cfg.get('col_disconnected', 'F00F')

    px        = cfg.get('pos_x', 37.8)
    py        = cfg.get('pos_y', -30.7)
    bg_style  = cfg.get('bg_style', 'BgsPlayerCard')
    bg_sub    = cfg.get('bg_substyle', 'BgRacePlayerName')
    ttl_style = cfg.get('title_style', 'BgsPlayerCard')
    ttl_sub   = cfg.get('title_substyle', 'ProgressBar')
    icon_sty  = cfg.get('icon_style', 'BgRaceScore2')
    icon_sub  = cfg.get('icon_substyle', 'Fame')
    title     = escape(cfg.get('title', 'Finish Winners'))

    pay_first  = int(cfg.get('pay_first', 20))
    pay_second = int(cfg.get('pay_second', 15))
    pay_third  = int(cfg.get('pay_third', 10))
    payout_map = {1: pay_first, 2: pay_second, 3: pay_third}

    # Collect top 3 finishers from current ranking
    widget_height = lh * 3 + 3.4
    finishers = []
    try:
        ranking = await_ranking = getattr(aseco, '_re_last_ranking', [])
        for i, entry in enumerate(ranking[:3]):
            login    = entry.get('Login', '') if isinstance(entry, dict) else ''
            nick     = entry.get('NickName', login) if isinstance(entry, dict) else str(entry)
            best     = int((entry.get('BestTime', 0) or entry.get('Score', 0))
                           if isinstance(entry, dict) else 0)
            finishers.append({
                'rank': i + 1,
                'login': login,
                'nickname': nick,
                'won': payout_map.get(i + 1, 0),
                'best': best,
            })
    except Exception:
        pass

    p = []
    p.append(f'<manialink id="{ML_WINNING_PAYOUT}">')
    p.append(f'<frame posn="{px:.2f} {py:.2f} 0">')
    p.append(f'<quad posn="0 0 0.001" sizen="25.5 {widget_height:.2f}"'
             f' style="{escape(bg_style)}" substyle="{escape(bg_sub)}"/>')
    p.append(f'<quad posn="0.4 -0.36 0.002" sizen="24.7 2"'
             f' style="{escape(ttl_style)}" substyle="{escape(ttl_sub)}"/>')
    p.append(f'<quad posn="0.6 0 0.004" sizen="2.5 2.5"'
             f' style="{escape(icon_sty)}" substyle="{escape(icon_sub)}"/>')
    p.append(f'<label posn="3.2 -0.55 0.004" sizen="20.2 0"'
             f' textsize="1" text="{title}"/>')
    p.append(f'<format textsize="1" textcolor="{escape(col_def)}"/>')

    offset = 3.0
    for i, item in enumerate(finishers):
        y = lh * i + offset
        rank_icon = {1: 'First', 2: 'Second', 3: 'Third'}.get(item['rank'])
        nick = escape(item['nickname'])
        won  = item['won']

        if rank_icon:
            p.append(f'<quad posn="0.85 -{y-0.15:.2f} 0.002"'
                     f' sizen="1.7 1.6" style="Icons64x64_1"'
                     f' substyle="{rank_icon}"/>')

        p.append(f'<label posn="6.2 -{y:.2f} 0.002" sizen="3.95 1.7"'
                 f' halign="right" scale="0.9" textcolor="{escape(col_cop)}"'
                 f' text="+{won} C"/>')
        p.append(f'<label posn="6.5 -{y:.2f} 0.002" sizen="11.4 1.7"'
                 f' scale="0.9" text="{nick}"/>')
        if won > 0:
            p.append(f'<label posn="24.5 -{y:.2f} 0.002" sizen="8 1.7"'
                     f' halign="right" scale="0.9" textcolor="{escape(col_won)}"'
                     f' text="Congratulations!"/>')

    if not finishers:
        y = offset
        p.append(f'<label posn="2.3 -{y:.2f} 0.002" sizen="20 1.7"'
                 f' scale="0.9" textcolor="FA0F" text="No finishers yet"/>')

    p.append('</frame></manialink>')
    return ''.join(p)


# ---------------------------------------------------------------------------
# Phase 3 — RoundScoreWidget (ML 91831)
# ---------------------------------------------------------------------------

def build_round_score_widget(aseco: 'Aseco') -> str:
    """
    Port of PHP re_buildRoundScoreWidget().
    Reads round_scores and round_score_pb from _state.
    Shown live during race on each player finish.
    """
    mode = _effective_mode(aseco)
    gm_tag = _GM_TAG.get(mode)

    rs_cfg  = getattr(_state, 'round_score_cfg', {})
    gm_cfgs = rs_cfg.get('gamemodes', {})
    gm      = gm_cfgs.get(gm_tag or '', {})

    if not gm.get('enabled', False):
        return _empty(ML_ROUND_SCORE)

    warmup    = getattr(_state, 'warmup', False)
    phase_key = 'warmup' if warmup else 'race'
    phase_cfg = gm.get(phase_key, {})

    pos_x   = float(phase_cfg.get('pos_x', 49.2))
    pos_y   = float(phase_cfg.get('pos_y', 17.8))
    entries = int(phase_cfg.get('entries', 14))
    topcount= int(phase_cfg.get('topcount', 3))
    width   = float(rs_cfg.get('width', 15.5))
    title   = escape(rs_cfg.get('title', 'Round Score'))

    lh      = _state.line_height
    st      = _state.style
    fmt     = st.fmt_codes
    col_top = st.col_top
    col_worse = st.col_worse
    top_sty = st.top_style
    top_sub = st.top_sub

    # Race icon vs warmup icon
    op_key      = 'warmup' if warmup else 'race'
    op_cfg      = rs_cfg.get(op_key, {})
    icon_style  = escape(op_cfg.get('icon_style', 'Icons64x64_1'))
    icon_sub    = escape(op_cfg.get('icon_substyle', 'RestartRace'))

    # Background/title styles from race widget style
    bg_style   = st.bg_style
    bg_sub     = st.bg_substyle
    title_sty  = st.title_style
    title_sub  = st.title_sub

    position   = 'right' if pos_x < 0 else 'left'
    if position == 'right':
        icon_x  = 12.5 + (width - 15.5)
        title_x = 12.4 + (width - 15.5)
        title_ha= 'right'
    else:
        icon_x  = 0.6
        title_x = 3.2
        title_ha= 'left'

    widget_height = lh * entries + 3.3
    col_width_name = width / 100 * 72.0
    score_x = 2.65
    score_w = 3.45

    p = []
    p.append(f'<manialink id="{ML_ROUND_SCORE}">')
    p.append(f'<frame posn="{pos_x:.2f} {pos_y:.2f} 0">')
    p.append(f'<quad posn="0 0 0.001" sizen="{width:.2f} {widget_height:.2f}"'
             f' style="{escape(bg_style)}" substyle="{escape(bg_sub)}"/>')
    p.append(f'<quad posn="0.4 -0.36 0.002" sizen="{width-0.8:.2f} 2"'
             f' style="{escape(title_sty)}" substyle="{escape(title_sub)}"/>')
    p.append(f'<quad posn="{icon_x:.2f} 0 0.004" sizen="2.5 2.5"'
             f' style="{icon_style}" substyle="{icon_sub}"/>')
    p.append(f'<label posn="{title_x:.2f} -0.55 0.004" sizen="10 0"'
             f' halign="{title_ha}" textsize="1" text="{title}"/>')

    if topcount > 0:
        top_h = topcount * lh + 0.3
        p.append(f'<quad posn="0.4 -2.6 0.004" sizen="{width-0.8:.2f} {top_h:.2f}"'
                 f' style="{escape(top_sty)}" substyle="{escape(top_sub)}"/>')

    round_scores = getattr(_state, 'round_scores', {})
    round_pb     = getattr(_state, 'round_score_pb', {})

    if warmup:
        # Warmup: show "No Score during Warm-Up!" message
        p.append(f'<label posn="2.3 -3.2 0.004"'
                 f' sizen="{col_width_name+5.5:.2f} 1.7"'
                 f' scale="0.9" autonewline="1" textcolor="FA0F"'
                 f' text="No Score during&#10;Warm-Up!"/>')
    elif not round_scores:
        # Empty — no one finished yet
        p.append(f'<label posn="2.3 -3 0.004" sizen="1.7 1.7"'
                 f' halign="right" scale="0.9" text="{escape(fmt)}--."/ >')
        p.append(f'<label posn="{score_x:.2f} -3 0.004" sizen="{score_w:.2f} 1.7"'
                 f' halign="left" scale="0.9" textcolor="{escape(col_top)}"'
                 f' text="{escape(fmt)}-:--.--"/>')
        p.append(f'<label posn="6.25 -3 0.004" sizen="{max(width - 6.7, 1.0):.2f} 1.7"'
                 f' scale="0.9" textcolor="FA0F" text=" Free For You!"/>')
    else:
        # Build sorted score list
        # round_scores: dict[score_ms -> list[{login, nickname, score, score_plain, playerid}]]
        if mode == Gameinfo.LAPS:
            # Sort by checkpointid DESC, score ASC, playerid ASC
            flat = []
            for sc_key in round_scores:
                for entry in round_scores[sc_key]:
                    flat.append(entry)
            flat.sort(key=lambda x: (-x.get('checkpointid', 0),
                                     x.get('score_plain', 0),
                                     x.get('playerid', 0)))
            sorted_list = flat
        else:
            # Sort by score ASC (already keyed by score), tie-break by PB then PID
            sorted_list = []
            for sc_key in sorted(round_scores.keys()):
                group = round_scores[sc_key]
                if len(group) > 1:
                    group = sorted(group,
                                   key=lambda x: (x.get('score_plain', 0),
                                                  round_pb.get(x.get('login',''), 999999999),
                                                  x.get('playerid', 0)))
                sorted_list.extend(group)

        # Get rpoints
        rpoints = _get_rpoints(aseco, mode, len(sorted_list))

        line = 0
        offset = 3.0
        row_scale = 0.65
        name_x = 5.05 if mode == Gameinfo.TEAM else 5.05
        name_w = max(width - name_x - 0.55, 1.0)

        for item in sorted_list[:entries]:
            y = lh * line + offset
            textcolor = col_top if (line + 1) <= topcount else col_worse
            nick = escape(_sanitise_nick(item.get('nickname', '?')))
            score_txt = escape(item.get('score', '--'))

            # Points badge (left or right of widget)
            if mode == Gameinfo.LAPS:
                # Show lap count + time delta
                leader_cp = sorted_list[0].get('checkpointid', 0) if sorted_list else 0
                my_cp     = item.get('checkpointid', 0)
                delta_ms  = abs(item.get('score_plain', 0) - sorted_list[0].get('score_plain', 0))
                behind    = my_cp < leader_cp
                delta_col = 'D02F' if behind else '0B3F'
                delta_txt = escape(format_time(delta_ms))
                lap_txt   = str(my_cp + 1)
                if position == 'left':
                    p.append(f'<quad posn="-7.1 -{y-0.3:.2f} 0.003" sizen="7 2"'
                             f' style="BgsPlayerCard" substyle="ProgressBar"/>')
                    p.append(f'<label posn="-2.35 -{y:.2f} 0.004" sizen="4.8 2"'
                             f' halign="right" scale="{row_scale:.2f}" textcolor="{delta_col}"'
                             f' text="$O+{escape(fmt)}{delta_txt}"/>')
                    p.append(f'<label posn="-0.5 -{y:.2f} 0.004" sizen="1.3 2"'
                             f' halign="right" scale="{row_scale:.2f}" textcolor="{delta_col}"'
                             f' text="$O{escape(fmt)}{lap_txt}"/>')
                else:
                    p.append(f'<quad posn="{width+0.1:.2f} -{y-0.3:.2f} 0.003" sizen="7 2"'
                             f' style="BgsPlayerCard" substyle="ProgressBar"/>')
                    p.append(f'<label posn="{width+4.7:.2f} -{y:.2f} 0.004" sizen="4.8 2"'
                             f' halign="right" scale="{row_scale:.2f}" textcolor="{delta_col}"'
                             f' text="$O+{escape(fmt)}{delta_txt}"/>')
                    p.append(f'<label posn="{width+6.8:.2f} -{y:.2f} 0.004" sizen="1.3 2"'
                             f' halign="right" scale="{row_scale:.2f}" textcolor="{delta_col}"'
                             f' text="$O{escape(fmt)}{lap_txt}"/>')
            else:
                pts = (rpoints[line] if line < len(rpoints)
                       else (rpoints[-1] if rpoints else 0))
                pts_txt = f'$O+{escape(fmt)}{pts}'
                if position == 'left':
                    p.append(f'<quad posn="-4.1 -{y-0.3:.2f} 0.003" sizen="4 2"'
                             f' style="Bgs1InRace" substyle="BgCard1"/>')
                    p.append(f'<label posn="-0.6 -{y:.2f} 0.004" sizen="3 2"'
                             f' halign="right" scale="{row_scale:.2f}" textcolor="0B3F"'
                             f' text="{pts_txt}"/>')
                else:
                    p.append(f'<quad posn="{width+0.1:.2f} -{y-0.3:.2f} 0.003" sizen="4 2"'
                             f' style="Bgs1InRace" substyle="BgCard1"/>')
                    p.append(f'<label posn="{width+3.6:.2f} -{y:.2f} 0.004" sizen="3 2"'
                             f' halign="right" scale="{row_scale:.2f}" textcolor="0B3F"'
                             f' text="{pts_txt}"/>')

            # Rank, score, name
            p.append(f'<label posn="2.3 -{y:.2f} 0.004" sizen="1.7 1.7"'
                     f' halign="right" scale="{row_scale:.2f}"'
                     f' text="{escape(fmt)}{line+1}."/>')
            p.append(f'<label posn="{score_x:.2f} -{y:.2f} 0.004" sizen="{score_w:.2f} 1.7"'
                     f' halign="left" scale="{row_scale:.2f}" textcolor="{escape(textcolor)}"'
                     f' text="{escape(fmt)}{score_txt}"/>')
            p.append(f'<label posn="{name_x:.2f} -{y:.2f} 0.004" sizen="{name_w:.2f} 1.7"'
                     f' scale="{row_scale:.2f}" text="{escape(fmt)}{nick}"/>')
            line += 1

    p.append('</frame></manialink>')
    return ''.join(p)


def _get_rpoints(aseco: 'Aseco', mode: int, shown_count: int = 0) -> list[int]:
    """Get current round points list via GBX (cached) or settings fallback."""
    if mode == Gameinfo.TEAM:
        players = getattr(getattr(aseco, 'server', None), 'players', None)
        active_count = 0
        connected_count = 0
        if players is not None:
            try:
                all_players = list(players.all())
                server_login = getattr(getattr(aseco, 'server', None), 'serverlogin', '') or ''
                connected_count = sum(
                    1 for p in all_players
                    if getattr(p, 'login', '') and getattr(p, 'login', '') != server_login
                )
                active_count = sum(
                    1 for p in all_players
                    if getattr(p, 'login', '')
                    and getattr(p, 'login', '') != server_login
                    and not getattr(p, 'isspectator', False)
                )
            except Exception:
                active_count = 0
                connected_count = 0

        max_points_team = 0
        for holder in (
            getattr(aseco, 'settings', None),
            getattr(getattr(aseco, 'server', None), 'gameinfo', None),
            getattr(aseco, 'server', None),
        ):
            if holder is None:
                continue
            for attr in (
                'max_points_team',
                'team_max_points',
                'teampointsmax',
                'maxpointsteam',
                'TeamMaxPoints',
                'MaxPointsTeam',
            ):
                try:
                    value = int(getattr(holder, attr, 0) or 0)
                except Exception:
                    value = 0
                if value > 0:
                    max_points_team = value
                    break
            if max_points_team > 0:
                break

        count = max(active_count, shown_count)
        if count <= 1:
            count = max(count, connected_count)
        if max_points_team > 0:
            count = min(count, max_points_team) if count > 0 else max_points_team
        if count > 0:
            return list(range(count, 0, -1))

    # Try to use cached value set by plugin_rpoints
    cached = getattr(_state, '_rpoints_cache', None)
    if cached:
        return list(cached)
    # Fallback: read from settings
    system = getattr(getattr(aseco, 'settings', None), 'default_rpoints', '') or ''
    rounds_points = None
    try:
        from pyxaseco_plugins.plugin_rpoints import ROUNDS_POINTS as _ROUNDS_POINTS
        rounds_points = _ROUNDS_POINTS
    except Exception:
        try:
            from pyxaseco.plugins.plugin_rpoints import ROUNDS_POINTS as _ROUNDS_POINTS
            rounds_points = _ROUNDS_POINTS
        except Exception:
            rounds_points = None
    if rounds_points and system in rounds_points:
        return list(rounds_points[system][1])
    if ',' in system:
        try:
            return list(map(int, system.split(',')))
        except Exception:
            pass
    # TM defaults for Rounds
    return [10, 6, 4, 3, 2, 1]


# ---------------------------------------------------------------------------
# Send helpers — broadcast to all players
# ---------------------------------------------------------------------------

async def draw_round_score(aseco: 'Aseco') -> None:
    xml = build_round_score_widget(aseco)
    await _broadcast(aseco, xml)


async def hide_round_score(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_ROUND_SCORE))


async def draw_all_score_lists(aseco: 'Aseco') -> None:
    """Send all scoretable-list widgets to all players at score screen."""
    mode = _effective_mode(aseco)
    if mode != Gameinfo.STNT:
        await _broadcast(aseco, build_dedi_records_for_score(aseco))
    await _broadcast(aseco, build_local_records_for_score(aseco))
    await _broadcast(aseco, build_avg_times_for_score(aseco))
    await _broadcast(aseco, build_donation_widget(aseco))
    await _broadcast(aseco, build_winning_payout_widget(aseco))


async def hide_all_score_lists(aseco: 'Aseco') -> None:
    """Hide all scoretable-list widgets."""
    for ml in (ML_LOCAL_SCORE, ML_DEDI_SCORE, ML_AVG_TIMES,
               ML_DONATION, ML_WINNING_PAYOUT):
        await _broadcast(aseco, _empty(ml))
