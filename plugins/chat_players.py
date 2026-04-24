"""
chat_players.py — Port of plugins/chat.players.php

/players [filter] — Displays current list of nicks/logins with clickable /stats.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import ML_ID_MAIN, strip_colors, display_manialink_multi
from pyxaseco.plugins.plugin_localdatabase import map_country

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('players', 'Displays current list of nicks/logins')
    aseco.register_event('onChat_players',              chat_players)
    aseco.register_event('onPlayerManialinkPageAnswer', event_players)


async def chat_players(aseco: 'Aseco', command: dict):
    player = command['author']
    params = command['params'].split(None, 1)
    search = params[0].lower() if params else ''

    head   = 'Players On This Server:'
    HEADER = ['Id', '{#nick}Nick $g/{#login} Login', '{#black}Nation']

    pid = 1
    player.playerlist = []
    entries = []   # list of data rows (no header rows here)

    for pl in aseco.server.players.all():
        nick_plain = strip_colors(pl.nickname)
        if search and search not in nick_plain.lower() and search not in pl.login.lower():
            continue

        player.playerlist.append({'login': pl.login})

        nick_display = '{#black}' + pl.nickname + '$z / ' + \
                       ('{#logina}' if aseco.is_any_admin(pl) else '{#login}') + pl.login
        if aseco.settings.clickable_lists and pid <= 200:
            nick_display = [nick_display, pid + 2000]

        nat = pl.nation
        if len(nat) > 14:
            nat = map_country(nat)

        entries.append([f'{pid:02d}.', nick_display, '{#black}' + nat])
        pid += 1

    if not entries:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No player(s) found!'), player.login)
        return

    player.msgs = [[1, head, [1.3, 0.1, 0.9, 0.3], ['Icons128x128_1', 'Buddies']]]

    page   = [HEADER]
    lines  = 0
    for row in entries:
        page.append(row)
        lines += 1
        if lines > 14:
            player.msgs.append(page)
            lines = 0
            page  = [HEADER]
    if len(page) > 1:   # more than just the header
        player.msgs.append(page)

    display_manialink_multi(aseco, player)


async def event_players(aseco: 'Aseco', answer: list):
    """Handle ManiaLink player list clicks (action 2001-2200) → open /stats."""
    if len(answer) < 3:
        return
    action = int(answer[2])
    if 2001 <= action <= 2200:
        login  = answer[1]
        player = aseco.server.players.get_player(login)
        if not player:
            return
        idx = action - 2001
        if idx < len(player.playerlist):
            target_login = player.playerlist[idx]['login']
            aseco.console('player {1} clicked command "/stats {2}"', login, target_login)
            xml = f'<manialink id="{ML_ID_MAIN}"></manialink>'
            await aseco.client.query_ignore_result(
                'SendDisplayManialinkPageToLogin', login, xml, 0, False)
            from pyxaseco.plugins.chat_stats import chat_stats
            await chat_stats(aseco, {'author': player, 'params': target_login})
