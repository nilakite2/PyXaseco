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

logger = logging.getLogger(__name__)

ML_DEDI = 91811
ML_WINDOW = 91800
ML_SUBWIN = 91801


def _digest_entries(entries: list, login: str) -> str:
    key = str((login, [(e.get('rank'), e.get('login'), e.get('score'), e.get('self'))
                       for e in entries]))
    return str(hash(key))


def _normalise_dedi_record(rec: dict, rank: int) -> dict | None:
    if not isinstance(rec, dict):
        return None

    best = int(rec.get('Best') or rec.get('Score') or rec.get('score') or 0)
    if best <= 0:
        return None

    game = str(rec.get('Game') or 'TMU')
    login = str(rec.get('login') or rec.get('Login') or '')
    if game.upper() == 'TMN' and not login.endswith('TMN'):
        login += 'TMN'

    nickname = str(
        rec.get('nickname')
        or rec.get('NickName')
        or rec.get('Nickname')
        or login
        or '?'
    )
    nickname = _handle_special_chars(nickname)

    return {
        # Normalized Eyepiece shape
        'rank': int(rec.get('rank') or rec.get('Pos') or rank),
        'login': login,
        'nickname': nickname,
        'score': best,
        'score_text': format_time(best),
        # Backward-compatible/raw-ish aliases
        'Game': game,
        'Login': login,
        'NickName': nickname,
        'Best': best,
        'Score': best,
        'Pos': int(rec.get('Pos') or rank),
    }


def _dedi_close_to_you(
    recs: list,
    login: str,
    limit: int,
    topcount: int,
    player_nick: str | None = None,
) -> list:
    better: list = []
    worse: list = []
    self_r = None
    is_better = True

    for i, rec in enumerate(recs):
        if not isinstance(rec, dict):
            continue

        rl = str(rec.get('login') or rec.get('Login') or '')
        nick = str(rec.get('nickname') or rec.get('NickName') or rl or '?')
        score = rec.get('score')

        entry = {
            'rank': int(rec.get('rank') or (i + 1)),
            'login': rl,
            'nickname': nick,
            'score': score,
            'self': -1,
            'highlitefull': False,
        }

        if rl == login:
            self_r = entry
            is_better = False
        elif is_better:
            better.append(entry)
        else:
            entry['self'] = 1
            worse.append(entry)

    
    # Top-X pinning
    array_top: list = []
    ctu_count = limit
    if len(better) > topcount:
        for _ in range(topcount):
            e = better.pop(0)
            e['self'] = -1
            array_top.append(e)
        ctu_count -= topcount
    
    # No record for this player - keep the placeholder row
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

    # Alternate one-before / one-after around self
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

    result_clean: list = []
    count = 0
    for item in result:
        if item is not None:
            if item.get('self') == 0:
                item['highlitefull'] = count >= topcount
            result_clean.append(item)
            count += 1
    
    return result_clean[:limit]


def _get_dedi_records() -> list:
    try:
        try:
            from pyxaseco_plugins.plugin_dedimania import dedi_db
        except Exception:
            from pyxaseco.plugins.plugin_dedimania import dedi_db
        if not isinstance(dedi_db, dict):
            return []
        challenge = dedi_db.get('Challenge', {})
        if not isinstance(challenge, dict):
            return []
        records = challenge.get('Records', [])
        if not isinstance(records, list):
            return []

        result = []
        for i, rec in enumerate(records):
            row = _normalise_dedi_record(rec, i + 1)
            if row is not None:
                result.append(row)
        return result
    except Exception:
        return []


async def _draw_dedi_player(aseco: 'Aseco', login: str):
    from .common import _hide, _send
    from .records_common import _build_record_widget

    if not _state.player_visible.get(login, True):
        await _hide(aseco, login, ML_DEDI)
        return

    if _state.challenge_show_next:
        await _hide(aseco, login, ML_DEDI)
        return

    mode = _effective_mode(aseco)
    cfg = _state.dedi.get(mode)
    if not cfg or not cfg.enabled:
        await _hide(aseco, login, ML_DEDI)
        return

    raw_recs = _get_dedi_records()
    if not raw_recs:
        _state.player_dedi_digest.pop(login, None)

    online = {p.login for p in aseco.server.players.all()} if _state.mark_online else set()
    player = aseco.server.players.get_player(login)
    player_nick = player.nickname if player and getattr(player, 'nickname', '') else login

    entries = _dedi_close_to_you(raw_recs, login, cfg.entries, cfg.topcount, player_nick)
    # Hard fallback: never allow an empty Dedi widget body.
    if not entries:
        entries = [{
            'rank': '--',
            'login': login,
            'nickname': player_nick or login,
            'score': None,
            'self': 0,
            'highlitefull': False,
        }]

    digest = _digest_entries(entries, login)
    if _state.player_dedi_digest.get(login) == digest:
        return
    _state.player_dedi_digest[login] = digest

    xml = _build_record_widget(
        ml_id=ML_DEDI,
        cfg=cfg,
        login=login,
        entries=entries,
        online=online,
        mode=mode,
        click_action=91804,
    )
    await _send(aseco, login, xml)


