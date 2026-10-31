"""
ztrack.py — Port of plugins/plugin.ztrack.php (by ZiZa)

CP-delta tracking overlay (ManiaLink id 19861111).
Shows checkpoint or sector deltas against a cached record.

/ztrack local <n>  — compare to local record #n
/ztrack dedi  <n>  — compare to dedi record #n
/ztrack auto [n]  — Dedi -> Local -> optional WRMania
/ztrack wrm <n>   — compare to WRMania when its app is loaded
/ztrack off        — disable
/ztrack            — show help
"""

from __future__ import annotations

from pyxaseco.core.widget_delivery import deliver_ui
from typing import TYPE_CHECKING

from pyxaseco.models import Gameinfo
from pyxaseco.app_services import get_dedi_db, get_dedimania_service
from pyxaseco.helpers import _send_multipage, format_time

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

ML_ID = 19861111

# Mode is the requested source; Source records the provider actually in use.
_zt: dict = {}
_runs: dict = {}

# cpll_array reference: {login: {'time': int, 'cp': int}}
# We read from cpll at checkpoint time


def register(aseco: 'Aseco'):
    aseco.add_chat_command('ztrack', 'Shows help for zTrack-Plugin')
    aseco.register_event('onChat_ztrack',            chat_ztrack)
    aseco.register_event('onPlayerInfoChanged',      zt_player_info_changed)
    aseco.register_event('onPlayerRetire',           zt_player_retire)
    aseco.register_event('onPlayerFinish1',          zt_player_finish)
    aseco.register_event('onBeginRound',             zt_begin_round)
    aseco.register_event('onRestartChallenge',       zt_begin_round)
    aseco.register_event('onNewChallenge',           zt_new_challenge)
    aseco.register_event('onCheckpoint',             zt_checkpoint)
    aseco.register_event('onPlayerConnect',          zt_player_connect)
    aseco.register_event('onPlayerDisconnect',       zt_player_disconnect)
    aseco.register_event('onEndRace',                zt_end_race)


# ---------------------------------------------------------------------------
# /ztrack command
# ---------------------------------------------------------------------------

def _checks(values, score, expected=0):
    if isinstance(values, str):
        values = values.split(',')
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 512:
        return []
    try:
        if any(isinstance(value, bool) or not str(value).isdecimal() for value in values):
            return []
        checks = [int(value) for value in values]
        best = int(score)
    except (TypeError, ValueError):
        return []
    if (checks[0] <= 0 or any(a >= b for a, b in zip(checks, checks[1:]))
            or checks[-1] != best or (expected > 0 and len(checks) != expected)):
        return []
    return checks


def _reference(aseco, mode, index):
    """Read existing caches only; optional record apps are never imported."""
    if index < 0 or aseco.server.gameinfo.mode == Gameinfo.STNT:
        return None
    expected = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
    active = getattr(aseco, 'active_apps', ()) or ()
    for source in (('Dedi', 'Local', 'WRMania') if mode == 'Auto' else (mode,)):
        checks, score, nickname = [], 0, ''
        if source == 'Local':
            rec = aseco.server.records.get_record(index)
            if rec is not None:
                checks, score = getattr(rec, 'checks', []), getattr(rec, 'score', 0)
                nickname = getattr(getattr(rec, 'player', None), 'nickname', '')
        elif source == 'Dedi' and 'records_dedimania' in active:
            provider = get_dedimania_service(aseco)
            db = get_dedi_db(aseco)
            track = db.get('Challenge', {})
            uid = track.get('UId') or track.get('Uid') or track.get('UID') or aseco.server.challenge.uid
            rows = track.get('Records', [])
            if (getattr(provider, '_connected', False) and db.get('RecsValid')
                    and uid == aseco.server.challenge.uid and isinstance(rows, list) and index < len(rows)):
                rec = rows[index]
                if isinstance(rec, dict):
                    checks, score = rec.get('Checks', []), rec.get('Best') or rec.get('Score', 0)
                    nickname = rec.get('NickName') or rec.get('Login', '')
        elif source == 'WRMania' and 'records_wrmania' in active:
            # No dependency on the WRMania package, even when its folder is absent.
            provider = aseco.get_service('service/records_wrmania')
            read = getattr(provider, 'checkpoint_records', None)
            rows = read(aseco) if callable(read) else []
            rec = next((row for row in rows if row.get('rank') == index + 1), None)
            if rec is not None:
                checks, score = rec.get('checkpointsMs', []), rec.get('score', 0)
                nickname = rec.get('nickname') or rec.get('login', '')
        checks = _checks(checks, score, expected)
        if checks:
            return {'source': source, 'checks': checks, 'score': int(score), 'nickname': nickname}
    return None


