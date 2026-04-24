"""
chat_server.py — Port of plugins/chat.server.php

/server   — Server info window
/xaseco   — PyXaseco info window
/pyxaseco — PyXaseco info window
/plugins  — List of active plugins
/nations  — Top 10 visiting nations
"""

from __future__ import annotations
import time
from typing import TYPE_CHECKING
from pyxaseco.helpers import (format_text, format_time, format_time_h,
                               display_manialink, display_manialink_multi,
                               is_lan_login)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

PYXASECO_VERSION = 'PyXaseco 1.0-Alpha'
PYXASECO_URL     = 'github.com/nilakite2/PyXaseco'


def _wrap_comment_tm_aware(comment: str, max_visible: int = 35) -> list[str]:
    """
    Word-wrap a TM-formatted comment string for display in a ManiaLink table cell,
    measuring only *visible* characters (ignoring $l[url], $nnn colour codes, etc.)
    and never splitting inside a $l[...] or $h[...] URL construct.

    Replaces the previous textwrap.wrap() call which measured raw string length
    (counting invisible TM codes) and could split mid-way through a $l[url] token,
    causing the link to render as raw text instead of a clickable hyperlink.
    """
    import re as _re

    def _visible_len(s: str) -> int:
        s = _re.sub(r'\$[lLhH]\[[^\]]*\]', '', s)   # $l[url] atoms -> 0 chars
        s = _re.sub(r'\$[lLhH]', '', s)                # $l closers
        s = _re.sub(r'\$[0-9a-fA-F]{1,3}', '', s)      # $nnn colour codes
        s = _re.sub(r'\$[a-zA-Z]', '', s)               # $o $i $s $z etc.
        s = s.replace('$$', '$')
        return len(s)

    if not comment:
        return ['']

    # Split on explicit newlines the server admin may have put in
    segments = _re.split(r'\r?\n', comment)
    result: list[str] = []

    for raw in segments:
        raw = raw.strip()
        if not raw:
            continue
        if _visible_len(raw) <= max_visible:
            result.append(raw)
            continue

        # Need to wrap — walk character by character tracking visible width,
        # treating $l[url] as a single zero-width atom so it is never split.
        parts: list[str] = []
        current = ''
        current_vis = 0
        last_space_raw = -1    # index into current where last safe space is
        last_space_vis = -1    # visible length up to that space

        i = 0
        while i < len(raw):
            ch = raw[i]

            # $l[url], $L[url], $h[url], $H[url] — consume as one indivisible atom
            if (ch == '$' and i + 1 < len(raw) and raw[i+1].lower() in 'lh'
                    and i + 2 < len(raw) and raw[i+2] == '['):
                end = raw.find(']', i + 3)
                if end == -1:
                    end = len(raw) - 1
                atom = raw[i:end + 1]
                current += atom
                i = end + 1
                continue

            # Other $-codes — consume and add no visible length
            if ch == '$' and i + 1 < len(raw):
                nxt = raw[i + 1]
                if nxt in '0123456789abcdefABCDEF':
                    j = i + 1
                    while (j < len(raw) and raw[j] in '0123456789abcdefABCDEF'
                           and j < i + 4):
                        j += 1
                    current += raw[i:j]
                    i = j
                    continue
                elif nxt == '$':
                    current += '$'
                    current_vis += 1
                    i += 2
                    continue
                else:
                    current += raw[i:i + 2]
                    i += 2
                    continue

            # Normal visible character
            if ch == ' ':
                last_space_raw = len(current)
                last_space_vis = current_vis
            current += ch
            current_vis += 1

            # Exceeded limit - cut at last safe space
            if current_vis > max_visible and last_space_raw > 0:
                parts.append(current[:last_space_raw])
                current = '...' + current[last_space_raw + 1:]
                current_vis = 3 + (current_vis - last_space_vis - 1)
                last_space_raw = -1
                last_space_vis = -1

            i += 1

        if current.strip():
            parts.append(current)
        result.extend(parts)

    return result or ['']


def _tz_str() -> str:
    """Return timezone as short abbreviation (CEST/CET) or UTC+HH:MM fallback."""
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
    aseco.add_chat_command('server',  'Displays info about this server')
    aseco.add_chat_command('xaseco',  'Displays info about this PyXaseco')
    aseco.add_chat_command('pyxaseco',  'Displays info about this PyXaseco')
    aseco.add_chat_command('plugins', 'Displays list of active plugins')
    aseco.add_chat_command('nations', 'Displays top 10 most visiting nations')
    aseco.register_event('onChat_server',  chat_server)
    aseco.register_event('onChat_xaseco',  chat_xaseco)
    aseco.register_event('onChat_pyxaseco',  chat_xaseco)
    aseco.register_event('onChat_plugins', chat_plugins)
    aseco.register_event('onChat_nations', chat_nations)


