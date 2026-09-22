"""
players_stats.py - Player statistics and top-donators commands.

/stats [login] - Player statistics window
/statsall      - Redirects to /stats
/topdons       - Top 100 highest donators
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from pyxaseco.helpers import (display_manialink, display_manialink_multi,
                              format_text, format_time_h, strip_colors)
from pyxaseco.app_services import (
    localdb_get_donations,
    localdb_get_player_id,
    localdb_get_pool,
)
from pyxaseco.models import Player as RuntimePlayer

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


logger = logging.getLogger(__name__)


def _row_value(row, key: str, index: int, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    if row and len(row) > index:
        return row[index]
    return default


async def _lookup_player_from_db(aseco: 'Aseco', value: str):
    value = (value or '').strip()
    if not value:
        return None

    try:
        pool = await localdb_get_pool(aseco)
        if not pool:
            return None

        value_l = value.lower()
        like = f'%{value}%'

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT Id, Login, NickName, Nation, Wins, TimePlayed, TeamName, UpdatedAt '
                    'FROM players WHERE Login=%s LIMIT 1',
                    (value,),
                )
                row = await cur.fetchone()
                if row:
                    rows = [row]
                else:
                    await cur.execute(
                        'SELECT Id, Login, NickName, Nation, Wins, TimePlayed, TeamName, UpdatedAt '
                        'FROM players '
                        'WHERE Login LIKE %s OR NickName LIKE %s '
                        'ORDER BY UpdatedAt DESC, Login ASC LIMIT 50',
                        (like, like),
                    )
                    rows = await cur.fetchall()
    except Exception:
        return None

    if not rows:
        return None

    candidates = []
    for row in rows:
        login = str(_row_value(row, 'Login', 1, '') or '').strip()
        nickname = str(_row_value(row, 'NickName', 2, '') or '').strip()
        if not login:
            continue
        candidates.append({
            'id': int(_row_value(row, 'Id', 0, 0) or 0),
            'login': login,
            'nickname': nickname or login,
            'nation': str(_row_value(row, 'Nation', 3, '') or '').strip(),
            'wins': int(_row_value(row, 'Wins', 4, 0) or 0),
            'timeplayed': int(_row_value(row, 'TimePlayed', 5, 0) or 0),
            'teamname': str(_row_value(row, 'TeamName', 6, '') or '').strip(),
            'updated_at': str(_row_value(row, 'UpdatedAt', 7, '') or '').strip(),
        })

    if not candidates:
        return None

    match = None
    exact_login = [item for item in candidates if item['login'].lower() == value_l]
    if len(exact_login) == 1:
        match = exact_login[0]
    else:
        exact_nick = [
            item for item in candidates
            if strip_colors(item['nickname']).strip().lower() == value_l
        ]
        if len(exact_nick) == 1:
            match = exact_nick[0]
        else:
            partial = [
                item for item in candidates
                if value_l in item['login'].lower()
                or value_l in strip_colors(item['nickname']).lower()
            ]
            if len(partial) == 1:
                match = partial[0]

    if not match:
        return None

    player = RuntimePlayer()
    player.id = match['id']
    player.login = match['login']
    player.nickname = match['nickname']
    player.nation = match['nation']
    player.zone = match['nation']
    player.wins = match['wins']
    player.timeplayed = match['timeplayed']
    player.teamname = match['teamname']
    setattr(player, 'updated_at', match['updated_at'])
    setattr(player, 'offline_lookup', True)
    return player


def _tz_str() -> str:
    import datetime as _dt
    now = _dt.datetime.now().astimezone()
    abbr = now.strftime('%Z') or ''
    if abbr and ' ' not in abbr:
        return abbr
    offset = now.utcoffset()
    if offset is None:
        return 'UTC'
    total = int(offset.total_seconds() // 60)
    sign = '+' if total >= 0 else '-'
    total = abs(total)
    return f'UTC{sign}{total // 60:02d}:{total % 60:02d}'


def register_stats_commands(aseco: 'Aseco'):
    aseco.add_chat_command(
        'stats',
        'Displays statistics of current player',
        owner='chat/stats',
        app='players',
        category='chat-stats',
        usage='/stats [login]',
        display_name='stats',
        order=210,
    )
    aseco.add_chat_command(
        'statsall',
        'Displays world statistics of a player',
        owner='chat/stats',
        app='players',
        category='chat-stats',
        usage='/statsall [login]',
        display_name='statsall',
        order=211,
    )
    aseco.register_event('onChat_stats', chat_stats)
    aseco.register_event('onChat_statsall', chat_statsall)


def register_topdons_command(aseco: 'Aseco'):
    aseco.add_chat_command(
        'topdons',
        'Displays top 100 highest donators',
        owner='chat/topdons',
        app='players',
        category='chat-players',
        usage='/topdons',
        display_name='topdons',
        order=235,
    )
    aseco.register_event('onChat_topdons', chat_topdons)


def register(aseco: 'Aseco'):
    register_stats_commands(aseco)
    register_topdons_command(aseco)


async def chat_stats(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    target = player

    if command['params'].strip():
        param = command['params'].strip()
        t = aseco.server.players.get_player(param)
        if t:
            target = t
        else:
            target = await _lookup_player_from_db(aseco, param)
            if not target:
                await _send_login(
                    aseco,
                    player.login,
                    f'{{#server}}> {{#error}}Player not found in database: {{#highlite}}{param}',
                )
                return

    try:
        info = await aseco.client.query('GetDetailedPlayerInfo', target.login)
        rankings = info.get('LadderStats', {}).get('PlayerRankings', [{}])
        rank = rankings[0].get('Ranking', 0) if rankings else 0
        score = rankings[0].get('Score', 0.0) if rankings else 0.0
        lastm = info.get('LadderStats', {}).get('LastMatchScore', 0.0)
        wins = info.get('LadderStats', {}).get('NbrMatchWins', 0)
        draws = info.get('LadderStats', {}).get('NbrMatchDraws', 0)
        losses = info.get('LadderStats', {}).get('NbrMatchLosses', 0)
        zone = info.get('Path', 'World|?')[6:]
        inscr = info.get('LadderStats', {}).get('HoursSinceZoneInscription', 0)
        inscrdays = inscr // 24
        inscrhours = inscr % 24
    except Exception:
        rank = score = lastm = wins = draws = losses = 0
        zone = ''
        inscrdays = inscrhours = 0

    def fmt_num(n: int) -> str:
        formatted = format(n, ',').replace(',', '\u2009')
        return formatted.replace('\u2009', '$n $m')

    last_online = 'unknown'
    try:
        pool = await localdb_get_pool(aseco)
        if pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'SELECT UpdatedAt FROM players WHERE Login=%s', (target.login,))
                    row = await cur.fetchone()
                    if row:
                        last_online = re.sub(r':\d\d$', '', str(row[0]))
    except Exception:
        pass

    if last_online == 'unknown':
        updated_at = str(getattr(target, 'updated_at', '') or '').strip()
        if updated_at:
            last_online = re.sub(r':\d\d$', '', updated_at)

    records = 0
    maxrecs = 0
    rank_str = 'N/A'
    try:
        from apps.players.rankings import maxrecs as _mr
        maxrecs = _mr
    except ImportError:
        pass

    try:
        from apps.records_local.chat_records2 import get_recs
        target_id = getattr(target, 'id', 0) or await localdb_get_player_id(aseco, target.login)
        rec_list = await get_recs(aseco, target_id)
        records = sum(1 for v in rec_list.values() if v <= maxrecs)
    except Exception:
        pass

    try:
        from apps.players.rankings import getRank
        rank_str = getRank(target.login)
    except ImportError:
        try:
            pool2 = await localdb_get_pool(aseco)
            if pool2:
                pid = await localdb_get_player_id(aseco, target.login)
                async with pool2.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            'SELECT avg FROM rs_rank WHERE playerID=%s', (pid,))
                        row = await cur.fetchone()
                        if row:
                            my_avg = row[0]
                            await cur.execute(
                                'SELECT COUNT(*) FROM rs_rank WHERE avg < %s', (my_avg,))
                            better = (await cur.fetchone())[0]
                            await cur.execute('SELECT COUNT(*) FROM rs_rank')
                            total = (await cur.fetchone())[0]
                            rank_str = f'{better+1}/{total} Avg: {my_avg/10000:4.1f}'
        except Exception:
            pass

    donations = None
    if aseco.server.rights:
        try:
            donations = await localdb_get_donations(aseco, target.login)
        except Exception:
            pass

    races_won = max(target.get_wins(), target.wins)

    feature_ranks = True
    try:
        from apps.players.rankings import feature_ranks as _fr
        feature_ranks = bool(_fr)
    except ImportError:
        pass

    clickable = aseco.settings.clickable_lists
    header = f'Stats for: {target.nickname}$z / {{#login}}{target.login}'
    stats = [
        ['Server Date', '{#black}' + time.strftime('%b %d, %Y')],
        ['Server Time', '{#black}' + time.strftime('%H:%M:%S') + ' ' + _tz_str()],
    ]

    tp_val = '{#black}' + format_time_h(target.get_time_played() * 1000, False)
    if clickable:
        tp_val = [tp_val, -5]
    stats.append(['Time Played', tp_val])

    stats.append(['Last Online', '{#black}' + last_online])

    if feature_ranks:
        sr_val = '{#black}' + rank_str
        if clickable:
            sr_val = [sr_val, -6]
        stats.append(['Server Rank', sr_val])

    rec_val = '{#black}' + str(records)
    if clickable:
        rec_val = [rec_val, 5]
    stats.append(['Records', rec_val])

    rw_val = '{#black}' + str(races_won)
    if clickable:
        rw_val = [rw_val, 6]
    stats.append(['Races Won', rw_val])

    stats += [
        ['Ladder Rank', '{#black}' + fmt_num(int(rank))],
        ['Ladder Score', '{#black}' + str(round(score, 1))],
        ['Last Match', '{#black}' + str(round(lastm, 1))],
        ['Wins', '{#black}' + fmt_num(int(wins))],
        ['Draws', '{#black}' + fmt_num(int(draws)) +
         (f'   $gW/L: {{#black}}{round(wins/losses, 3)}' if losses else '')],
        ['Losses', '{#black}' + fmt_num(int(losses))],
        ['Zone', '{#black}' + zone],
        ['Inscribed', '{#black}' + f'{inscrdays} day{"s" if inscrdays != 1 else " "} ' +
         f'{inscrhours} hours'],
        ['Rights', '{#black}' + ('United' if target.rights else 'Nations')],
    ]

    if aseco.server.rights and donations is not None:
        stats.append(['Donations', '{#black}' + (str(donations) if target.rights else 'N/A')])

    stats += [
        ['Clan', '{#black}' + (target.teamname + '$z' if target.teamname else '<none>')],
        ['Client', '{#black}' + target.client],
    ]

    if aseco.allow_ability(player, 'chat_statsip'):
        stats.append(['IP', '{#black}' + target.ipport])

    display_manialink(aseco, player.login, header,
                      ['Icons128x128_1', 'Statistics', 0.03],
                      stats, [1.0, 0.3, 0.7], 'OK')


async def chat_statsall(aseco: 'Aseco', command: dict):
    msg = '{#server}> {#error}Command unavailable, use {#highlite}$i /stats {#error}instead.'
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg), command['author'].login)


def _server_is_tmf(aseco: 'Aseco') -> bool:
    try:
        return aseco.server.get_game() == 'TMF'
    except Exception:
        return getattr(aseco.server, 'game', '') == 'TMF'


async def _send_login(aseco: 'Aseco', login: str, message: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(message),
        login,
    )


async def chat_topdons(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    if not _server_is_tmf(aseco):
        await _send_login(aseco, login, aseco.get_chat_message('FOREVER_ONLY'))
        return

    if not aseco.server.rights:
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message('UNITED_ONLY'), 'server'),
        )
        return

    try:
        pool = await localdb_get_pool(aseco)
        if not pool:
            await _send_login(aseco, login, '{#server}> {#error}Local database unavailable!')
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT p.NickName, x.donations
                    FROM players p
                    LEFT JOIN players_extra x ON (p.Id = x.playerID)
                    WHERE x.donations <> 0
                    ORDER BY x.donations DESC
                    LIMIT 100
                    """
                )
                rows_db = await cur.fetchall()

        if not rows_db:
            await _send_login(aseco, login, '{#server}> {#error}No donator(s) found!')
            return

        rows = []
        for i, row in enumerate(rows_db, 1):
            nick = row[0] or ''
            if not getattr(aseco.settings, 'lists_colornicks', False):
                nick = strip_colors(nick)
            rows.append([f'{i:02d}.', '{#black}' + nick, int(row[1] or 0)])

        player.msgs = [[
            1,
            'Current TOP 100 Donators:',
            [0.9, 0.1, 0.6, 0.2],
            ['Icons128x128_1', 'Coppers', -0.01],
        ]]
        player.msgs.extend([rows[i:i + 15] for i in range(0, len(rows), 15)])
        display_manialink_multi(aseco, player)

    except Exception as e:
        logger.exception('[Players] /topdons failed: %s', e)
        await _send_login(
            aseco,
            login,
            '{#server}> {#error}Error loading donators list.',
        )
