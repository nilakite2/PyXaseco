"""
chat_lastwin.py — Port of plugins/chat.lastwin.php

/lastwin — Re-opens the last closed multi-page ManiaLink window.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('lastwin', 'Re-opens the last closed multi-page window')
    aseco.register_event('onChat_lastwin', chat_lastwin)


async def chat_lastwin(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    if not player.msgs or len(player.msgs) < 2:
        msg = aseco.format_colors('{#server}> {#error}No multi-page window available!')
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', msg, login)
        return

    display_manialink_multi(aseco, player)
