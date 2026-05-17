"""
chat_wins.py — Port of plugins/chat.wins.php

/wins — Shows the current player's win count.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('wins', 'Shows wins for current player')
    aseco.register_event('onChat_wins', chat_wins)


async def chat_wins(aseco: 'Aseco', command: dict):
    player = command['author']
    wins = player.get_wins()
    suffix = '.' if wins == 1 else ('s!' if wins > 1 else 's.')
    msg = format_text(aseco.get_chat_message('WINS'), wins, suffix)
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg), player.login)
