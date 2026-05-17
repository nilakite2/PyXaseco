from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from ..config import _state, _effective_mode
from ..ui import append_window_start, append_window_end, append_four_player_columns
from ..utils import _handle_special_chars

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Record

logger = logging.getLogger(__name__)

ML_LOCAL = 91812
ML_WINDOW = 91800
ML_SUBWIN = 91801


def _digest_entries(entries: list, login: str) -> str:
    """
    Fast content fingerprint to skip sending unchanged ManiaLinks.
    Kept local here so the split file works even if utils.py does not expose it yet.
    """
    key = str((login, [(e.get('rank'), e.get('login'), e.get('score'), e.get('self'))
                       for e in entries]))
    return str(hash(key))


def _close_to_you(records, login: str, limit: int, topcount: int, player_nick: str | None = None) -> list:
    better: list = []
    worse: list = []
    self_r = None
    is_better = True

    for i, rec in enumerate(records):
        rec_login = rec.player.login if rec.player else ''
        entry = {
            'rank': i + 1,
            'login': rec_login,
            'nickname': rec.player.nickname if rec.player else '?',
            'score': rec.score,
            'self': -1,
            'highlitefull': False,
        }
        if rec_login == login:
            self_r = entry
            is_better = False
        elif is_better:
            better.append(entry)
        else:
            entry['self'] = 1
            worse.append(entry)

# ── Top-X pinning from the better-record slice ──────
    array_top: list = []
    ctu_count = limit
    if len(better) > topcount:
        for _ in range(topcount):
            e = better.pop(0)
            e['self'] = -1
            array_top.append(e)
        ctu_count -= topcount

    # ── No record for this player — show placeholder at the bottom ─────────
    if self_r is None:
        placeholder = {
            'rank': '--',
            'login': login,
            'nickname': player_nick or login,
            'score': None,
            'self': 0,
            'highlitefull': False,
        }
        result: list = [None] * ctu_count
        last_idx = ctu_count - 1
        result[last_idx] = placeholder
        for i in range(len(better) - 1, -1, -1):
            last_idx -= 1
            if last_idx >= 0:
                result[last_idx] = better[i]
                result[last_idx]['self'] = -1
        result = [r for r in result if r is not None]
        return (array_top + result)[:limit]

    # ── Alternate one-before / one-after around self until ctu_count full ──
    result_new: list = [dict(self_r)]
    result_new[0]['self'] = 0
    idx = 0
    has_better = True
    has_worse = True

    while len(result_new) < ctu_count and (has_better or has_worse):
        if has_better and len(better) >= idx + 1:
            r = dict(better[len(better) - 1 - idx])
            r['self'] = -1
            result_new = [r] + result_new
        else:
            has_better = False

        if len(result_new) < ctu_count:
            if has_worse and len(worse) >= idx + 1:
                r = dict(worse[idx])
                r['self'] = 1
                result_new.append(r)
            else:
                has_worse = False
        idx += 1

    result = array_top + result_new

    # ── Set highlitefull: True when self is OUTSIDE the top-X zone ────────
    result_clean: list = []
    count = 0
    for item in result:
        if item is not None:
            if item.get('self') == 0:
                item['highlitefull'] = count >= topcount
            result_clean.append(item)
            count += 1

    return result_clean[:limit]



async def _draw_local_player(aseco: 'Aseco', login: str):
    from .common import _hide, _send
    from .records_common import _build_record_widget

    if not _state.player_visible.get(login, True):
        await _hide(aseco, login, ML_LOCAL)
        return

    if _state.challenge_show_next:
        await _hide(aseco, login, ML_LOCAL)
        return

    mode = _effective_mode(aseco)
    cfg = _state.local.get(mode)
    if not cfg or not cfg.enabled:
        await _hide(aseco, login, ML_LOCAL)
        return

    all_recs = list(aseco.server.records)
    online = {p.login for p in aseco.server.players.all()} if _state.mark_online else set()

    player = aseco.server.players.get_player(login)
    player_nick = player.nickname if player and getattr(player, 'nickname', '') else login

    entries = _close_to_you(all_recs, login, cfg.entries, cfg.topcount, player_nick)

    digest = _digest_entries(entries, login)
    if _state.player_local_digest.get(login) == digest:
        return
    _state.player_local_digest[login] = digest

    xml = _build_record_widget(
        ml_id=ML_LOCAL,
        cfg=cfg,
        login=login,
        entries=entries,
        online=online,
        mode=mode,
        click_action=91805,
    )
    await _send(aseco, login, xml)