def _source(value):
    return {'auto': 'Auto', 'dedi': 'Dedi', 'local': 'Local',
            'wrm': 'WRMania', 'wrmania': 'WRMania'}.get(value.lower())


async def _show_splits(aseco, player, reference, rank, sectors):
    title = f'zTrack - {reference["source"]} {rank} - ' + ('Sector Times' if sectors else 'Checkpoint Times')
    rows, previous = [], 0
    for index, time in enumerate(reference['checks'], 1):
        rows.append([('S' if sectors else 'CP') + str(index), format_time(time - previous if sectors else time)])
        previous = time
    uid = aseco.server.challenge.uid

    def valid(runtime, _player):
        return runtime.server.challenge.uid == uid

    player.msgs = [[1, title, [1.0, .45, .55], ['Icons128x128_1', 'Rankings'], valid]]
    player.msgs.extend([[['Sector' if sectors else 'Checkpoint', 'Time']] + rows[i:i + 20]
                       for i in range(0, len(rows), 20)])
    await _send_multipage(aseco, player)


async def chat_ztrack(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    login = player.login
    args = str(command.get('params') or '').split()
    sub = args[0].lower() if args else ''

    async def send(msg):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)

    if sub == 'off':
        await send('{#message}[zTrack]: CP-tracking disabled')
        _zt[login] = {'Mode': '', 'Rec': 0, 'Target': login}
        await _send_ml_self(aseco, login, False)
        return

    split_view = sub in ('cps', 'sectors')
    if split_view:
        values = args[1:]
        mode = _source(values.pop(0)) if values and _source(values[0]) else 'Auto'
    elif sub.isdecimal():
        values, mode = args, 'Auto'
    else:
        values, mode = args[1:], _source(sub)
    if mode is None:
        await send('{#message}[zTrack]: /ztrack auto|local|dedi|wrm <rank> [cp|sector]. '
            '/ztrack cps|sectors [source] [rank] lists splits; /ztrack off disables tracking.')
        return
    rank = int(values.pop(0)) if values and values[0].isdecimal() and len(values[0]) <= 5 else 1
    comparison = values.pop(0).lower() if values and not split_view else 'cp'
    if not 1 <= rank <= 10000 or values or comparison not in ('cp', 'sector'):
        await send('{#message}[zTrack]: Use a positive rank and optional cp or sector; see /ztrack help.')
        return
    reference = _reference(aseco, mode, rank - 1)
    if reference is None:
        await send(f'{{#message}}[zTrack]: No usable {mode} record {rank} with complete checkpoint data.')
        return
    if split_view:
        await _show_splits(aseco, player, reference, rank, sub == 'sectors')
        return
    _zt[login] = {'Mode': mode, 'Source': reference['source'], 'Rec': rank - 1,
                  'Target': _resolve_view_target(aseco, player) or login, 'Comparison': comparison}
    await send(f'{{#message}}[zTrack]: {comparison.capitalize()} tracking comparing to '
               f'{{#highlite}}{reference["source"]} record {rank}.')
    if _is_viewer_spec_like(player):
        await _send_ml(aseco, login, True)
    else:
        await _send_ml_self(aseco, login, True)



# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def zt_new_challenge(aseco: 'Aseco', _challenge):
    global _zt
    _zt = {}
    _runs.clear()

    xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
    await deliver_ui(aseco, 'SendDisplayManialinkPage', xml, 0, False)


async def zt_end_race(aseco: 'Aseco', _params):
    xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
    await deliver_ui(aseco, 'SendDisplayManialinkPage', xml, 0, False)


async def zt_player_connect(aseco: 'Aseco', player: 'Player'):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(
            '{#server}>> {#message}This server is running zTrack, '
            'type {#highlite}/ztrack {#message}for more information'),
        player.login)


async def zt_player_disconnect(aseco: 'Aseco', player: 'Player'):
    _zt.pop(player.login, None)
    _runs.pop(player.login, None)


