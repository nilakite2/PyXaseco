"""
platform_ui settings command surface.

/settings [login] - Personal settings window
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink
from pyxaseco.app_services import (
    localdb_get_cps,
    localdb_get_panels,
    localdb_get_style,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


def register(aseco: 'Aseco'):
    aseco.add_chat_command(
        'settings',
        'Displays your personal settings',
        owner='chat/settings',
        app='platform_ui',
        category='chat-ui',
        usage='/settings [login]',
        display_name='settings',
        order=212,
    )
    aseco.register_event('onChat_settings', chat_settings)


async def chat_settings(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    target = player

    if command['params'].strip() and aseco.allow_ability(player, 'chat_settings'):
        t = aseco.server.players.get_player(command['params'].strip())
        if t:
            target = t

    header = f'Settings for: {target.nickname}$z / {{#login}}{target.login}'
    settings_rows = []
    cps = None
    style = None
    panels = None

    try:
        cps = await localdb_get_cps(aseco, target.login)
    except Exception:
        pass
    try:
        style = await localdb_get_style(aseco, target.login)
    except Exception:
        pass
    try:
        panels = await localdb_get_panels(aseco, target.login)
    except Exception:
        pass

    if cps:
        settings_rows.append(['Local CPS', '{#black}' + str(cps.get('cps', -1))])
        settings_rows.append(['Dedimania CPS', '{#black}' + str(cps.get('dedicps', -1))])
        if style or panels:
            settings_rows.append([])

    if style:
        settings_rows.append(['Window Style', '{#black}' + style])
        if panels:
            settings_rows.append([])

    if panels:
        if aseco.is_any_admin(target):
            settings_rows.append(['Admin Panel', '{#black}' + panels.get('admin', '')[5:]])
        settings_rows.append(['Donate Panel', '{#black}' + panels.get('donate', '')[6:]])
        settings_rows.append(['Records Panel', '{#black}' + panels.get('records', '')[7:]])
        settings_rows.append(['Vote Panel', '{#black}' + panels.get('vote', '')[4:]])

    if settings_rows:
        display_manialink(
            aseco,
            player.login,
            header,
            ['Icons128x128_1', 'Inputs', 0.03],
            settings_rows,
            [1.0, 0.3, 0.7],
            'OK',
        )
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No personal settings available'),
            player.login,
        )