# ---------------------------------------------------------------------------

async def chat_server(aseco: 'Aseco', command: dict):
    player = command['author']
    login  = player.login

    # ── DB stats: players, nations, total playtime ──────────────────────
    players_count = nations_count = 0
    playdays = playhours = playmins = 0
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        'SELECT COUNT(Id), COUNT(DISTINCT Nation), SUM(TimePlayed) FROM players')
                    row = await cur.fetchone()
                    if row:
                        players_count = int(row[0] or 0)
                        nations_count = int(row[1] or 0)
                        total_s       = int(row[2] or 0)
                        playdays      = total_s // (24 * 3600)
                        playtime_rem  = total_s % (24 * 3600)
    except Exception:
        playtime_rem = 0

    # ── Server uptime ─────────────────────────────────────────────────────
    try:
        network = await aseco.client.query('GetNetworkStats')
        aseco.server.uptime = network.get('Uptime', 0)
    except Exception:
        pass
    updays      = aseco.server.uptime // (24 * 3600)
    uptime_rem  = aseco.server.uptime % (24 * 3600)

    # ── Extra server settings (multicall equivalent) ──────────────────────
    comment = ''
    coppers = 0
    cuprpc  = 0
    try:
        comment = await aseco.client.query('GetServerComment') or ''
    except Exception:
        pass
    try:
        coppers = await aseco.client.query('GetServerCoppers') or 0
    except Exception:
        pass
    try:
        cup_resp = await aseco.client.query('GetCupRoundsPerChallenge')
        cuprpc   = cup_resp.get('CurrentValue', 0) if isinstance(cup_resp, dict) else 0
    except Exception:
        pass

    # ── Maxrecs ───────────────────────────────────────────────────────────
    maxrecs = 0
    try:
        from pyxaseco.plugins.plugin_rasp import maxrecs as _mr
        maxrecs = _mr
    except ImportError:
        pass

    # ── Admin contact ─────────────────────────────────────────────────────
    admin_contact = ''
    try:
        from pyxaseco.plugins.plugin_rasp import admin_contact as _ac
        admin_contact = _ac or ''
    except ImportError:
        pass

    # ── Feature votes flag ────────────────────────────────────────────────
    feature_votes = False
    try:
        from pyxaseco.plugins.plugin_rasp import feature_votes as _fv
        feature_votes = bool(_fv)
    except ImportError:
        pass

    gi     = aseco.server.gameinfo
    header = f'Welcome to: {aseco.server.name}'
    stats  = [
        ['Server Date', '{#black}' + time.strftime('%b %d, %Y')],
        ['Server Time', '{#black}' + time.strftime('%H:%M:%S') + ' ' + _tz_str()],
        ['Zone',        '{#black}' + aseco.server.zone],
    ]

    # Comment - break long lines with continuation '...'
    multicmt = _wrap_comment_tm_aware(comment, 35)
    for i, line in enumerate(multicmt):
        stats.append(['Comment' if i == 0 else '', '{#black}' + line])

    stats.append(['Uptime', '{#black}' + f'{updays} day{"s" if updays != 1 else " "} '
                  + format_time_h(uptime_rem * 1000, False)])

    if aseco.server.isrelay and aseco.server.relaymaster:
        rm = aseco.server.relaymaster
        stats.append(['Relays', '{#black}' + f'{rm.get("Login", "")} / {rm.get("NickName", "")}'])
    elif gi:
        stats.append(['Track Count', '{#black}' + str(gi.numchall)])

    if gi:
        stats.append(['Game Mode', '{#black}' + gi.get_mode()])
        mode = gi.mode
        if mode == 0:
            stats.append(['Points Limit', '{#black}' + str(gi.rndslimit)])
        elif mode == 1:
            stats.append(['Time Limit',   '{#black}' + format_time(gi.timelimit)])
        elif mode == 2:
            stats.append(['Points Limit', '{#black}' + str(gi.teamlimit)])
        elif mode == 3:
            stats.append(['Time Limit',   '{#black}' + format_time(gi.lapslimit)])
        elif mode == 4:
            # Always 5 minutes for Stunts
            stats.append(['Time Limit', '{#black}' + format_time(5 * 60 * 1000)])
        elif mode == 5:
            stats.append(['Points Limit', '{#black}' + str(gi.cuplimit)
                          + f'$g   R/C: {{#black}}{cuprpc}'])

    stats += [
        ['Max Players', '{#black}' + str(aseco.server.maxplay)],
        ['Max Specs',   '{#black}' + str(aseco.server.maxspec)],
        ['Recs/Track',  '{#black}' + str(maxrecs)],
    ]

    if feature_votes:
        stats.append(['Voting info', '{#black}/helpvote'])
    else:
        stats.append(['Vote Timeout', '{#black}' + format_time(aseco.server.votetime)])
        stats.append(['Vote Ratio',   '{#black}' + str(round(aseco.server.voterate, 2))])

    # Rights + optional coppers
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

    # Footer: visited-by rows
    stats.append([])
    stats.append([f'Visited by $f80{players_count} $gPlayers from $f40{nations_count} $gNations'])
    stats.append(['who together played: {#black}' +
                  f'{playdays} day{"s" if playdays != 1 else " "} '
                  + format_time_h(playtime_rem * 1000, False) + ' $g!'])

    display_manialink(aseco, login, header,
                      ['Icons64x64_1', 'DisplaySettings', 0.01],
                      stats, [1.0, 0.3, 0.7], 'OK')


