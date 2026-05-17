"""
plugin_cpll.py — Port of plugins/plugin.cpll.php (by ZiZa)

CP Live List: tracks which checkpoint each player is at and their time.
/cp    — show current standings for all players
/mycp  — show only players at the same CP as you
/cpll  — admin toggle (MasterAdmin only)
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

_cpll_array: dict = {}
_cpll_enabled: bool = True
_cpll_filter: bool = True   # filter out spectators in /cp listing
_cpll_trackcps: int = 0     # total CPs on current track


def get_cpll_array() -> dict:
    """Public accessor used by plugin_ztrack."""
    return _cpll_array


def register(aseco: 'Aseco'):
    aseco.register_event('onCheckpoint',       cpll_on_checkpoint)
    aseco.register_event('onPlayerFinish',     cpll_on_player_finish)
    aseco.register_event('onPlayerDisconnect', cpll_on_player_disconnect)
    aseco.register_event('onNewChallenge',     cpll_on_new_challenge)

    aseco.add_chat_command('cp',   'Shows current CP-Standings')
    aseco.add_chat_command('mycp', 'Shows players with the same amount of CPs as you')
    aseco.add_chat_command('cpll', 'Configuration of CPLL-plugin')

    aseco.register_event('onChat_cp',   chat_cp)
    aseco.register_event('onChat_mycp', chat_mycp)
    aseco.register_event('onChat_cpll', chat_cpll)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def cpll_on_checkpoint(aseco: 'Aseco', params: list):
    """params: [uid, login, time, lap, cp_index, ...]"""
    global _cpll_array
    if not _cpll_enabled or len(params) < 5:
        return
    login   = params[1]
    time_ms = params[2]
    cp_idx  = params[4] + 1  # 1-based
    _cpll_array[login] = {'time': time_ms, 'cp': cp_idx}


async def cpll_on_player_finish(aseco: 'Aseco', params: list):
    global _cpll_array
    if len(params) >= 2:
        login = params[1]
        _cpll_array.pop(login, None)


async def cpll_on_player_disconnect(aseco: 'Aseco', player: 'Player'):
    _cpll_array.pop(player.login, None)


async def cpll_on_new_challenge(aseco: 'Aseco', challenge):
    global _cpll_array, _cpll_trackcps
    _cpll_trackcps = max(0, getattr(challenge, 'nbchecks', 1) - 1)
    _cpll_array = {}


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

async def chat_cp(aseco: 'Aseco', command: dict):
    await _list_cps(aseco, command, is_mycp=False, cleanup=_cpll_filter)


async def chat_mycp(aseco: 'Aseco', command: dict):
    await _list_cps(aseco, command, is_mycp=True, cleanup=_cpll_filter)


async def chat_cpll(aseco: 'Aseco', command: dict):
    global _cpll_enabled, _cpll_filter
    admin: Player = command['author']
    args = command['params'].split(None, 2)
    sub  = args[0].lower() if args else ''

    if not aseco.is_master_admin(admin):
        return

    def _reply(msg: str):
        import asyncio
        asyncio.ensure_future(aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), admin.login))

    if sub == 'on':
        _cpll_enabled = True
        _reply('{#server}>> {#message}CPLL set to: {#highlite}ON')
    elif sub == 'off':
        _cpll_enabled = False
        _reply('{#server}>> {#message}CPLL set to: {#highlite}OFF')
    elif sub == 'filter':
        sub2 = args[1].lower() if len(args) > 1 else ''
        if sub2 == 'on':
            _cpll_filter = True
            _reply('{#server}>> {#message}CPLL specfilter set to: {#highlite}ON')
        elif sub2 == 'off':
            _cpll_filter = False
            _reply('{#server}>> {#message}CPLL specfilter set to: {#highlite}OFF')
        else:
            state = 'ON' if _cpll_filter else 'OFF'
            _reply(f'{{#server}}>> {{#message}}CPLL specfilter: {{#highlite}}{state}')
    else:
        state = 'ON' if _cpll_enabled else 'OFF'
        _reply(f'{{#server}}>> {{#message}}CPLL: {{#highlite}}{state}')


# ---------------------------------------------------------------------------
# Core display
# ---------------------------------------------------------------------------

async def _list_cps(aseco: 'Aseco', command: dict, is_mycp: bool, cleanup: bool):
    player: Player = command['author']

    if not _cpll_enabled:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}>> {#error}CPLiveList is currently disabled!'),
            player.login)
        return

    # Optionally filter spectators
    data = dict(_cpll_array)
    if cleanup:
        for lgn in list(data.keys()):
            p = aseco.server.players.get_player(lgn)
            if p and p.isspectator:
                del data[lgn]

    # /mycp: player must have a CP
    if is_mycp and player.login not in data:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}>> {#error}You did not reach a checkpoint yet!'),
            player.login)
        return

    # Sort by CP number descending (highest CP first), then time ascending
    sorted_data = sorted(data.items(),
                         key=lambda x: (-x[1]['cp'], x[1]['time']))

    my_cp = data.get(player.login, {}).get('cp', 0) if is_mycp else None

    header = f'Current Standings, total CPs: {_cpll_trackcps}'
    rows   = [['CP', 'Time', 'Player']]

    for lgn, val in sorted_data:
        if is_mycp and val['cp'] != my_cp:
            continue
        p = aseco.server.players.get_player(lgn)
        nick = p.nickname if p else lgn
        rows.append([str(val['cp']), _fmt_time(val['time']), nick])

    pages = [rows[i:i+10] for i in range(0, max(len(rows), 1), 10)]
    player.msgs = [[1, header, [0.7, 0.1, 0.2, 0.4], ['Icons64x64_1', 'TV']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


def _fmt_time(ms: int) -> str:
    sec = ms // 1000
    hun = (ms % 1000) // 10
    mn  = sec // 60
    sc  = sec % 60
    return f'{mn:02d}:{sc:02d}.{hun:02d}'
