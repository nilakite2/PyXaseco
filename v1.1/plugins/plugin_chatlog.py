"""
plugin_chatlog.py — Port of plugins/plugin.chatlog.php

Keeps a rolling buffer of recent player chat messages and displays
them in a ManiaLink window via /chatlog.
"""

from __future__ import annotations
from collections import deque
from typing import TYPE_CHECKING
from pyxaseco.helpers import strip_colors, format_text, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

CHAT_LEN = 30   # max lines to buffer
LINE_LEN = 70   # max chars per line before wrapping

_chatbuf: deque = deque(maxlen=CHAT_LEN)


def register(aseco: 'Aseco'):
    aseco.register_event('onChat', log_chat)
    aseco.register_event('onChat_chatlog', chat_chatlog)
    aseco.add_chat_command('chatlog', 'Displays log of recent chat messages')


async def log_chat(aseco: 'Aseco', params: list):
    """Called on every chat message. params = [uid, login, text, is_cmd]"""
    if len(params) < 3:
        return
    uid, login, text = params[0], params[1], params[2]

    # Skip server messages and chat commands
    if uid == aseco.server.id or not text or text.startswith('/'):
        return

    player = aseco.server.players.get_player(login)
    if not player:
        return

    import time
    timestamp = time.strftime('%H:%M:%S')
    nick = player.nickname.replace('$w', '').replace('$W', '')
    _chatbuf.append((timestamp, nick, text))


async def chat_chatlog(aseco: 'Aseco', command: dict):
    """Handle /chatlog — show recent chat history in a ManiaLink window."""
    player: Player = command['author']
    login = player.login

    if not _chatbuf:
        msg = aseco.format_colors('{#server}> {#error}No chat history found!')
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)
        return

    head = 'Recent chat history:'
    rows = []
    show_times = aseco.settings.chatpmlog_times

    for timestamp, nick, text in _chatbuf:
        # Wrap long lines
        clean = strip_colors(text, for_tm=False)
        wrapped = _wrap(clean, LINE_LEN)
        for i, line in enumerate(wrapped):
            prefix = f'<{{#server}}{timestamp}$z> ' if show_times else ''
            nick_part = f'[{{#black}}{nick}$z] ' if i == 0 else '    ...'
            rows.append([f'$z{prefix}{nick_part}{line}'])

    # Paginate at 15 rows per page
    pages = [rows[i:i+15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, head, [1.2], ['Icons64x64_1', 'Outbox']]]
    player.msgs.extend(pages)

    display_manialink_multi(aseco, player)


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap, returns list of lines."""
    import textwrap
    lines = textwrap.wrap(text, width) or ['']
    return [lines[0]] + ['...' + l for l in lines[1:]]
