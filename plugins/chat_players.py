"""
chat_players.py — Port of plugins/chat.players.php

/players [filter] — Displays current list of nicks/logins with clickable /stats.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import ML_ID_MAIN, strip_colors, display_manialink_multi
from pyxaseco.plugins.plugin_localdatabase import map_country, get_pool

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def _display_country(pl) -> str:
    nation = (getattr(pl, 'nation', '') or '').strip()
    zone = (getattr(pl, 'zone', '') or '').strip()

    while zone.startswith('World|'):
        zone = zone[6:]

    zone_country = zone.split('|', 1)[0].strip() if zone else ''

    country = nation
    if zone_country and len(nation) <= 3:
        country = zone_country

    if len(country) > 14:
        mapped = map_country(country)
        return mapped

    return country


def _is_admin_login(aseco: 'Aseco', login: str) -> bool:
    return (
        aseco.is_master_admin_login(login)
        or aseco.is_admin_login(login)
        or aseco.is_operator_login(login)
    )


def register(aseco: 'Aseco'):
    aseco.add_chat_command('players', 'Displays current list of nicks/logins')
    aseco.register_event('onChat_players',              chat_players)
    aseco.register_event('onPlayerManialinkPageAnswer', event_players)


async def chat_players(aseco: 'Aseco', command: dict):
    player = command['author']
    params = command['params'].split(None, 1)
    search = params[0].lower() if params else ''

    head   = 'Players Known To This Server:'
    HEADER = ['Id', '{#nick}Nick $g/{#login} Login', '{#black}Nation']

    online_players = {pl.login: pl for pl in aseco.server.players.all()}
    db_rows = []
    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'SELECT Login, NickName, Nation, UpdatedAt '
                        'FROM players ORDER BY UpdatedAt DESC, Login ASC'
                    )
                    db_rows = await cur.fetchall()
    except Exception:
        db_rows = []

    pid = 1
    player.playerlist = []
    entries = []   # list of data rows (no header rows here)

    if db_rows:
        for row in db_rows:
            login = str((row[0] if row and len(row) > 0 else '') or '').strip()
            nickname_db = str((row[1] if row and len(row) > 1 else '') or '').strip()
            nation_db = str((row[2] if row and len(row) > 2 else '') or '').strip()
            if not login:
                continue

            online = online_players.get(login)
            nickname = getattr(online, 'nickname', '') or nickname_db or login
            nick_plain = strip_colors(nickname)
            if search and search not in nick_plain.lower() and search not in login.lower():
                continue

            player.playerlist.append({'login': login})

            nick_display = '{#black}' + nickname + '$z / ' + \
                           ('{#logina}' if _is_admin_login(aseco, login) else '{#login}') + login
            if aseco.settings.clickable_lists and pid <= 200:
                nick_display = [nick_display, pid + 2000]

            nat = _display_country(online) if online else nation_db
            if nat and len(nat) > 14:
                nat = map_country(nat)

            entries.append([f'{pid:02d}.', nick_display, '{#black}' + nat])
            pid += 1
    else:
        for pl in aseco.server.players.all():
            nick_plain = strip_colors(pl.nickname)
            if search and search not in nick_plain.lower() and search not in pl.login.lower():
                continue

            player.playerlist.append({'login': pl.login})

            nick_display = '{#black}' + pl.nickname + '$z / ' + \
                           ('{#logina}' if aseco.is_any_admin(pl) else '{#login}') + pl.login
            if aseco.settings.clickable_lists and pid <= 200:
                nick_display = [nick_display, pid + 2000]

            nat = _display_country(pl)

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
