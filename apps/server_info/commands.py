"""
Server information and runtime introspection command surface.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pyxaseco.helpers import (display_manialink, display_manialink_multi,
                              format_time, format_time_h)
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.aseco import PYXASECO_VERSION

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
        'plugins',
        'Displays active app runtime entries and capabilities',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/plugins',
        display_name='plugins',
        order=112,
    )
    aseco.add_chat_command(
        'nations',
        'Displays the top nations by player count',
        owner='chat/server',
        app='server_info',
        category='chat-server',
        usage='/nations',
        display_name='nations',
        order=113,
    )
    aseco.register_event('onChat_server', chat_server)
    aseco.register_event('onChat_xaseco', chat_xaseco)
    aseco.register_event('onChat_plugins', chat_plugins)
    aseco.register_event('onChat_nations', chat_nations)


async def chat_server(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    players = list(aseco.server.players.all())
    active_players = [p for p in players if not getattr(p, 'isspectator', False)]
    spectators = [p for p in players if getattr(p, 'isspectator', False)]
    nations = {getattr(p, 'nation', '') for p in players if getattr(p, 'nation', '')}
    players_count = len(players)
    nations_count = len(nations)
    playtime_total = sum(int(getattr(p, 'timeplayed', 0) or 0) for p in players)
    playdays = playtime_total // (24 * 3600)
    playtime_rem = playtime_total % (24 * 3600)
    coppers = int(getattr(aseco.server, 'coppers', 0) or 0)

    admin_contact = ''
    feature_votes = False
    maxrecs = int(getattr(aseco.settings, 'max_records', 30) or 30)
    try:
        from apps.rasp.rankings import admin_contact as _ac
        admin_contact = _ac or ''
    except Exception:
        pass
    try:
        from apps.rasp.voting import feature_votes as _fv
        feature_votes = bool(_fv)
    except Exception:
        pass
    try:
        from apps.rasp.rankings import maxrecs as _mr
        maxrecs = int(_mr or maxrecs)
    except Exception:
        pass

    header = f'Server info: {aseco.server.name}'
    stats = [
        ['Server Name', '{#black}' + str(aseco.server.name)],
        ['Comment', '{#black}' + str(getattr(aseco.server, 'comment', '') or '<none>')],
        ['Current Players', '{#black}' + str(len(active_players))],
        ['Spectators', '{#black}' + str(len(spectators))],
        ['Max Players', '{#black}' + str(aseco.server.maxplay)],
        ['Max Specs', '{#black}' + str(aseco.server.maxspec)],
        ['Recs/Track', '{#black}' + str(maxrecs)],
    ]

    if feature_votes:
        stats.append(['Voting info', '{#black}/helpvote'])
    else:
        stats.append(['Vote Timeout', '{#black}' + format_time(aseco.server.votetime)])
        stats.append(['Vote Ratio', '{#black}' + str(round(aseco.server.voterate, 2))])

    if aseco.server.rights:
        rights_val = '{#black}United'
        if aseco.allow_ability(player, 'server_coppers'):
            rights_val += f'   $gCoppers: {{#black}}{coppers}'
        stats.append(['Rights', rights_val])
    else:
        stats.append(['Rights', '{#black}Nations'])

    stats.append(['Ladder Limits', '{#black}' + str(aseco.server.laddermin)
                  + '$g - {#black}' + str(aseco.server.laddermax)])

    if admin_contact:
        stats.append(['Admin Contact', '{#black}' + admin_contact])

    stats.append([])
    stats.append([f'Visited by $f80{players_count} $gPlayers from $f40{nations_count} $gNations'])
    stats.append(['who together played: {#black}' +
                  f'{playdays} day{"s" if playdays != 1 else " "} '
                  + format_time_h(playtime_rem * 1000, False) + ' $g!'])

    display_manialink(aseco, login, header,
                      ['Icons64x64_1', 'DisplaySettings', 0.01],
                      stats, [1.0, 0.3, 0.7], 'OK')


async def chat_xaseco(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    uptime_s = int(time.time()) - aseco.uptime
    updays = uptime_s // (24 * 3600)
    uptime_rem = uptime_s % (24 * 3600)

    admin_contact = ''
    try:
        from apps.rasp.rankings import admin_contact as _ac
        admin_contact = _ac or ''
    except Exception:
        pass

    welcome_raw = aseco.get_chat_message('WELCOME')
    welcome_lines = str(welcome_raw or '').split('{br}')

    header = f'PyXaseco info: {aseco.server.name}'
    info = [['Version', '{#black}' + PYXASECO_VERSION]]

    for i, line in enumerate(welcome_lines):
        info.append(['Welcome' if i == 0 else '', '{#black}' + aseco.format_colors(line)])

    info += [
        ['Uptime', '{#black}' + f'{updays} day{"s" if updays != 1 else " "} ' +
         format_time_h(uptime_rem * 1000, False)],
        ['Website', '{#black}$l[https://github.com/PyXaseco/PyXaseco]https://github.com/PyXaseco/PyXaseco$l'],
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
