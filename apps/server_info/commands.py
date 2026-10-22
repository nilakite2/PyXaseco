"""
Server information and runtime introspection command surface.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pyxaseco.helpers import (display_manialink, display_manialink_multi,
                              format_text, format_time, format_time_h, strip_colors)
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.aseco import PYXASECO_VERSION
from . import overview

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command(
        'server',
        'Displays detailed server information',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/server',
        display_name='server',
        order=110,
    )
    aseco.add_chat_command(
        'xaseco',
        'Displays PyXaseco runtime information',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/xaseco',
        display_name='xaseco',
        order=111,
    )
    aseco.add_chat_command(
        'pyxaseco',
        'Alias for /xaseco',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/pyxaseco',
        display_name='pyxaseco',
        order=112,
    )
    aseco.add_chat_command(
        'plugins',
        'Displays active app runtime entries and capabilities',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/plugins',
        display_name='plugins',
        order=113,
    )
    aseco.add_chat_command(
        'apps',
        'Alias for /plugins',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/apps',
        display_name='apps',
        order=114,
    )
    aseco.add_chat_command(
        'nations',
        'Displays the top nations by player count',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/nations',
        display_name='nations',
        order=115,
    )
    aseco.register_event('onChat_server', chat_server)
    aseco.register_event('onPlayerManialinkPageAnswer', overview.on_answer)
    aseco.register_event('onChat_xaseco', chat_xaseco)
    aseco.register_event('onChat_pyxaseco', chat_pyxaseco)
    aseco.register_event('onChat_plugins', chat_plugins)
    aseco.register_event('onChat_apps', chat_apps)
    aseco.register_event('onChat_nations', chat_nations)


async def chat_server(aseco: 'Aseco', command: dict):
    await overview.show(aseco, command['author'])


async def chat_xaseco(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    uptime_s = int(time.time()) - aseco.uptime
    updays = uptime_s // (24 * 3600)
    uptime_rem = uptime_s % (24 * 3600)

    admin_contact = ''
    try:
        from apps.players.rankings import admin_contact as _ac
        admin_contact = _ac or ''
    except Exception:
        pass

    display_name = strip_colors(getattr(player, 'nickname', '') or '').strip()
    if not display_name:
        try:
            pool = await localdb_get_pool(aseco)
            if pool:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute('SELECT NickName FROM players WHERE Login=%s LIMIT 1', (login,))
                        row = await cur.fetchone()
                if isinstance(row, dict):
                    display_name = strip_colors(str(row.get('NickName') or '')).strip()
                elif row:
                    display_name = strip_colors(str(row[0] or '')).strip()
        except Exception:
            display_name = ''
    if not display_name:
        display_name = login

    welcome_raw = str(aseco.settings.chat_messages.get('WELCOME', [''])[0] or '')
    welcome_text = format_text(
        welcome_raw,
        display_name,
        aseco.server.name,
        PYXASECO_VERSION,
    )
    welcome_lines = str(aseco.format_colors(welcome_text) or '').split('{br}')

    header = f'PyXaseco info: {aseco.server.name}'
    info = [['Version', '{#black}' + PYXASECO_VERSION]]

    for i, line in enumerate(welcome_lines):
        info.append(['Welcome' if i == 0 else '', '{#black}' + aseco.format_colors(line)])

    info += [
        ['Uptime', '{#black}' + f'{updays} day{"s" if updays != 1 else " "} ' +
         format_time_h(uptime_rem * 1000, False)],
        ['Website', '{#black}$l[http://github.com/nilakite2/PyXaseco]http://github.com/nilakite2/PyXaseco$l'],
        ['Credits', '{#black}Python port: Nila'],
        ['', '{#black}Original authors: Xymph, Flo, Assembler Maniac, Jfreu & others'],
    ]

    mas_logins = [lgn for lgn in aseco.settings.masteradmin_list.get('TMLOGIN', [])
                  if lgn and not lgn.startswith('LAN_')]
    if mas_logins:
        label = 'Masteradmin' + ('s' if len(mas_logins) > 1 else '')
        for i, lgn in enumerate(mas_logins):
            pl = aseco.server.players.get_player(lgn)
            nick = (pl.nickname + '$z') if pl else lgn
            info.append([label if i == 0 else '', '{#black}' + nick])

    if admin_contact:
        info.append(['Admin Contact', '{#black}' + admin_contact])

    display_manialink(aseco, login, header,
                      ['BgRaceScore2', 'Warmup'],
                      info, [1.0, 0.3, 0.7], 'OK')


async def chat_pyxaseco(aseco: 'Aseco', command: dict):
    await chat_xaseco(aseco, command)


async def chat_plugins(aseco: 'Aseco', command: dict):
    player = command['author']
    active_apps = list(getattr(aseco, 'active_apps', []) or [])
    loadout_entries = list(getattr(aseco, 'loadout_entries', []) or [])
    fulfilled_entries = list(getattr(aseco, 'fulfilled_entries', []) or [])

    rows: list[list[str]] = []
    if active_apps:
        rows.append(['{#black}$oActive Apps'])
        rows.extend([['{#black}' + str(app_id)] for app_id in active_apps])
        rows.append([''])

    if loadout_entries:
        rows.append(['{#black}$oActive Loadout Entries'])
        rows.extend([['{#black}' + str(entry)] for entry in loadout_entries])
        rows.append([''])

    if fulfilled_entries:
        rows.append(['{#black}$oFulfilled Runtime Capabilities'])
        rows.extend([['{#black}' + str(entry)] for entry in fulfilled_entries])

    if not rows:
        rows = [['{#black}(none)']]

    head = 'Current App Runtime'
    pages = [rows[i:i+15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, head, [0.7], ['Icons128x128_1', 'Browse', 0.02]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def chat_apps(aseco: 'Aseco', command: dict):
    await chat_plugins(aseco, command)


async def chat_nations(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    try:
        pool = await localdb_get_pool(aseco)
        if not pool:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                aseco.format_colors('{#server}> {#error}Database not available.'), login)
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT Nation, COUNT(Nation) AS cnt FROM players '
                    'GROUP BY Nation ORDER BY cnt DESC LIMIT 10')
                rows = await cur.fetchall()

        if not rows:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                aseco.format_colors('{#server}> {#error}No players/nations found!'), login)
            return

        header = 'TOP 10 Most Visiting Nations:'
        nats = []
        for i, (nat, cnt) in enumerate(rows, 1):
            nats.append([f'{i}.', '{#black}' + (nat or '?'), str(cnt)])

        display_manialink(aseco, login, header,
                          ['Icons128x128_1', 'Credits'],
                          nats, [0.8, 0.1, 0.4, 0.3], 'OK')

    except Exception:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}Could not load nations data.'), login)
