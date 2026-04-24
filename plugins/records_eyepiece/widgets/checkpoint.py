from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.models import Gameinfo

from ..config import _state, _effective_mode

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


ML_CP = 91832
ML_CPDELTA = 91834


def _is_player_currently_spectating(player) -> bool:
    if not player:
        return False

    raw_status = getattr(player, 'spectatorstatus', None)
    if raw_status is not None:
        try:
            return (int(raw_status) % 10) != 0
        except Exception:
            pass

    return bool(getattr(player, 'isspectator', False))


# ---------------------------------------------------------------------------
# Widget renderers
# ---------------------------------------------------------------------------

async def _draw_cpdelta_player(aseco: 'Aseco', login: str):
    from .common import _hide, _send

    mode = _effective_mode(aseco)
    if _state.challenge_show_next or mode == getattr(Gameinfo, 'SCOR', 7):
        await _hide(aseco, login, ML_CPDELTA)
        return

    # Spectators don't drive — hide the Local/Dedi time delta overlay.
    _player = aseco.server.players.get_player(login)
    if _is_player_currently_spectating(_player):
        await _hide(aseco, login, ML_CPDELTA)
        return

    text = str(_state.player_cp_delta.get(login, '') or '')
    if not text:
        await _hide(aseco, login, ML_CPDELTA)
        return

    label = _state.player_cp_target_name.get(login, '') or 'CP Delta'
    cp_cfg = _state.cp

    # Center under the 16-wide CP widget, with spectator offset
    player = aseco.server.players.get_player(login)
    _spec_offset = 5.0 if _is_player_currently_spectating(player) else 0.0
    x = cp_cfg.pos_x + 8.0
    y = cp_cfg.pos_y - 4.8 + _spec_offset

    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<manialink id="{ML_CPDELTA}">'
        f'<frame posn="{x:.2f} {y:.2f} 1">'
        f'<label scale="0.30" posn="0 0 1" halign="center" valign="center" '
        f'style="TextRaceMessage" text="{label}"/>'
        f'<label scale="0.50" posn="0 -1.8 1" halign="center" valign="center" '
        f'style="TextRaceChrono" text="{text}"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _send(aseco, login, xml)


async def _draw_cp_player(aseco: 'Aseco', login: str):
    """
    Port of re_buildCheckpointCountWidget().
    """
    from .common import _hide, _send

    if not _state.cp.enabled:
        await _hide(aseco, login, ML_CP)
        return

    st = _state.style
    cp_cfg = _state.cp
    ch = aseco.server.challenge
    mode = _effective_mode(aseco)

    if _state.challenge_show_next or mode == getattr(Gameinfo, 'SCOR', 7):
        await _hide(aseco, login, ML_CP)
        return

    nbchecks = int(getattr(ch, 'nbchecks', 0) or 0)
    nblaps = int(getattr(ch, 'nblaps', 0) or 0)
    forcedlaps = int(getattr(ch, 'forcedlaps', 0) or 0)

    if mode in (Gameinfo.RNDS, Gameinfo.TEAM, Gameinfo.CUP):
        if forcedlaps > 0:
            totalcps = nbchecks * forcedlaps
        elif nblaps > 0:
            totalcps = nbchecks * nblaps
        else:
            totalcps = nbchecks
    elif mode == Gameinfo.LAPS and nblaps > 0:
        totalcps = nbchecks * nblaps
    else:
        totalcps = nbchecks

    # When this player is spectating, show the CP progress of the player
    # they are watching rather than the spectator's own (always 0) counter.
    _display_login = login
    spec_status = getattr(aseco.server.players.get_player(login), 'spectatorstatus', 0) or 0
    if spec_status and (spec_status % 10) != 0:  # non-zero low digit = is spectator
        target_pid = spec_status // 10000
        if target_pid > 0:
            # Find the player being spectated by their server PID
            for _p in aseco.server.players.all():
                if getattr(_p, 'pid', 0) == target_pid:
                    _display_login = _p.login
                    break

    checkpoint = int(_state.player_cp_idx.get(_display_login, 0) or 0)
    cp_display = checkpoint
    text_color = st.cp_text_color

    total_display = totalcps - 1 if totalcps > 0 else 0

    if cp_display == total_display and total_display > 0:
        top_text = 'ALL CHECKPOINTS REACHED'
        top_color = 'FC0F'
        bot_text = '$O Finish Now '
        blink = False
    elif cp_display > total_display and total_display > 0:
        top_text = 'TRACK SUCCESSFULLY'
        top_color = 'FC0F'
        bot_text = '$O Finished '
        blink = False
    elif total_display == 0:
        top_text = 'WITHOUT CHECKPOINTS'
        top_color = 'FC0F'
        bot_text = ''
        blink = False
    else:
        top_text = 'CHECKPOINT'
        top_color = 'FC0F'
        bot_text = f'$O{cp_display} $Zof$O {total_display}'
        blink = False

    bot_style = 'style="TextTitle2Blink"' if blink else ''

    # Spectators have the speed/time box removed so the CP widget must
    # move up 5 units to avoid the empty gap at the bottom of the screen.
    player = aseco.server.players.get_player(login)
    _spec_offset = 5.0 if _is_player_currently_spectating(player) else 0.0
    _cp_pos_y = cp_cfg.pos_y + _spec_offset

    xml = (
        f'<manialink id="{ML_CP}">'
        f'<frame posn="{cp_cfg.pos_x:.4f} {_cp_pos_y:.4f} 0">'
        f'<quad posn="0 0 0.001" sizen="16 4"'
        f' style="{st.bg_style}" substyle="{st.bg_substyle}"/>'
        f'<label posn="8 -0.65 0.01" halign="center"'
        f' textsize="1" scale="0.6" textcolor="{top_color}"'
        f' text="{top_text}"/>'
    )
    if bot_text:
        xml += (
            f'<label posn="8 -1.8 0.01" halign="center"'
            f' {bot_style} textsize="1" scale="0.9"'
            f' textcolor="{text_color}"'
            f' text="{bot_text}"/>'
        )
    xml += f'</frame></manialink>'

    await _send(aseco, login, xml)