def _build_dedi_records_window(aseco: 'Aseco', page: int = 0, records: list | None = None) -> str:
    from ..utils import _safe_ml_text

    raw_records = records if records is not None else _get_dedi_records()
    if not raw_records:
        return ''

    mode = _effective_mode(aseco)
    is_stnt = (mode == Gameinfo.STNT)

    title = _state.dedi.get(mode, _state.challenge).title
    total = len(raw_records)

    p: list[str] = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title=f'{_safe_ml_text(title)}  |  Page 1/1  |  {total} Records',
        icon_style='Icons128x128_1',
        icon_substyle='Rankings',
        content_frame_pos='2.5 -6.5 1',
    )

    ch = getattr(aseco.server, 'challenge', None)
    uid = getattr(ch, 'uid', '') or ''
    dedimode = '&amp;Mode=M0' if mode in (Gameinfo.RNDS, Gameinfo.TEAM, Gameinfo.CUP) else '&amp;Mode=M1' if mode in (Gameinfo.TA, Gameinfo.LAPS) else ''
    p.append('<frame posn="63.15 0 0.04">')
    p.append(
        f'<quad posn="0 -47.8 -0.5" sizen="14.5 1" '
        f'url="http://dedimania.net/tmstats/?do=stat{dedimode}&amp;RecOrder3=RANK-ASC&amp;Uid={_safe_ml_text(uid)}&amp;Show=RECORDS" bgcolor="0000"/>'
    )

    p.append('<label posn="0 -47.8 -0.5" sizen="30 1" textsize="1" scale="0.7" textcolor="000F" text="MORE INFO ON DEDIMANIA.NET  "/>')
    p.append('</frame>')

    p.append(f'<format textsize="1" textcolor="{_state.style.col_default}"/>')
    append_four_player_columns(p)

    online = {pl.login for pl in aseco.server.players.all()}

    line = 0
    offset = 0.0
    for idx, item in enumerate(raw_records[:100], start=1):
        if not isinstance(item, dict):
            continue

        rec_login = str(item.get('login') or item.get('Login') or '')
        nick = str(item.get('nickname') or item.get('NickName') or rec_login or '?')

        if is_stnt:
            try:
                score = str(int(item.get('Best') or item.get('Score') or item.get('score') or 0))
            except Exception:
                score = '--'
        else:
            score = item.get('score_text')
            if not score:
                try:
                    score = format_time(int(item.get('Best') or item.get('Score') or item.get('score') or 0))
                except Exception:
                    score = '--'

        rank = int(item.get('rank') or item.get('Pos') or idx)

        if rec_login in online:
            y_bg = max(0.2, 1.83 * line - 0.2)
            p.append(
                f'<quad posn="{offset + 0.4:.2f} -{y_bg:.2f} 0.03" sizen="16.95 1.83" '
                f'style="{_state.style.hi_other_style}" substyle="{_state.style.hi_other_sub}"/>'
            )

        y = 1.83 * line
        p.append(f'<label posn="{2.6 + offset:.2f} -{y:.2f} 0.04" sizen="2 1.7" halign="right" scale="0.9" text="{rank}."/>')
        p.append(f'<label posn="{6.4 + offset:.2f} -{y:.2f} 0.04" sizen="4 1.7" halign="right" scale="0.9" textcolor="{_state.style.col_scores}" text="{_safe_ml_text(score)}"/>')
        p.append(f'<label posn="{6.9 + offset:.2f} -{y:.2f} 0.04" sizen="11.2 1.7" scale="0.9" text="{_safe_ml_text(nick)}"/>')

        line += 1
        if line >= 25:
            offset += 19.05
            line = 0

    append_window_end(p)
    return ''.join(p)
