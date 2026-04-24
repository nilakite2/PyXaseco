"""
plugin_rasp_chat.py — Port of plugins/plugin.rasp_chat.php

Private messages, PM log, and social shout-out commands:
/pm /pma /pmlog /hi /bye /thx /lol /lool /brb /afk /gg /gr /n1 /bgm /official /bootme
"""

from __future__ import annotations
from collections import deque
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, display_manialink_multi, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

PM_BUF_LEN = 30
LINE_LEN = 70


def register(aseco: 'Aseco'):
    cmds = [
        ('pm',       'Sends a private message to login or Player_ID'),
        ('pma',      'Sends a private message to player & admins'),
        ('pmlog',    'Displays log of your recent private messages'),
        ('hi',       'Sends a Hi message to everyone'),
        ('bye',      'Sends a Bye message to everyone'),
        ('thx',      'Sends a Thanks message to everyone'),
        ('lol',      'Sends a Lol message to everyone'),
        ('lool',     'Sends a Lool message to everyone'),
        ('brb',      'Sends a Be Right Back message to everyone'),
        ('afk',      'Sends an Away From Keyboard message to everyone'),
        ('gg',       'Sends a Good Game message to everyone'),
        ('gr',       'Sends a Good Race message to everyone'),
        ('n1',       'Sends a Nice One message to everyone'),
        ('bgm',      'Sends a Bad Game message to everyone'),
        ('official', 'Shows a helpful message ;-)'),
        ('bootme',   'Boot yourself from the server'),
    ]
    for name, help_text in cmds:
        aseco.add_chat_command(name, help_text)
        aseco.register_event(f'onChat_{name}', globals()[f'chat_{name}'])


# ---------------------------------------------------------------------------
# Private messages
# ---------------------------------------------------------------------------

async def chat_pm(aseco: 'Aseco', command: dict):
    import time as _time
    player: Player = command['author']
    parts = command['params'].split(None, 1)
    if not parts:
        await _send(aseco, player.login, '{#server}> {#error}No target specified!')
        return

    target = _find_player(aseco, player, parts[0])
    if not target:
        return

    msg_text = parts[1] if len(parts) > 1 else ''
    if not msg_text:
        await _send(aseco, player.login, '{#server}> {#error}No message!')
        return

    stamp = _time.strftime('%H:%M:%S')
    pl_nick = player.nickname.replace('$w','').replace('$W','')
    tg_nick = target.nickname.replace('$w','').replace('$W','')

    _append_pm(player, stamp, pl_nick, msg_text)
    _append_pm(target, stamp, pl_nick, msg_text)

    msg = (f'{{#error}}-pm-$g[{pl_nick}$z$s$i->{tg_nick}$z$s$i]$i '
           f'{{#interact}}{msg_text}')
    msg_colored = aseco.format_colors(msg)

    mc = aseco.client.build_multicall()
    mc.add('ChatSendServerMessageToLogin', msg_colored, target.login)
    mc.add('ChatSendServerMessageToLogin', msg_colored, player.login)
    await mc.query_ignore_result()


async def chat_pma(aseco: 'Aseco', command: dict):
    import time as _time
    player: Player = command['author']

    if not aseco.allow_ability(player, 'chat_pma'):
        await _send(aseco, player.login, aseco.get_chat_message('NO_ADMIN'))
        return

    parts = command['params'].split(None, 1)
    if not parts:
        await _send(aseco, player.login, '{#server}> {#error}No target specified!')
        return

    target = _find_player(aseco, player, parts[0])
    if not target:
        return

    msg_text = parts[1] if len(parts) > 1 else ''
    if not msg_text:
        await _send(aseco, player.login, '{#server}> {#error}No message!')
        return

    stamp = _time.strftime('%H:%M:%S')
    pl_nick = player.nickname.replace('$w','').replace('$W','')
    tg_nick = target.nickname.replace('$w','').replace('$W','')
    msg = (f'{{#error}}-pm-$g[{pl_nick}$z$s$i->{tg_nick}$z$s$i]$i '
           f'{{#interact}}{msg_text}')
    msg_colored = aseco.format_colors(msg)

    mc = aseco.client.build_multicall()
    mc.add('ChatSendServerMessageToLogin', msg_colored, target.login)
    _append_pm(target, stamp, pl_nick, msg_text)

    for admin in aseco.server.players.all():
        if aseco.allow_ability(admin, 'chat_pma'):
            _append_pm(admin, stamp, pl_nick, msg_text)
            mc.add('ChatSendServerMessageToLogin', msg_colored, admin.login)

    await mc.query_ignore_result()


