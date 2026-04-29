from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from ..utils import _digest_entries, _handle_special_chars, _safe_ml_text

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from ..config import WidgetCfg, _state, _effective_mode
from ..ui import append_window_start, append_window_end, append_four_player_columns

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

ML_LIVE = 91813
ML_WINDOW = 91800
ML_SUBWIN = 91801


async def _fetch_live(aseco: 'Aseco') -> list:
    try:
        ranks = await aseco.client.query('GetCurrentRanking', 300, 0)
    except Exception as e:
        logger.debug('[Records-Eyepiece] GetCurrentRanking: %s', e)
        return []

    if not isinstance(ranks, list):
        return []

    # Team mode — collapse to the two team entries and relabel them explicitly.
    if getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.TEAM and len(ranks) >= 2:
        try:
            ranks[0].update({'Login': 'TEAM-0', 'NickName': '$08FTeam Blue'})
            ranks[1].update({'Login': 'TEAM-1', 'NickName': '$F50Team Red'})
        except Exception:
            pass
        return ranks[:2]
    return ranks


def _point_limit(aseco) -> int:
    info = getattr(aseco.server, 'gameinfo', None)
    if not info:
        return 0
    mode = _effective_mode(aseco)
    if mode == Gameinfo.RNDS:
        return int(getattr(info, 'rndslimit', 0) or 0)
    if mode == Gameinfo.TEAM:
        return int(getattr(info, 'teamlimit', 0) or 0)
    if mode == Gameinfo.CUP:
        return int(getattr(info, 'cuplimit', 0) or 0)
    return 0


def _is_team_live_mode(aseco, mode: int | None = None) -> bool:
    if mode == Gameinfo.TEAM:
        return True
    direct_mode = getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1)
    if direct_mode == Gameinfo.TEAM:
        return True
    if len(_state.live_cache) >= 2:
        login0 = str(_state.live_cache[0].get('Login') or '')
        login1 = str(_state.live_cache[1].get('Login') or '')
        if login0 == 'TEAM-0' and login1 == 'TEAM-1':
            return True
    return False


def _live_metric(aseco, item: dict, cfg: WidgetCfg, plimit: int) -> str:
    mode = getattr(aseco.server.gameinfo, 'mode', -1)

    if mode in (Gameinfo.RNDS, Gameinfo.CUP):
        score = int(item.get('Score', 0) or 0)
        if cfg.display_type == 'time':
            best = int(item.get('BestTime', 0) or 0)
            return format_time(best) if best > 0 else '--'

        remaining = max(plimit - score, 0) if plimit > 0 else 0
        return (
            cfg.fmt
            .replace('{score}', str(score))
            .replace('{remaining}', str(remaining))
            .replace('{pointlimit}', str(plimit))
        )

    if mode == Gameinfo.LAPS:
        if cfg.display_type == 'time':
            best = int(item.get('BestTime', 0) or 0)
            return format_time(best) if best > 0 else '--'

        ch = aseco.server.challenge
        nbc = int(getattr(ch, 'nbchecks', 0) or 0)
        nbl = int(getattr(ch, 'nblaps', 0) or 0)
        total_cps = nbc * nbl if nbl > 0 else nbc
        cps = int(item.get('NbCheckpoints') or item.get('BestCheckpoints') or 0)
        return f'{cps}/{total_cps}'

    if mode == Gameinfo.STNT:
        return str(int(item.get('Score', 0) or 0))

    # TA, Team, and default
    best = int(item.get('BestTime', 0) or item.get('Score', 0) or 0)
    return format_time(best) if best > 0 else '--'


def _live_entries_for(aseco, login: str, cfg: WidgetCfg, plimit: int) -> list:
    all_entries = []
    for i, item in enumerate(_state.live_cache):
        il = str(item.get('Login') or '')
        score_str = _live_metric(aseco, item, cfg, plimit)
        all_entries.append({
            'rank': i + 1,
            'login': il,
            'nickname': item.get('NickName') or il or '?',
            'score': score_str,
            'self': 0 if il == login else -1,
            'highlitefull': False,
            '_raw': item,
        })

    top = []
    better = []
    self_r = None
    worse = []
    found = False

    for entry in all_entries:
        if entry['login'] == login:
            entry['self'] = 0
            entry['highlitefull'] = (entry['rank'] - 1 < cfg.topcount)
            self_r = entry
            found = True
        elif not found:
            if len(top) < cfg.topcount:
                top.append(entry)
            else:
                better.append(entry)
        else:
            entry['self'] = 1
            worse.append(entry)

    if self_r is None:
        placeholder = {
            'rank': '--',
            'login': login,
            'nickname': getattr(aseco.server.players.get_player(login), 'nickname', login) or login,
            'score': '0',
            'self': 0,
            'highlitefull': False,
        }
        avail = cfg.entries - 1
        result = top[:cfg.topcount]
        avail -= len(result)
        result += better[:avail]
        result.append(placeholder)
        return result[:cfg.entries]

    remaining = cfg.entries - cfg.topcount - 1
    if remaining < 1:
        remaining = 1
    before = remaining // 2
    after = remaining - before
    b_slice = better[-before:] if before else []
    w_slice = worse[:after]
    if len(w_slice) < after:
        extra = after - len(w_slice)
        b_slice = better[-(before + extra):] if (before + extra) else []

    return (top[:cfg.topcount] + b_slice + [self_r] + w_slice)[:cfg.entries]