async def zt_begin_round(aseco: 'Aseco', _params=None):
    _runs.clear()
    for player in aseco.server.players.all():
        login = getattr(player, 'login', '')
        if not login or login not in _zt:
            continue

        enabled = _zt[login].get('Mode', '') != ''
        if _is_viewer_spec_like(player):
            _zt[login]['Target'] = _resolve_view_target(aseco, player) or login
            await _send_ml(aseco, login, enabled)
        else:
            _zt[login]['Target'] = login
            await _send_ml_self(aseco, login, enabled)


async def zt_player_info_changed(aseco: 'Aseco', changes: dict):
    """Called when a player changes spectator status."""
    login = changes.login

    if login not in _zt:
        _zt[login] = {'Mode': '', 'Rec': 0, 'Target': login}

    if _is_viewer_spec_like(changes):
        target_login = _resolve_view_target(aseco, changes)
        if target_login:
            _zt[login]['Target'] = target_login
            enabled = _zt[login].get('Mode', '') != ''
            if enabled:
                await _send_ml(aseco, login, True)
        else:
            _zt[login]['Target'] = login if bool(getattr(changes, 'finished_waiting', False)) else ''
            enabled = _zt[login].get('Mode', '') != ''
            if enabled:
                await _send_ml(aseco, login, True if _zt[login]['Target'] else False)
    else:
        _zt[login]['Target'] = login
        enabled = _zt[login].get('Mode', '') != ''
        await _send_ml_self(aseco, login, enabled)


async def zt_player_retire(aseco: 'Aseco', player: 'Player'):
    login = getattr(player, 'login', '')
    _runs.pop(login, None)
    if not login:
        return
    if login not in _zt:
        _zt[login] = {'Mode': '', 'Rec': 0, 'Target': login}
    _zt[login]['Target'] = _resolve_view_target(aseco, player) or login
    enabled = _zt[login].get('Mode', '') != ''
    await _send_ml(aseco, login, enabled)


async def zt_player_finish(aseco: 'Aseco', finish_item):
    player = getattr(finish_item, 'player', None)
    login = getattr(player, 'login', '')
    if not login:
        return
    if login not in _zt:
        _zt[login] = {'Mode': '', 'Rec': 0, 'Target': login}

    enabled = _zt[login].get('Mode', '') != ''
    mode = getattr(getattr(aseco, 'server', None), 'gameinfo', None)
    mode = getattr(mode, 'mode', -1)
    waiting_mode = mode in (Gameinfo.RNDS, Gameinfo.TEAM, Gameinfo.LAPS, Gameinfo.CUP)

    if bool(getattr(player, 'retired', False)):
        _zt[login]['Target'] = _resolve_view_target(aseco, player) or login
        await _send_ml(aseco, login, enabled)
    elif waiting_mode and bool(getattr(player, 'finished_waiting', False)):
        _zt[login]['Target'] = _resolve_view_target(aseco, player) or login
        await _send_ml(aseco, login, enabled)
    else:
        _zt[login]['Target'] = login
        await _send_ml_self(aseco, login, enabled)


async def zt_checkpoint(aseco: 'Aseco', params: list):
    """Use cumulative splits for CP deltas, adjacent splits for sector deltas."""
    if len(params) < 5 or aseco.server.gameinfo.mode == Gameinfo.STNT:
        return
    try:
        cp_login, absolute, index = params[1], int(params[2]), int(params[4])
        lap = int(params[3])
    except (TypeError, ValueError):
        return
    if absolute <= 0 or index < 0:
        return
    count = int(getattr(aseco.server.challenge, 'nbchecks', 0) or 0)
    state = _runs.get(cp_login, {'index': -1, 'absolute': 0, 'base': 0, 'time': 0})
    if index == 0:
        state = {'index': -1, 'absolute': 0, 'base': 0, 'time': 0}
    laps = aseco.server.gameinfo.mode == Gameinfo.LAPS and count > 0
    relative_index = index % count if laps else index
    if laps and index != state['index'] + 1:
        state['base'] = None
    time = absolute - state['base'] if state['base'] is not None else None
    previous = (0 if relative_index == 0 else state['time']
                if state['index'] == index - 1 and absolute > state['absolute'] else None)
    _runs[cp_login] = {'index': index, 'absolute': absolute, 'base': state['base'], 'time': time}
    if laps and lap > 0 and lap * count == index + 1:
        _runs[cp_login]['base'] = absolute
    for login, info in list(_zt.items()):
        if info.get('Target') != cp_login or not info.get('Mode'):
            continue
        reference = _reference(aseco, info['Mode'], int(info.get('Rec', 0)))
        info['Source'] = reference['source'] if reference else info['Mode']
        delta = None
        if reference and time is not None and relative_index < len(reference['checks']):
            checks = reference['checks']
            target = checks[relative_index]
            if info.get('Comparison') == 'sector':
                if previous is not None:
                    target -= checks[relative_index - 1] if relative_index else 0
                    delta = (time - previous) - target
            else:
                delta = time - target
        # Clear the previous number if the selected provider/split is unavailable.
        if login == cp_login:
            await _send_ml_self(aseco, login, delta if delta is not None else True)
        else:
            await _send_ml(aseco, login, delta if delta is not None else True)



