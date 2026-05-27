from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, as_float, as_int, bind_app_settings
from pyxaseco.helpers import (configure_window_message_history, display_manialink,
                              get_window_message_buffer)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


MSGLOG_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='social_chat',
    section_name='social_chat',
    description='Optional message-log feature settings',
    settings=(
        AppSetting('msglog/enabled', False, as_bool, 'Enable the optional message log command and button.', 'msglog'),
        AppSetting('msglog/buffer_length', 21, as_int, 'Number of recent messages to retain.', 'msglog'),
        AppSetting('msglog/line_length', 800, as_int, 'Approximate wrap width for stored messages.', 'msglog'),
        AppSetting('msglog/window_lines', 5, as_int, 'Number of recent lines shown in the popup window.', 'msglog'),
        AppSetting('msglog/button_pos_x', -63.9, as_float, 'Message-log button X position.', 'msglog'),
        AppSetting('msglog/button_pos_y', -33.5, as_float, 'Message-log button Y position.', 'msglog'),
    ),
)

feature_msglog = False
_button_pos_x = -63.9
_button_pos_y = -33.5
ML_WINDOW_ID = 7
ML_BUTTON_ID = 8
ML_ACTION_ID = 7223


def _apply_app_defaults(aseco: 'Aseco') -> None:
    global feature_msglog, _button_pos_x, _button_pos_y

    bound = bind_app_settings(MSGLOG_SETTINGS_SCHEMA, getattr(aseco, '_base_dir', None))
    feature_msglog = bool(bound.values['msglog/enabled'])
    _button_pos_x = float(bound.values['msglog/button_pos_x'])
    _button_pos_y = float(bound.values['msglog/button_pos_y'])
    configure_window_message_history(
        buffer_len=int(bound.values['msglog/buffer_length']),
        line_len=int(bound.values['msglog/line_length']),
        window_len=int(bound.values['msglog/window_lines']),
    )
    setattr(aseco, 'feature_msglog', feature_msglog)
    setattr(aseco.server, 'feature_msglog', feature_msglog)


def register(aseco: 'Aseco'):
    _apply_app_defaults(aseco)
    if not feature_msglog:
        return
    aseco.add_chat_command('msglog', 'Displays log of recent system messages', app='social_chat', category='chat-server')
    aseco.register_event('onPlayerManialinkPageAnswer', _event_msglog)
    aseco.register_event('onPlayerConnect', _msglog_button)
    aseco.register_event('onChat_msglog', chat_msglog)


def _server_is_tmf(aseco: 'Aseco') -> bool:
    return getattr(aseco.server, 'get_game', lambda: '')() == 'TMF'


async def _msglog_button(aseco: 'Aseco', player):
    xml = (
        f'<manialink id="{ML_BUTTON_ID}"><frame posn="{_button_pos_x} {_button_pos_y} 0">'
        f'<quad sizen="1.65 1.65" style="Icons64x64_1" substyle="ArrowUp" action="{ML_ACTION_ID}"/>'
        '</frame></manialink>'
    )
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin',
        player.login,
        xml,
        0,
        False,
    )


async def _event_msglog(aseco: 'Aseco', answer: list):
    if len(answer) < 3:
        return

    try:
        action = int(answer[2])
    except Exception:
        return

    if action != ML_ACTION_ID:
        return

    player = aseco.server.players.get_player(answer[1])
    if not player:
        return

    aseco.console('player {1} clicked command "/msglog "', player.login)
    await chat_msglog(aseco, {'author': player, 'params': ''})


async def chat_msglog(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    if not _server_is_tmf(aseco):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(aseco.get_chat_message('FOREVER_ONLY')),
            login,
        )
        return

    msgbuf = get_window_message_buffer()
    if msgbuf:
        header = 'Recent system message history:'
        msgs = [[line] for line in msgbuf]
        display_manialink(
            aseco,
            login,
            header,
            ['Icons64x64_1', 'NewMessage'],
            msgs,
            [1.53],
            'OK',
        )
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No system message history found!'),
            login,
        )
