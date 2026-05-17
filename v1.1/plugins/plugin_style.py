"""
plugin_style.py — Port of plugins/plugin.style.php

Loads ManiaLink window style templates from styles/*.xml files.
/style help | list | default | off | <name>
"""

from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
from pyxaseco.core.config import parse_xml_file
from pyxaseco.helpers import display_manialink, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup',                    style_default)
    aseco.register_event('onPlayerConnect',              init_player_style)
    aseco.register_event('onPlayerManialinkPageAnswer',  event_style)
    aseco.add_chat_command('style', 'Selects window style (see: /style help)')
    aseco.register_event('onChat_style', chat_style)


async def style_default(aseco: 'Aseco', _param):
    """Load the server-default style on startup."""
    style_name = aseco.settings.window_style
    if style_name:
        _load_server_style(aseco, style_name)


def _load_server_style(aseco: 'Aseco', style_name: str):
    styles_dir = aseco._base_dir / 'styles'
    style_file = styles_dir / f'{style_name}.xml'
    data = parse_xml_file(style_file)
    if data and 'STYLES' in data:
        aseco.style = data['STYLES']
        aseco.console('Load default style [{1}]', str(style_file))
    else:
        aseco.console('[PyXaseco] WARNING: Could not parse style file: {1}', str(style_file))


async def init_player_style(aseco: 'Aseco', player: 'Player'):
    """Load a player's saved personal style on connect"""
    # ldb_getStyle is provided by plugin_localdatabase — skip gracefully if absent
    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_get_style
        style_name = await ldb_get_style(aseco, player.login)
        if style_name:
            _load_player_style(aseco, player, style_name)
    except (ImportError, Exception):
        pass


def _load_player_style(aseco: 'Aseco', player: 'Player', style_name: str):
    styles_dir = aseco._base_dir / 'styles'
    style_file = styles_dir / f'{style_name}.xml'
    data = parse_xml_file(style_file)
    if data and 'STYLES' in data:
        player.style = data['STYLES']
    else:
        aseco.console('[PyXaseco] WARNING: Could not parse player style: {1}', str(style_file))


async def chat_style(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    param = command['params'].strip()

    if param == 'help':
        header = '{#black}/style$g will change the window style:'
        help_data = [
            ['...', '{#black}help',    'Displays this help information'],
            ['...', '{#black}list',    'Displays available styles'],
            ['...', '{#black}default', 'Resets style to server default'],
            ['...', '{#black}off',     'Disables TMF window style'],
            ['...', '{#black}xxx',     'Selects window style xxx'],
        ]
        display_manialink(aseco, login, header,
                          ['Icons64x64_1', 'TrackInfo', -0.01],
                          help_data, [0.8, 0.05, 0.15, 0.6], 'OK')

    elif param == 'list':
        styles_dir = aseco._base_dir / 'styles'
        files = sorted(p.stem for p in styles_dir.glob('*.xml'))[:50]
        files += ['default', 'off']

        player.tracklist = [{'style': f} for f in files]

        head = 'Currently available window styles:'
        rows = []
        for sid, f in enumerate(files, 1):
            rows.append([f'{sid:02d}.', ['{#black}' + f, sid + 48]])

        pages = [rows[i:i+15] for i in range(0, max(len(rows), 1), 15)]
        player.msgs = [[1, head, [0.8, 0.1, 0.7], ['Icons64x64_1', 'Windowed']]]
        player.msgs.extend(pages)
        display_manialink_multi(aseco, player)

    elif param:
        style = param
        # numeric selection from tracklist
        if style.isdigit():
            sid = int(style) - 1
            if 0 <= sid < len(player.tracklist):
                style = player.tracklist[sid].get('style', style)

        if style == 'off':
            player.style = {}
            msg = '{#server}> TMF window style disabled!'
            _save_style(aseco, login, '')
        elif style == 'default':
            player.style = aseco.style
            msg = ('{#server}> Style reset to server default '
                   '{#highlite}' + aseco.settings.window_style + '{#server} !')
            _save_style(aseco, login, aseco.settings.window_style)
        else:
            styles_dir = aseco._base_dir / 'styles'
            style_file = styles_dir / f'{style}.xml'
            data = parse_xml_file(style_file)
            if data and 'STYLES' in data:
                player.style = data['STYLES']
                msg = '{#server}> Style {#highlite}' + param + '{#server} selected!'
                _save_style(aseco, login, style)
            else:
                msg = '{#server}> {#error}No valid style file, use {#highlite}$i /style list {#error}!'

        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
    else:
        msg = '{#server}> {#error}No style specified, use {#highlite}$i /style help {#error}!'
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)


def _save_style(aseco: 'Aseco', login: str, style_name: str):
    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_set_style
        import asyncio
        asyncio.ensure_future(ldb_set_style(aseco, login, style_name))
    except (ImportError, Exception):
        pass


async def event_style(aseco: 'Aseco', answer: list):
    """Handle ManiaLink style selection clicks (action IDs 49-100)."""
    if len(answer) < 3:
        return
    action = int(answer[2])
    if 49 <= action <= 100:
        login = answer[1]
        player = aseco.server.players.get_player(login)
        if not player:
            return
        sid = action - 49
        if sid < len(player.tracklist):
            style = player.tracklist[sid].get('style', '')
            aseco.console('player {1} clicked command "/style {2}"', login, style)
            # Apply style
            cmd = {'author': player, 'params': style}
            await chat_style(aseco, cmd)
            # Refresh list
            cmd['params'] = 'list'
            aseco.console('player {1} clicked command "/style list"', login)
            await chat_style(aseco, cmd)