# ---------------------------------------------------------------------------
# ManiaLink helpers
# ---------------------------------------------------------------------------

def _mode_label(info):
    source = info.get('Source') or info.get('Mode', '')
    suffix = ' sector' if info.get('Comparison') == 'sector' else ''
    return f'{source} {info.get("Rec", 0) + 1}{suffix}'


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
        mode_label = _mode_label(info)
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
        mode_label = _mode_label(info)
        xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<manialink id="{ML_ID}">'
               f'<frame posn="0 -43.5 1">'
               f'<label scale="0.5" posn="0 0 1" halign="center" valign="center" style="TextRaceMessage" text="{mode_label}"/>'
               f'<label scale="0.5" posn="0 -2.0 1" halign="center" valign="center" style="TextRaceChrono" text="{txt}"/>'
               f'</frame>'
               f'</manialink>')
    else:
        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'

    await deliver_ui(aseco,
        'SendDisplayManialinkPageToLogin', login, xml, 0, False
    )


async def _send_ml_self(aseco: 'Aseco', login: str, time_val):
    """Self (player) overlay — positioned higher on screen."""
    if time_val is True:
        info = _zt.get(login, {})
        mode_label = _mode_label(info)
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
        mode_label = _mode_label(info)
        xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<manialink id="{ML_ID}">'
               f'<frame posn="0 -30.7 1">'
               f'<label scale="0.35" posn="0 0 1" halign="center" valign="center" style="TextRaceMessage" text="{mode_label}"/>'
               f'<label scale="0.5" posn="0 -1.9 1" halign="center" valign="center" style="TextRaceChrono" text="{txt}"/>'
               f'</frame>'
               f'</manialink>')
    else:
        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'

    await deliver_ui(aseco,
        'SendDisplayManialinkPageToLogin', login, xml, 0, False
    )


def _resolve_spec_target(aseco: 'Aseco', player: 'Player') -> str:
    """
    Return the login of the player a spectator is watching.
    Returns empty string if not spectating or target cannot be determined.
    """
    if not _is_viewer_spec_like(player):
        return ''
    spec_status = int(getattr(player, 'spectatorstatus', 0) or 0)
    target_pid = spec_status // 10000
    own_pid = int(getattr(player, 'pid', 0) or 0)
    if target_pid <= 0 or target_pid == own_pid:
        return ''
    return _pid_to_login(aseco, target_pid)


def _is_viewer_spec_like(player: 'Player') -> bool:
    if not player:
        return False

    if bool(getattr(player, 'retired', False)):
        return True

    if bool(getattr(player, 'finished_waiting', False)):
        return True

    try:
        spec_status = int(getattr(player, 'spectatorstatus', 0) or 0)
    except Exception:
        spec_status = 0

    if spec_status > 0 and (spec_status % 10) != 0:
        spec_mode = (spec_status // 10) % 100
        target_pid = spec_status // 10000
        own_pid = int(getattr(player, 'pid', 0) or 0)
        return spec_mode > 0 and target_pid != own_pid

    return False


def _resolve_view_target(aseco: 'Aseco', player: 'Player') -> str:
    target_login = _resolve_spec_target(aseco, player)
    if target_login:
        return target_login
    if bool(getattr(player, 'retired', False)) or bool(getattr(player, 'finished_waiting', False)):
        return getattr(player, 'login', '') or ''
    return ''


def _pid_to_login(aseco: 'Aseco', pid: int) -> str:
    for p in aseco.server.players.all():
        if p.pid == pid:
            return p.login
    return ''
