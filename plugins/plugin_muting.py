"""
plugin_muting.py — Port of plugins/plugin.muting.php

Per-player chat muting. When player A mutes player B:
  - B's chat lines are hidden from A
  - A's chat buffer (mutebuf) replays older visible lines to fill the window
  - Server-wide system messages are still buffered for /refresh

Also exports send_window_message() used by vote/jukebox plugins.

Commands: /mute /unmute /mutelist /refresh
"""

from __future__ import annotations
import re
import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, strip_colors, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# Signal to other plugins that muting is available
muting_available: bool = False

# Compiled pattern matching known global server messages (>> prefix)
_globalpat: re.Pattern | None = None

CHAT_WINDOW_LEN = 28  # TM chat window lines
MSG_BUF_LEN     = 21  # msglog history length
MSG_WIN_LEN     = 5   # lines shown in window message
MSG_LINE_LEN    = 800 # max chars per message line

# Message history buffer (for send_window_message / /msglog)
_msgbuf: list = []


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup', _init_globalpat)
    aseco.register_event('onChat',    _handle_muting)

    aseco.add_chat_command('mute',     "Mute another player's chat messages")
    aseco.add_chat_command('unmute',   "UnMute another player's chat messages")
    aseco.add_chat_command('mutelist', 'Display list of muted players')
    aseco.add_chat_command('refresh',  'Refresh chat window')

    aseco.register_event('onChat_mute',     chat_mute)
    aseco.register_event('onChat_unmute',   chat_unmute)
    aseco.register_event('onChat_mutelist', chat_mutelist)
    aseco.register_event('onChat_refresh',  chat_refresh)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

async def _init_globalpat(aseco: 'Aseco', _data):
    global _globalpat, muting_available
    _globalpat = re.compile(r'^\$z\$s|\$\$z\$\$s')
    muting_available = True
    aseco.console('[Muting] Muting plugin ready.')


# ---------------------------------------------------------------------------
# Public API — used by plugin_msglog / send_window_message callers
# ---------------------------------------------------------------------------

async def send_window_message(aseco: 'Aseco', message: str, scoreboard: bool):
    """
    Buffer a system message and display the recent window to all players.
    Used by voting, jukebox, and other plugins when window_style is set.
    """
    global _msgbuf
    # Append message lines to buffer
    for line in message.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Wrap long lines
        while len(line) > MSG_LINE_LEN:
            _msgbuf.append(aseco.format_colors(line[:MSG_LINE_LEN]))
            line = '$z$s$n' + line[MSG_LINE_LEN:]
        if len(_msgbuf) >= MSG_BUF_LEN:
            _msgbuf.pop(0)
        _msgbuf.append(aseco.format_colors(line))

    # Show recent window
    if scoreboard:
        try:
            timeout_info = await aseco.client.query('GetChatTime') or {}
            timeout = (timeout_info.get('CurrentValue', 0) + 5000)
        except Exception:
            timeout = 10000
    else:
        timeout = aseco.settings.window_timeout * 1000

    lines = _msgbuf[-MSG_WIN_LEN:] if _msgbuf else []
    await _display_msgwindow(aseco, lines, timeout)


async def _display_msgwindow(aseco: 'Aseco', lines: list, timeout: int):
    """Show a small ManiaLink message window to all players."""
    if not lines:
        return
    text = '\n'.join(lines)
    style = aseco.settings.window_style
    ml_id = 90010  # dedicated window ML ID

    # Build a simple overlay ManiaLink
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<manialinks>'
        f'<manialink id="{ml_id}">'
        f'<frame posn="-63 -37 0">'
        f'<label sizen="55 3" style="TextStaticSmall" '
        f'text="{text.replace(chr(34), chr(39))}" '
        f'autonewline="1"/>'
        f'</frame>'
        f'</manialink>'
        f'</manialinks>'
    )
    try:
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPage', xml, timeout, False)
    except Exception:
        pass


def get_msgbuf() -> list:
    """Return the message buffer (used by plugin_msglog)."""
    return _msgbuf


# ---------------------------------------------------------------------------
# onChat handler — intercept and buffer muted players' lines
# ---------------------------------------------------------------------------

