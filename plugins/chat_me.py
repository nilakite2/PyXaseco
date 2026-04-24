"""
chat_me.py — Port of plugins/chat.me.php

/me <text> — Broadcast an emote-style message starting with the player's nickname.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('me', 'Can be used to express emotions')
    aseco.register_event('onChat_me', chat_me)


async def chat_me(aseco: 'Aseco', command: dict):
    player = command['author']

    # Check global mute list
    if player.login in aseco.server.mutelist:
        msg = format_text(aseco.get_chat_message('MUTED'), '/me')
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(msg), player.login)
        return

    msg = format_text('$i{1}$z$s$i {#emotic}{2}',
                      player.nickname, command['params'])
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage', aseco.format_colors(msg))