# ---------------------------------------------------------------------------
# CP Delta Helpers
# ---------------------------------------------------------------------------

def _find_local_cp_target(aseco: 'Aseco', login: str) -> tuple[str, list[int], int | None]:
    records = aseco.server.records
    try:
        count = records.count()
    except Exception:
        count = 0

    for i in range(count):
        rec = records.get_record(i)
        if not rec or not getattr(rec, 'player', None):
            continue
        if rec.player.login != login:
            continue
        checks = list(getattr(rec, 'checks', []) or [])
        if checks:
            return ('Local', [int(x) for x in checks], int(getattr(rec, 'score', 0) or 0))

    return ('', [], None)


def _get_dedi_records_for_current_challenge(aseco: 'Aseco') -> list[dict]:
    try:
        from pyxaseco.plugins.plugin_dedimania import dedi_db
        chal = dedi_db.get('Challenge', {}) if isinstance(dedi_db, dict) else {}
        recs = chal.get('Records', [])
        dedi_uid = str(chal.get('Uid') or chal.get('UID') or '')
        curr_uid = str(getattr(getattr(aseco.server, 'challenge', None), 'uid', '') or '')
        if dedi_uid and curr_uid and dedi_uid != curr_uid:
            return []
    except Exception:
        return []

    return recs if isinstance(recs, list) else []


def _find_player_dedi_cp_target(aseco: 'Aseco', login: str) -> tuple[str, list[int], int | None]:
    for rec in _get_dedi_records_for_current_challenge(aseco):
        if not isinstance(rec, dict):
            continue
        if str(rec.get('Login') or '') != login:
            continue
        checks = list(rec.get('Checks', []) or [])
        if checks:
            best = int(rec.get('Best', 0) or rec.get('Score', 0) or 0)
            return ('Dedi', [int(x) for x in checks], best if best > 0 else None)

    return ('', [], None)


def _find_dedi_cp_target(aseco: 'Aseco', login: str) -> tuple[str, list[int], int | None]:
    mode, checks, score = _find_player_dedi_cp_target(aseco, login)
    if checks:
        return (mode, checks, score)

    for rec in reversed(_get_dedi_records_for_current_challenge(aseco)):
        if not isinstance(rec, dict):
            continue
        checks = list(rec.get('Checks', []) or [])
        if checks:
            best = int(rec.get('Best', 0) or rec.get('Score', 0) or 0)
            return ('Dedi', [int(x) for x in checks], best if best > 0 else None)

    return ('', [], None)


def _refresh_cp_target_for_player(aseco: 'Aseco', login: str) -> None:
    mode = ''
    checks: list[int] = []
    label = ''

    local_mode, local_checks, local_score = _find_local_cp_target(aseco, login)
    dedi_mode, dedi_checks, dedi_score = _find_player_dedi_cp_target(aseco, login)

    if local_checks and dedi_checks:
        if dedi_score is not None and (local_score is None or dedi_score < local_score):
            mode, checks, label = dedi_mode, dedi_checks, 'Dedi'
        else:
            mode, checks, label = local_mode, local_checks, 'Local'
    elif local_checks:
        mode, checks, label = local_mode, local_checks, 'Local'
    elif dedi_checks:
        mode, checks, label = dedi_mode, dedi_checks, 'Dedi'
    else:
        mode, checks, _ = _find_dedi_cp_target(aseco, login)
        label = 'Dedi' if checks else ''

    _state.player_cp_target_mode[login] = mode
    _state.player_cp_target_checks[login] = checks
    _state.player_cp_target_name[login] = label

    if not checks:
        _state.player_cp_delta[login] = ''


def _refresh_cp_targets_all(aseco: 'Aseco') -> None:
    for p in aseco.server.players.all():
        _refresh_cp_target_for_player(aseco, p.login)


def _format_cp_delta(ms: int) -> str:
    if ms < 0:
        sign = '$00f-'
        ms = abs(ms)
    elif ms > 0:
        sign = '$f00+'
    else:
        sign = '$fff'

    total_sec = ms // 1000
    hun = (ms % 1000) // 10
    mn = total_sec // 60
    sc = total_sec % 60

    if mn > 0:
        return f'{sign}{mn}:{sc:02d}.{hun:02d}'
    return f'{sign}{sc}.{hun:02d}'