async def _handle_muting(aseco: 'Aseco', chat: list):
    if len(chat) < 4:
        return

    uid, login, text, is_cmd = chat[0], chat[1], chat[2], chat[3]

    if uid != aseco.server.id:
        # Player chat — check mute lists
        if is_cmd:
            return  # registered slash commands are hidden anyway
        chatter = aseco.server.players.get_player(login)
        if not chatter:
            return
        chatter_nick = chatter.nickname

        for player in aseco.server.players.all():
            if login in player.mutelist or login in aseco.server.mutelist:
                # Replay buffer to this player to push muted message off screen
                if player.mutebuf:
                    buf = '\n'.join('$z$z$s' + line for line in player.mutebuf)
                    try:
                        await aseco.client.query_ignore_result(
                            'ChatSendServerMessageToLogin', buf, player.login)
                    except Exception:
                        pass
            else:
                # Append line to this player's chat buffer (for /refresh)
                if len(player.mutebuf) >= CHAT_WINDOW_LEN:
                    player.mutebuf.pop(0)
                player.mutebuf.append(f'$z$s[{chatter_nick}$z$s] {text}')
    else:
        # Server message — buffer for all players if it looks like a global
        if _globalpat and _globalpat.match(text):
            for player in aseco.server.players.all():
                if len(player.mutebuf) >= CHAT_WINDOW_LEN:
                    player.mutebuf.pop(0)
                player.mutebuf.append(text)


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

def _get_player_nick(aseco: 'Aseco', login: str) -> str:
    pl = aseco.server.players.get_player(login)
    return pl.nickname if pl else login


def _get_player_param(aseco: 'Aseco', requester, param: str, offline: bool = False):
    if not param or not param.strip():
        return None
    param = param.strip()
    if param.isdigit():
        pid = int(param) - 1
        pl_list = getattr(requester, 'playerlist', [])
        if 0 <= pid < len(pl_list):
            entry = pl_list[pid]
            param = entry.get('login', '') if isinstance(entry, dict) else str(entry)
    player = aseco.server.players.get_player(param)
    if player:
        return player
    if offline:
        from pyxaseco.models import Player as _P
        stub = _P()
        stub.login    = param
        stub.nickname = param
        return stub
    return None


async def _reply(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)


async def chat_mute(aseco: 'Aseco', command: dict):
    player = command['author']
    target = _get_player_param(aseco, player, command.get('params', ''))
    if not target:
        return

    # Cannot mute admins
    if aseco.is_any_admin(target):
        await _reply(aseco, player.login,
                     f'{{#server}}> {{#error}}Cannot mute admin '
                     f'{{#highlite}}$i {strip_colors(target.nickname)}$z$s{{#error}} !')
        return

    if target.login not in player.mutelist:
        player.mutelist.append(target.login)
        msg = format_text(aseco.get_chat_message('MUTE'), target.nickname)
    else:
        msg = (f'{{#server}}> {{#error}}Player {{#highlite}}$i '
               f'{strip_colors(target.nickname)}$z$s{{#error}} is already in your mute list!')
    await _reply(aseco, player.login, msg)


async def chat_unmute(aseco: 'Aseco', command: dict):
    player = command['author']
    target = _get_player_param(aseco, player, command.get('params', ''), offline=True)
    if not target:
        return

    if target.login in player.mutelist:
        player.mutelist.remove(target.login)
        msg = format_text(aseco.get_chat_message('UNMUTE'), target.nickname)
    else:
        msg = (f'{{#server}}> {{#error}}Player {{#highlite}}$i '
               f'{strip_colors(target.nickname)}$z$s{{#error}} is not in your mute list!')
    await _reply(aseco, player.login, msg)


async def chat_mutelist(aseco: 'Aseco', command: dict):
    player = command['author']
    login  = player.login
    muted  = [l for l in player.mutelist if l]

    if not muted:
        await _reply(aseco, login, '{#server}> {#error}No muted players found!')
        return

    header = 'Currently Muted Players:'
    rows   = [['Id', '{#nick}Nick / {#login}Login']]
    player.playerlist = []
    for i, ml in enumerate(muted, 1):
        nick = strip_colors(_get_player_nick(aseco, ml))
        rows.append([f'{i:02d}.', f'{{#black}}{nick}$z / {{#login}}{ml}'])
        player.playerlist.append({'login': ml})

    pages = [rows[j:j+14] for j in range(0, max(len(rows), 1), 14)]
    player.msgs = [[1, header, [0.9, 0.1, 0.8], ['Icons128x128_1', 'Padlock', 0.01]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def chat_refresh(aseco: 'Aseco', command: dict):
    player = command['author']
    if player.mutebuf:
        buf = '\n'.join('$z$z$s' + line for line in player.mutebuf)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', buf, player.login)
