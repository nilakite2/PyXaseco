"""
plugin_ztrack.py — Port of plugins/plugin.ztrack.php (by ZiZa)

CP-delta tracking overlay (ManiaLink id 19861111).
Shows time delta vs a chosen local or dedi record at each checkpoint.

/ztrack local <n>  — compare to local record #n
/ztrack dedi  <n>  — compare to dedi record #n  (stub, requires dedi plugin)
/ztrack off        — disable
/ztrack            — show help
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

ML_ID = 19861111

# {login: {'Mode': 'Local'|'Dedi'|'', 'Rec': int, 'Target': str}}
_zt: dict = {}

# cpll_array reference: {login: {'time': int, 'cp': int}}
# We read from plugin_cpll at checkpoint time


def register(aseco: 'Aseco'):
    aseco.add_chat_command('ztrack', 'Shows help for zTrack-Plugin')
    aseco.register_event('onChat_ztrack',            chat_ztrack)
    aseco.register_event('onPlayerInfoChanged',      zt_player_info_changed)
    aseco.register_event('onNewChallenge',           zt_new_challenge)
    aseco.register_event('onCheckpoint',             zt_checkpoint)
    aseco.register_event('onPlayerConnect',          zt_player_connect)
    aseco.register_event('onPlayerDisconnect',       zt_player_disconnect)
    aseco.register_event('onEndRace',                zt_end_race)


# ---------------------------------------------------------------------------
# /ztrack command
# ---------------------------------------------------------------------------

async def chat_ztrack(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    login = player.login
    args = command['params'].split(None, 2)
    sub = args[0].lower() if args else ''

    def _send(msg: str):
        import asyncio
        asyncio.ensure_future(aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login))

    if sub == 'local':
        if len(args) < 2 or not args[1].isdigit():
            _send('{#message}[zTrack]: Please select a local record')
            return

        idx = int(args[1]) - 1
        rec = aseco.server.records.get_record(idx)

        if rec is None:
            _send(f'{{#message}}[zTrack]: {{#highlite}}Local record {idx+1}{{#message}} does not exist')
            return

        if not getattr(rec, 'checks', None):
            _send(f'{{#message}}[zTrack]: {{#highlite}}Local record {idx+1}{{#message}} has no checkpoint data')
            return

        # When spectating, track the target player's CPs, not the spectator's own.
        _target = _resolve_spec_target(aseco, player)
        _zt.setdefault(login, {}).update({
            'Mode': 'Local',
            'Rec': idx,
            'Target': _target or login,
        })
        _send(f'{{#message}}[zTrack]: CP-tracking is now comparing to {{#highlite}}local record {idx+1}')

        if player.isspectator:
            await _send_ml(aseco, login, True)
        else:
            await _send_ml_self(aseco, login, True)

    elif sub == 'dedi':
        if len(args) < 2 or not args[1].isdigit():
            _send('{#message}[zTrack]: Please select a dedi record')
            return

        idx = int(args[1]) - 1

        try:
            from pyxaseco.plugins.plugin_dedimania import dedi_db
            dedi_recs = dedi_db.get('Challenge', {}).get('Records', [])
        except Exception:
            dedi_recs = []

        if idx < 0 or idx >= len(dedi_recs):
            _send(f'{{#message}}[zTrack]: {{#highlite}}Dedi record {idx+1}{{#message}} does not exist')
            return

        checks = dedi_recs[idx].get('Checks', []) or []
        if not checks:
            _send(f'{{#message}}[zTrack]: {{#highlite}}Dedi record {idx+1}{{#message}} has no checkpoint data')
            return

        _target = _resolve_spec_target(aseco, player)
        _zt.setdefault(login, {}).update({
            'Mode': 'Dedi',
            'Rec': idx,
            'Target': _target or login,
        })
        _send(f'{{#message}}[zTrack]: CP-tracking comparing to {{#highlite}}Dedi record {idx+1}')
        if player.isspectator:
            await _send_ml(aseco, login, True)
        else:
            await _send_ml_self(aseco, login, True)

    elif sub == 'off':
        _send('{#message}[zTrack]: CP-tracking disabled')
        _zt[login] = {'Mode': '', 'Rec': 0, 'Target': login}

        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPageToLogin',
            login,
            xml,
            0,
            False
        )
        
    else:
        _send(
            '{#message}[zTrack]: Type {#highlite}/ztrack local <nr> '
            '{#message}or {#highlite}/ztrack dedi <nr> '
            "{#message}to compare the current racing time of yourself or the person you're speccing. "
            'Use {#highlite}/ztrack off {#message}to disable.'
        )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def zt_new_challenge(aseco: 'Aseco', _challenge):
    global _zt
    _zt = {}

    xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', xml, 0, False)


async def zt_end_race(aseco: 'Aseco', _params):
    xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', xml, 0, False)


async def zt_player_connect(aseco: 'Aseco', player: 'Player'):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(
            '{#server}>> {#message}This server is running zTrack, '
            'type {#highlite}/ztrack {#message}for more information'),
        player.login)


async def zt_player_disconnect(aseco: 'Aseco', player: 'Player'):
    _zt.pop(player.login, None)


async def zt_player_info_changed(aseco: 'Aseco', changes: dict):
    """Called when a player changes spectator status."""
    login = changes.login
    # spectatorstatus is the packed GBX integer: digits 4-7 = PID of spectated player.
    spec_status = int(getattr(changes, 'spectatorstatus', 0) or 0)
    is_spec = changes.isspectator

    if login not in _zt:
        _zt[login] = {'Mode': '', 'Rec': 0, 'Target': login}

    if is_spec:
        # Spectating — decode target PID from packed spectatorstatus
        target_pid = spec_status // 10000
        target_login = _pid_to_login(aseco, target_pid) if target_pid > 0 else ''
        if target_login:
            _zt[login]['Target'] = target_login
            enabled = _zt[login].get('Mode', '') != ''
            if enabled:
                await _send_ml(aseco, login, True)
        else:
            # Auto-target or no target yet — hide until target is known
            _zt[login]['Target'] = ''
            await _send_ml(aseco, login, False)
    else:
        # Back to playing — track own CPs
        _zt[login]['Target'] = login
        enabled = _zt[login].get('Mode', '') != ''
        await _send_ml_self(aseco, login, enabled)


async def zt_checkpoint(aseco: 'Aseco', params: list):
    """params: [uid, login, time, lap, cp_index, ...]"""
    if len(params) < 5:
        return

    cp_login = params[1]
    cp_time = int(params[2])
    cp_index = int(params[4]) + 1  # 1-based

    for login, info in list(_zt.items()):
        if info.get('Target') != cp_login:
            continue

        mode = info.get('Mode', '')
        if not mode:
            continue

        rec_idx = int(info.get('Rec', 0) or 0)
        delta = None

        if mode == 'Local':
            rec = aseco.server.records.get_record(rec_idx)
            if rec and getattr(rec, 'checks', None) and cp_index <= len(rec.checks):
                try:
                    target_cp = int(rec.checks[cp_index - 1])
                    delta = cp_time - target_cp
                except Exception:
                    delta = None

        elif mode == 'Dedi':
            try:
                from pyxaseco.plugins.plugin_dedimania import dedi_db
                dedi_recs = dedi_db.get('Challenge', {}).get('Records', [])
                if 0 <= rec_idx < len(dedi_recs):
                    rec = dedi_recs[rec_idx]
                    checks = rec.get('Checks', []) or []
                    if cp_index <= len(checks):
                        target_cp = int(checks[cp_index - 1])
                        delta = cp_time - target_cp
            except Exception:
                delta = None

        if delta is not None:
            if login == cp_login:
                await _send_ml_self(aseco, login, delta)
            else:
                await _send_ml(aseco, login, delta)


# ---------------------------------------------------------------------------
# ManiaLink helpers
# ---------------------------------------------------------------------------

def _fmt_delta(ms: int) -> str:
    sign = '$s$f00+' if ms >= 0 else '$s$00f-'
    ms = abs(ms)
    sec = ms // 1000
    hun = (ms % 1000) // 10
    mn  = sec // 60
    sc  = sec % 60
    return f'{sign}{mn:02d}:{sc:02d}.{hun:02d}'


async def _send_ml(aseco: 'Aseco', login: str, time_val):
    """Spectator overlay — positioned lower on screen."""
    if time_val is True:
        info = _zt.get(login, {})
        mode_label = f'{info.get("Mode","")} {info.get("Rec",0)+1}'
        xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<manialink id="{ML_ID}">'
               f'<frame posn="0 -43.5 1">'
               f'<label scale="0.5" posn="0 0 1" halign="center" valign="center" style="TextRaceMessage" text="{mode_label}"/>'
               f'<label scale="0.5" posn="0 -2.0 1" halign="center" valign="center" style="TextRaceChrono" text="--:--.--"/>'
               f'</frame>'
               f'</manialink>')
    elif isinstance(time_val, int) and not isinstance(time_val, bool):
        txt = _fmt_delta(time_val)
        info = _zt.get(login, {})
        mode_label = f'{info.get("Mode","")} {info.get("Rec",0)+1}'
        xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<manialink id="{ML_ID}">'
               f'<frame posn="0 -43.5 1">'
               f'<label scale="0.5" posn="0 0 1" halign="center" valign="center" style="TextRaceMessage" text="{mode_label}"/>'
               f'<label scale="0.5" posn="0 -2.0 1" halign="center" valign="center" style="TextRaceChrono" text="{txt}"/>'
               f'</frame>'
               f'</manialink>')
    else:
        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'

    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin', login, xml, 0, False
    )


async def _send_ml_self(aseco: 'Aseco', login: str, time_val):
    """Self (player) overlay — positioned higher on screen."""
    if time_val is True:
        info = _zt.get(login, {})
        mode_label = f'{info.get("Mode","")} {info.get("Rec",0)+1}'
        xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<manialink id="{ML_ID}">'
               f'<frame posn="0 -30.7 1">'
               f'<label scale="0.35" posn="0 0 1" halign="center" valign="center" style="TextRaceMessage" text="{mode_label}"/>'
               f'<label scale="0.5" posn="0 -1.9 1" halign="center" valign="center" style="TextRaceChrono" text="--:--.--"/>'
               f'</frame>'
               f'</manialink>')
    elif isinstance(time_val, int) and not isinstance(time_val, bool):
        txt = _fmt_delta(time_val)
        info = _zt.get(login, {})
        mode_label = f'{info.get("Mode","")} {info.get("Rec",0)+1}'
        xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<manialink id="{ML_ID}">'
               f'<frame posn="0 -30.7 1">'
               f'<label scale="0.35" posn="0 0 1" halign="center" valign="center" style="TextRaceMessage" text="{mode_label}"/>'
               f'<label scale="0.5" posn="0 -1.9 1" halign="center" valign="center" style="TextRaceChrono" text="{txt}"/>'
               f'</frame>'
               f'</manialink>')
    else:
        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'

    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin', login, xml, 0, False
    )


def _resolve_spec_target(aseco: 'Aseco', player: 'Player') -> str:
    """
    Return the login of the player a spectator is watching.
    Returns empty string if not spectating or target cannot be determined.
    """
    if not getattr(player, 'isspectator', False):
        return ''
    spec_status = int(getattr(player, 'spectatorstatus', 0) or 0)
    target_pid = spec_status // 10000
    if target_pid <= 0:
        return ''
    return _pid_to_login(aseco, target_pid)


def _pid_to_login(aseco: 'Aseco', pid: int) -> str:
    for p in aseco.server.players.all():
        if p.pid == pid:
            return p.login
    return ''