async def chat_xaseco(aseco: 'Aseco', command: dict):
    player  = command['author']
    login   = player.login

    uptime_s   = int(time.time()) - aseco.uptime
    updays     = uptime_s // (24 * 3600)
    uptime_rem = uptime_s % (24 * 3600)

    admin_contact = ''
    try:
        from pyxaseco.plugins.plugin_rasp import admin_contact as _ac
        admin_contact = _ac or ''
    except ImportError:
        pass

    welcome_raw   = format_text(aseco.get_chat_message('WELCOME'),
                                strip_colors_fn(player.nickname),
                                aseco.server.name,
                                PYXASECO_VERSION)
    welcome_lines = welcome_raw.split('{br}')

    header = f'PyXaseco info: {aseco.server.name}'
    info   = [['Version', '{#black}' + PYXASECO_VERSION]]

    for i, line in enumerate(welcome_lines):
        info.append(['Welcome' if i == 0 else '', '{#black}' + aseco.format_colors(line)])

    info += [
        ['Uptime',   '{#black}' + f'{updays} day{"s" if updays != 1 else " "} '
                     + format_time_h(uptime_rem * 1000, False)],
        ['Website',  '{#black}$l[' + PYXASECO_URL + ']' + PYXASECO_URL + '$l'],
        ['Credits',  '{#black}Python port: Nila'],
        ['',         '{#black}Original authors: Xymph, Flo, Assembler Maniac, Jfreu & others'],
    ]

    # Masteradmins
    mas_logins = [lgn for lgn in aseco.settings.masteradmin_list.get('TMLOGIN', [])
                  if lgn and not is_lan_login(lgn)]
    if mas_logins:
        label = 'Masteradmin' + ('s' if len(mas_logins) > 1 else '')
        for i, lgn in enumerate(mas_logins):
            # Try to resolve nick from online players
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

    try:
        loaded = aseco._plugin_loader.loaded_plugins if aseco._plugin_loader else []
    except AttributeError:
        loaded = list(getattr(aseco, 'plugins', []))

    head = 'Currently active plugins:'
    rows = [['{#black}' + str(p)] for p in loaded]

    pages = [rows[i:i+15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, head, [0.7], ['Icons128x128_1', 'Browse', 0.02]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def chat_nations(aseco: 'Aseco', command: dict):
    """PHP: queries DB for top 10 nations by player count."""
    player = command['author']
    login  = player.login

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
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
        nats   = []
        for i, (nat, cnt) in enumerate(rows, 1):
            nats.append([f'{i}.', '{#black}' + (nat or '?'), str(cnt)])

        display_manialink(aseco, login, header,
                          ['Icons128x128_1', 'Credits'],
                          nats, [0.8, 0.1, 0.4, 0.3], 'OK')

    except Exception as e:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}Could not load nations data.'), login)


# ---------------------------------------------------------------------------
# Small helper — avoid circular import of strip_colors from helpers
# ---------------------------------------------------------------------------
def strip_colors_fn(text: str) -> str:
    from pyxaseco.helpers import strip_colors
    return strip_colors(text, for_tm=False)
