from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo
from pyxaseco.app_services import get_dedi_db

from apps.ui.config import _state, _effective_mode
from apps.ui.hud import (
    append_window_start,
    append_window_end,
    append_four_player_columns,
)
from apps.ui.internal.utils import _handle_special_chars
from apps.ui.widgets.records_common import (
    ML_DEDI, ML_WINDOW, ML_SUBWIN, _digest_entries, _same_login, _dedi_close_to_you,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

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


def _get_dedi_records(aseco: 'Aseco' | None = None) -> list:
    try:
        runtime = aseco or getattr(_state, 'aseco', None)
        dedi_db = get_dedi_db(runtime)
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
    from apps.ui.widgets.common import _hide, _send
    from apps.ui.widgets.records_common import _build_record_widget

    if not _state.player_visible.get(login, True):
        await _hide(aseco, login, ML_DEDI)
        return

    if _state.challenge_show_next:
        await _hide(aseco, login, ML_DEDI)
        return

    mode = _effective_mode(aseco)
    cfg = _state.dedi.get(mode)
    if mode == Gameinfo.STNT or not cfg or not cfg.enabled:
        await _hide(aseco, login, ML_DEDI)
        return

    raw_recs = _get_dedi_records(aseco)
    if not raw_recs:
        _state.player_dedi_digest.pop(login, None)

    online = {p.login for p in aseco.server.players.all()} if _state.mark_online else set()
    player = aseco.server.players.get_player(login)
    player_nick = player.nickname if player and getattr(player, 'nickname', '') else login

    lookup = getattr(aseco, 'get_service', None)
    ui_style = lookup('ui/uistyle') if callable(lookup) else None
    modern = ui_style is not None and ui_style.resolve(player).base == 1
    entries = _dedi_close_to_you(raw_recs, login, cfg.entries, cfg.topcount, player_nick, include_no_record=not modern)
    # Hard fallback: never allow an empty Dedi widget body.
    if not entries and not modern:
        entries = [{
            'rank': '--',
            'login': login,
            'nickname': player_nick or login,
            'score': None,
            'self': 0,
            'highlitefull': False,
        }]

    xml = _build_record_widget(
        aseco=aseco,
        ml_id=ML_DEDI,
        cfg=cfg,
        login=login,
        entries=entries,
        online=online,
        mode=mode,
        click_action=91804,
    )
    digest = str(hash(xml))
    if _state.player_dedi_digest.get(login) == digest:
        return
    await _send(aseco, login, xml)
    _state.player_dedi_digest[login] = digest


def _build_dedi_records_window(aseco: 'Aseco', page: int = 0, records: list | None = None) -> str:
    from apps.ui.internal.utils import _safe_ml_text

    raw_records = records if records is not None else _get_dedi_records(aseco)
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