def _live_team_entries(aseco) -> list:
    entries = []
    for item in _state.live_cache[:2]:
        il = str(item.get('Login') or '')
        entries.append({
            'rank': False,
            'login': il,
            'nickname': item.get('NickName') or il or '?',
            'score': str(int(item.get('Score', 0) or 0)) + ' pts.',
            'self': -1,
            'highlitefull': False,
        })
    return entries


async def _draw_live_player(aseco: 'Aseco', login: str):
    from .common import _hide, _send
    from .records_common import _build_record_widget

    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    if _state.challenge_show_next or mode == getattr(Gameinfo, 'SCOR', 7):
        await _hide(aseco, login, ML_LIVE)
        return

    if not _state.player_visible.get(login, True):
        await _hide(aseco, login, ML_LIVE)
        return

    mode = _effective_mode(aseco)
    cfg = _state.live.get(mode)
    if not cfg or not cfg.enabled:
        await _hide(aseco, login, ML_LIVE)
        return

    plimit = _point_limit(aseco)
    team_mode = _is_team_live_mode(aseco, mode)

    if team_mode:
        raw_entries = _live_team_entries(aseco)
    else:
        raw_entries = _live_entries_for(aseco, login, cfg, plimit)

    digest = _digest_entries(raw_entries, login)
    if _state.player_live_digest.get(login) == digest:
        return
    _state.player_live_digest[login] = digest

    xml = _build_record_widget(
        ml_id=ML_LIVE,
        cfg=cfg,
        login=login,
        entries=raw_entries,
        online=set(),
        mode=Gameinfo.TEAM if team_mode else mode,
        is_live=True,
        click_action=91806,
    )
    await _send(aseco, login, xml)


def _build_live_rankings_window(aseco: 'Aseco', page: int = 0) -> str:
    live = _state.live_cache
    if not live:
        return ''

    mode = _effective_mode(aseco)
    team_mode = _is_team_live_mode(aseco, mode)
    plimit = _point_limit(aseco)
    cfg = _state.live.get(Gameinfo.TEAM if team_mode else mode, WidgetCfg())
    st = _state.style

    total = len(live)
    per_page = 100
    max_pages = max(1, min(4, (total + per_page - 1) // per_page))
    page = max(0, min(page, max_pages - 1))

    def page_buttons_lr(cur_p, mx_p):
        b = '<frame posn="67.05 -53.2 0">'
        if cur_p > 0:
            b += f'<quad posn="4.95 6.5 0.12" sizen="3.2 3.2" action="-{918150 + cur_p - 1}" style="Icons64x64_1" substyle="ArrowPrev"/>'
        else:
            b += '<quad posn="4.95 6.5 0.12" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        if cur_p < mx_p - 1:
            b += f'<quad posn="8.25 6.5 0.12" sizen="3.2 3.2" action="{918150 + cur_p + 1}" style="Icons64x64_1" substyle="ArrowNext"/>'
        else:
            b += '<quad posn="8.25 6.5 0.12" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        b += '</frame>'
        return b

    p = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title=cfg.title,
        icon_style=cfg.icon_style,
        icon_substyle=cfg.icon_substyle,
        content_frame_pos='2.5 -6.5 1',
    )
    p.append(page_buttons_lr(page, max_pages))
    p.append(f'<format textsize="1" textcolor="{st.col_default}"/>')
    append_four_player_columns(p)

    line = 0
    offset = 0.0
    start = page * per_page
    for i, item in enumerate(live[start:start + per_page]):
        score_str = _live_metric(aseco, item, cfg, plimit)
        nick = str(item.get('NickName') or '?')
        rank_num = start + i + 1
        y = 1.83 * line

        if team_mode:
            p.append(f'<label posn="{6.6 + offset:.2f} -{y:.2f} 0.03" sizen="6 1.7" halign="right" scale="0.9" textcolor="FFFF" text="{score_str}"/>')
        else:
            p.append(f'<label posn="{2.6 + offset:.2f} -{y:.2f} 0.03" sizen="2 1.7" halign="right" scale="0.9" text="{rank_num}."/>')
            p.append(f'<label posn="{6.4 + offset:.2f} -{y:.2f} 0.03" sizen="4 1.7" halign="right" scale="0.9" textcolor="{st.col_scores}" text="{score_str}"/>')
        p.append(f'<label posn="{6.9 + offset:.2f} -{y:.2f} 0.03" sizen="11.2 1.7" scale="0.9" text="{_safe_ml_text(nick)}"/>')

        line += 1
        if line >= 25:
            offset += 19.05
            line = 0

    append_window_end(p)
    return ''.join(p)