async def chat_pmlog(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    login = player.login

    if not player.pmbuf:
        await _send(aseco, login, '{#server}> {#error}No PM history found!')
        return

    head = 'Your recent PM history:'
    rows = []
    show_times = aseco.settings.chatpmlog_times
    for stamp, nick, text in player.pmbuf:
        clean = strip_colors(text, for_tm=False)
        prefix = f'<{{#server}}{stamp}$z> ' if show_times else ''
        rows.append([f'$z{prefix}[{{#black}}{nick}$z] {clean}'])

    pages = [rows[i:i+15] for i in range(0, max(len(rows),1), 15)]
    player.msgs = [[1, head, [1.2], ['Icons64x64_1', 'Outbox']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


# ---------------------------------------------------------------------------
# Social commands — check mute list, then broadcast
# ---------------------------------------------------------------------------

def _muted(aseco: 'Aseco', player: 'Player', cmd: str):
    if player.login in aseco.server.mutelist:
        return format_text(aseco.get_chat_message('MUTED'), cmd)
    return None


async def _broadcast(aseco: 'Aseco', player: 'Player', msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage', aseco.format_colors(msg))


async def chat_hi(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/hi'):
        return await _send(aseco, p.login, m)
    target = f'Hello {command["params"]} !' if command['params'] else 'Hello All !'
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}{target}')


async def chat_bye(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/bye'):
        return await _send(aseco, p.login, m)
    target = f'Bye {command["params"]} !' if command['params'] else 'I have to go... Bye All !'
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}{target}')


async def chat_thx(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/thx'):
        return await _send(aseco, p.login, m)
    target = f'Thanks {command["params"]} !' if command['params'] else 'Thanks All !'
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}{target}')


async def chat_lol(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/lol'):
        return await _send(aseco, p.login, m)
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}LoL !')


async def chat_lool(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/lool'):
        return await _send(aseco, p.login, m)
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}LooOOooL !')


async def chat_brb(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/brb'):
        return await _send(aseco, p.login, m)
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}Be Right Back !')


async def chat_afk(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/afk'):
        return await _send(aseco, p.login, m)
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}Away From Keyboard !')

    _raw_ss = getattr(p, 'spectatorstatus', None)
    _p_is_spec = ((int(_raw_ss) % 10) != 0) if _raw_ss is not None else bool(p.isspectator)
    if aseco.settings.afk_force_spec and not _p_is_spec:
        try:
            srv_opts = await aseco.client.query('GetServerOptions', 0) or {}
            max_spec = int(srv_opts.get('CurrentMaxSpectators', 1) or 1)
            if max_spec == 0:
                logger.warning('[rasp_chat] /afk: server MaxSpectators=0, cannot force spec')
                return
            await aseco.client.query('ForceSpectator', p.login, 1)
            await aseco.client.query('ForceSpectator', p.login, 0)
            mc = aseco.client.build_multicall()
            mc.add('ForceSpectatorTarget', p.login, '', 2)
            mc.add('SpectatorReleasePlayerSlot', p.login)
            await mc.query_ignore_result()
        except Exception as _afk_err:
            logger.warning('[rasp_chat] /afk ForceSpectator failed for %s: %s',
                           p.login, _afk_err)


async def chat_gg(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/gg'):
        return await _send(aseco, p.login, m)
    target = f'Good Game {command["params"]} !' if command['params'] else 'Good Game All !'
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}{target}')


async def chat_gr(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/gr'):
        return await _send(aseco, p.login, m)
    target = f'Good Race {command["params"]} !' if command['params'] else 'Good Race !'
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}{target}')


async def chat_n1(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/n1'):
        return await _send(aseco, p.login, m)
    target = f'Nice One {command["params"]} !' if command['params'] else 'Nice One !'
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}{target}')


async def chat_bgm(aseco: 'Aseco', command: dict):
    p = command['author']
    if m := _muted(aseco, p, '/bgm'):
        return await _send(aseco, p.login, m)
    await _broadcast(aseco, p, f'$g[{p.nickname}$z$s] {{#interact}}Bad Game for Me :(')


async def chat_official(aseco: 'Aseco', command: dict):
    try:
        from pyxaseco.plugins.plugin_rasp import _rasp_messages
        msg = _rasp_messages.get('OFFICIAL', [''])[0]
    except ImportError:
        msg = '{#server}> Official mode active!'
    await _send(aseco, command['author'].login, msg)


async def chat_bootme(aseco: 'Aseco', command: dict):
    p = command['author']
    try:
        from pyxaseco.plugins.plugin_rasp import _rasp_messages
        msg = format_text(_rasp_messages.get('BOOTME', ['{1} says bye!'])[0], p.nickname)
        dialog = _rasp_messages.get('BOOTME_DIALOG', [''])[0]
    except ImportError:
        msg = f'{p.nickname} says bye!'
        dialog = ''

    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))
    if dialog:
        await aseco.client.query_ignore_result(
            'Kick', p.login, aseco.format_colors(dialog + '$z'))
    else:
        await aseco.client.query_ignore_result('Kick', p.login)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_player(aseco: 'Aseco', sender: 'Player', target_str: str) -> 'Player | None':
    """Resolve a login string or numeric player ID to a Player object."""
    # Try direct login lookup first
    p = aseco.server.players.get_player(target_str)
    if p:
        return p

    # Try numeric ID (1-based index into player list)
    if target_str.isdigit():
        idx = int(target_str) - 1
        all_players = aseco.server.players.all()
        if 0 <= idx < len(all_players):
            return all_players[idx]

    import asyncio
    asyncio.ensure_future(aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(f'{{#server}}> {{#error}}Player {target_str!r} not found!'),
        sender.login))
    return None


def _append_pm(player: 'Player', stamp: str, from_nick: str, text: str):
    if not hasattr(player, 'pmbuf') or player.pmbuf is None:
        player.pmbuf = []
    if len(player.pmbuf) >= PM_BUF_LEN:
        player.pmbuf.pop(0)
    player.pmbuf.append((stamp, from_nick, text))


async def _send(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
