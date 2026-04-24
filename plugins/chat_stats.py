"""
chat_stats.py — Port of plugins/chat.stats.php

/stats [login]    — Player statistics window
/statsall         — Redirects to /stats
/settings [login] — Personal settings window
"""

from __future__ import annotations
import re
import time
from typing import TYPE_CHECKING
from pyxaseco.helpers import (format_text, format_time_h, strip_colors,
                               display_manialink)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


def _tz_str() -> str:
    """Return timezone as short abbreviation (CEST/CET) or UTC+HH:MM fallback.
    Matches plugin_track._tz_abbrev() — avoids long OS names like
    'Central Europe Daylight Time' that strftime('%Z') produces on Windows."""
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


def register(aseco: 'Aseco'):
    aseco.add_chat_command('stats',    'Displays statistics of current player')
    aseco.add_chat_command('statsall', 'Displays world statistics of a player')
    aseco.add_chat_command('settings', 'Displays your personal settings')
    aseco.register_event('onChat_stats',    chat_stats)
    aseco.register_event('onChat_statsall', chat_statsall)
    aseco.register_event('onChat_settings', chat_settings)


async def chat_stats(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    target = player

    # Resolve login OR numeric player-list index
    if command['params'].strip():
        param = command['params'].strip()
        # Try online player first (supports numeric index)
        t = aseco.server.players.get_player(param)
        if t:
            target = t
        # else: leave target as player (offline lookup not available here)

    # ── Ladder stats from XMLRPC ──────────────────────────────────────────
    try:
        info     = await aseco.client.query('GetDetailedPlayerInfo', target.login)
        rankings = info.get('LadderStats', {}).get('PlayerRankings', [{}])
        rank     = rankings[0].get('Ranking', 0)   if rankings else 0
        score    = rankings[0].get('Score', 0.0)    if rankings else 0.0
        lastm    = info.get('LadderStats', {}).get('LastMatchScore', 0.0)
        wins     = info.get('LadderStats', {}).get('NbrMatchWins', 0)
        draws    = info.get('LadderStats', {}).get('NbrMatchDraws', 0)
        losses   = info.get('LadderStats', {}).get('NbrMatchLosses', 0)
        zone     = info.get('Path', 'World|?')[6:]    # strip 'World|'
        inscr    = info.get('HoursSinceZoneInscription', 0)
        inscrdays  = inscr // 24
        inscrhours = inscr % 24
    except Exception:
        rank = score = lastm = wins = draws = losses = 0
        zone = ''
        inscrdays = inscrhours = 0

    def fmt_num(n: int) -> str:
        formatted = format(n, ',').replace(',', '\u2009')  # thin space
        return formatted.replace('\u2009', '$n $m')

    # ── Last online from DB ───────────────────────────────────────────────
    last_online = 'unknown'
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
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

    # ── Ranked records count ──────────────────────────────────────────────
    records   = 0
    maxrecs   = 0
    rank_str  = 'N/A'
    try:
        from pyxaseco.plugins.plugin_rasp import maxrecs as _mr
        maxrecs = _mr
    except ImportError:
        pass

    try:
        from pyxaseco.plugins.chat_records2 import get_recs
        rec_list = await get_recs(aseco, target.id)
        records  = sum(1 for v in rec_list.values() if v <= maxrecs)
    except Exception:
        pass

    # ── Server rank ───────────────────────────────────────────────────────
    try:
        from pyxaseco.plugins.plugin_rasp import getRank
        rank_str = getRank(target.login)
    except ImportError:
        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool, get_player_id
            pool2 = await get_pool()
            if pool2:
                pid = await get_player_id(target.login)
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
                            total  = (await cur.fetchone())[0]
                            rank_str = f'{better+1}/{total} Avg: {my_avg/10000:4.1f}'
        except Exception:
            pass

    # ── Donations (TMUF servers) ──────────────────────────────────────────
    donations = None
    if aseco.server.rights:
        try:
            from pyxaseco.plugins.plugin_localdatabase import ldb_get_donations
            donations = await ldb_get_donations(aseco, target.login)
        except (ImportError, Exception):
            pass

    # ── Races won (max of session wins and DB wins) ───────────────────────
    races_won = max(target.get_wins(), target.wins)

    # ── Feature_ranks flag ────────────────────────────────────────────────
    feature_ranks = True
    try:
        from pyxaseco.plugins.plugin_rasp import feature_ranks as _fr
        feature_ranks = bool(_fr)
    except ImportError:
        pass

    # ── Build stats rows ──────────────────────────────────────────────────
    clickable = aseco.settings.clickable_lists

    header = f'Stats for: {target.nickname}$z / {{#login}}{target.login}'
    stats  = [
        ['Server Date', '{#black}' + time.strftime('%b %d, %Y')],
        ['Server Time', '{#black}' + time.strftime('%H:%M:%S') + ' ' + _tz_str()],
    ]

    # Time Played — clickable action -5 (/active)
    tp_val = '{#black}' + format_time_h(target.get_time_played() * 1000, False)
    if clickable:
        tp_val = [tp_val, -5]
    stats.append(['Time Played', tp_val])

    stats.append(['Last Online', '{#black}' + last_online])

    if feature_ranks:
        # Server Rank — clickable action -6 (/top100)
        sr_val = '{#black}' + rank_str
        if clickable:
            sr_val = [sr_val, -6]
        stats.append(['Server Rank', sr_val])

    # Records — clickable action 5 (/toprecs)
    rec_val = '{#black}' + str(records)
    if clickable:
        rec_val = [rec_val, 5]
    stats.append(['Records', rec_val])

    # Races Won — clickable action 6 (/topwins)
    rw_val = '{#black}' + str(races_won)
    if clickable:
        rw_val = [rw_val, 6]
    stats.append(['Races Won', rw_val])

    stats += [
        ['Ladder Rank',  '{#black}' + fmt_num(int(rank))],
        ['Ladder Score', '{#black}' + str(round(score, 1))],
        ['Last Match',   '{#black}' + str(round(lastm, 1))],
        ['Wins',         '{#black}' + fmt_num(int(wins))],
        ['Draws',        '{#black}' + fmt_num(int(draws)) +
                         (f'   $gW/L: {{#black}}{round(wins/losses, 3)}' if losses else '')],
        ['Losses',       '{#black}' + fmt_num(int(losses))],
        ['Zone',         '{#black}' + zone],
        ['Inscribed',    '{#black}' + f'{inscrdays} day{"s" if inscrdays != 1 else " "} '
                         + f'{inscrhours} hours'],
        ['Rights',       '{#black}' + ('United' if target.rights else 'Nations')],
    ]

    if aseco.server.rights and donations is not None:
        stats.append(['Donations', '{#black}' + (str(donations) if target.rights else 'N/A')])

    stats += [
        ['Clan',   '{#black}' + (target.teamname + '$z' if target.teamname else '<none>')],
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


async def chat_settings(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    target = player

    if command['params'].strip() and aseco.allow_ability(player, 'chat_settings'):
        t = aseco.server.players.get_player(command['params'].strip())
        if t:
            target = t

    header       = f'Settings for: {target.nickname}$z / {{#login}}{target.login}'
    settings_rows = []

    cps    = None
    style  = None
    panels = None

    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_get_cps
        cps = await ldb_get_cps(aseco, target.login)
    except (ImportError, Exception):
        pass

    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_get_style
        style = await ldb_get_style(aseco, target.login)
    except (ImportError, Exception):
        pass

    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_get_panels
        panels = await ldb_get_panels(aseco, target.login)
    except (ImportError, Exception):
        pass

    if cps:
        settings_rows.append(['Local CPS',     '{#black}' + str(cps.get('cps', -1))])
        settings_rows.append(['Dedimania CPS', '{#black}' + str(cps.get('dedicps', -1))])
        if style or panels:
            settings_rows.append([])

    if style:
        settings_rows.append(['Window Style', '{#black}' + style])
        if panels:
            settings_rows.append([])

    if panels:
        if aseco.is_any_admin(target):
            settings_rows.append(['Admin Panel',   '{#black}' + panels.get('admin', '')[5:]])
        settings_rows.append(['Donate Panel',  '{#black}' + panels.get('donate', '')[6:]])
        settings_rows.append(['Records Panel', '{#black}' + panels.get('records', '')[7:]])
        settings_rows.append(['Vote Panel',    '{#black}' + panels.get('vote', '')[4:]])

    if settings_rows:
        display_manialink(aseco, player.login, header,
                          ['Icons128x128_1', 'Inputs', 0.03],
                          settings_rows, [1.0, 0.3, 0.7], 'OK')
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No personal settings available'),
            player.login)