async def _build_local_records_window(aseco: 'Aseco', page: int) -> str:
    from ..utils import _safe_ml_text

    records = list(aseco.server.records)
    if not records:
        return ''

    total = min(len(records), 5000)
    max_pages = max(1, (total + 99) // 100)
    page = max(0, min(page, max_pages - 1))

    PAGE_BASE = 918100

    def page_buttons(cur_p: int, mx_p: int) -> str:
        b = '<frame posn="52.2 -53.2 0.04">'
        if cur_p > 0:
            b += (
                f'<quad posn="6.6 6.50 0.01" sizen="3.2 3.2" action="-{PAGE_BASE + 0}" style="Icons64x64_1" substyle="ArrowFirst"/>'
                f'<quad posn="9.9 6.50 0.01" sizen="3.2 3.2" action="-{max(PAGE_BASE, PAGE_BASE + cur_p - 5)}" style="Icons64x64_1" substyle="ArrowFastPrev"/>'
                f'<quad posn="13.2 6.50 0.01" sizen="3.2 3.2" action="-{PAGE_BASE + cur_p - 1}" style="Icons64x64_1" substyle="ArrowPrev"/>'
            )
        else:
            b += (
                '<quad posn="6.6 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="6.6 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="9.9 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="9.9 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="13.2 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="13.2 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            )

        if (cur_p < 50) and (total > 100) and ((cur_p + 1) < mx_p):
            b += (
                f'<quad posn="16.5 6.50 0.01" sizen="3.2 3.2" action="{PAGE_BASE + cur_p + 1}" style="Icons64x64_1" substyle="ArrowNext"/>'
                f'<quad posn="19.8 6.50 0.01" sizen="3.2 3.2" action="{min(PAGE_BASE + mx_p - 1, PAGE_BASE + cur_p + 5)}" style="Icons64x64_1" substyle="ArrowFastNext"/>'
                f'<quad posn="23.1 6.50 0.01" sizen="3.2 3.2" action="{PAGE_BASE + mx_p - 1}" style="Icons64x64_1" substyle="ArrowLast"/>'
            )
        else:
            b += (
                '<quad posn="16.5 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="16.5 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="19.8 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="19.8 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="23.1 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="23.1 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            )

        b += '</frame>'
        return b

    title = f'Local Records   |   Page {page + 1}/{max_pages}   |   {total} Record{"s" if total != 1 else ""}'

    p: list[str] = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title=title,
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        content_frame_pos='2.5 -6.5 1',
    )
    p.append(page_buttons(page, max_pages))

    p.append(f'<format textsize="1" textcolor="{_state.style.col_default}"/>')
    append_four_player_columns(p)

    online = {pl.login for pl in aseco.server.players.all()}

    line = 0
    offset = 0.0
    for i in range(page * 100, min(page * 100 + 100, total)):
        rec = records[i]
        rec_login = rec.player.login if rec.player else ''
        nick = rec.player.nickname if rec.player else '?'
        score_str = format_time(rec.score)

        if rec_login in online:
            y_bg = -(1.83 * line - 0.2) if (1.83 * line - 0.2) > 0 else 0.2
            p.append(
                f'<quad posn="{offset + 0.4:.2f} {y_bg:.2f} 0.03" sizen="16.95 1.83" '
                f'style="{_state.style.hi_other_style}" substyle="{_state.style.hi_other_sub}"/>'
            )

        y = 1.83 * line
        p.append(f'<label posn="{2.6 + offset:.2f} -{y:.2f} 0.04" sizen="2 1.7" halign="right" scale="0.9" text="{i + 1}."/>')
        p.append(f'<label posn="{6.4 + offset:.2f} -{y:.2f} 0.04" sizen="4 1.7" halign="right" scale="0.9" textcolor="{_state.style.col_scores}" text="{_safe_ml_text(score_str)}"/>')
        p.append(f'<label posn="{6.9 + offset:.2f} -{y:.2f} 0.04" sizen="11.2 1.7" scale="0.9" text="{_safe_ml_text(nick)}"/>')

        line += 1
        if line >= 25:
            offset += 19.05
            line = 0

    append_window_end(p)
    return ''.join(p)
