"""
help_commands.py - Port of plugins/chat.help.php

/help    -> compact list of command names in chat
/helpall -> ManiaLink window with full descriptions
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.helpers import show_help
from pyxaseco.core.command_queries import command_label
from apps.platform_ui.navigation import example_for, player_command

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.register_command(
        'help',
        'Shows all available commands',
        owner='chat/help',
        app='help',
        category='chat-help',
        usage='/help [command]',
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
    player = command['author']
    words = str(command.get('params') or '').strip().split()
    if words:
        name = words[0].lstrip('/').lower()
        registration = player_command(aseco, player, name) if len(words) == 1 else None
        if registration is None:
            msg = 'That command is not listed for you. See /helpall.'
        else:
            usage = command_label(registration)
            example = example_for(registration)
            msg = f'{usage}: {registration.help_text}'
            if example and example != usage:
                msg += f' | Example: {example}'
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors(msg), player.login)
        return
    show_help(aseco, player, show_admin=False, disp_all=False)

    if aseco.settings.help_explanation:
        msg = aseco.format_colors(aseco.get_chat_message('HELP_EXPLANATION'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', msg, player.login)


async def chat_helpall(aseco: 'Aseco', command: dict):
    player = command['author']
    show_help(aseco, player, show_admin=False, disp_all=True, width=0.3)
