"""
help_chat.py — Port of plugins/chat.help.php

/help    → compact list of command names in chat
/helpall → ManiaLink window with full descriptions
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import show_help

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.register_command(
        'help',
        'Shows all available commands',
        owner='chat/help',
        app='help',
        category='chat-help',
        usage='/help',
        display_name='help',
        order=10,
    )
    aseco.register_command(
        'helpall',
        'Displays help for available commands',
        owner='chat/help',
        app='help',
        category='chat-help',
        usage='/helpall',
        display_name='helpall',
        order=11,
    )
    aseco.register_event('onChat_help', chat_help)
    aseco.register_event('onChat_helpall', chat_helpall)


async def chat_help(aseco: 'Aseco', command: dict):
    """Handle /help — compact command list in chat."""
    player = command['author']
    show_help(aseco, player, show_admin=False, disp_all=False)

    if aseco.settings.help_explanation:
        msg = aseco.format_colors(aseco.get_chat_message('HELP_EXPLANATION'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', msg, player.login)


async def chat_helpall(aseco: 'Aseco', command: dict):
    """Handle /helpall — full help in a ManiaLink window."""
    player = command['author']
    show_help(aseco, player, show_admin=False, disp_all=True, width=0.3)
