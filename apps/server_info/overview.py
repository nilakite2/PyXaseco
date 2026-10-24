"""Read-only, explicitly refreshed TMF server/runtime/service overview."""

from __future__ import annotations

import os
import platform
import sys
import time

from pyxaseco.helpers import _send_multipage, format_time, format_time_h, strip_colors
from pyxaseco.core.service_health import health_for


ACTION_BASE = 8530000
SERVER, RUNTIME, SERVICES, REFRESH, PREVIOUS, NEXT = range(ACTION_BASE, ACTION_BASE + 6)
PAGE_ROWS = 20


def _module(name):
    # Never import an optional app just to decide whether to show it.
    return sys.modules.get(name)


def _text(value, limit=70):
    return strip_colors(str(value or '')).replace('$', '$$').replace('\n', ' ').replace('\r', ' ')[:limit]


def _formatted_text(value):
    # Keep TMF colour/link codes intact; the window renderer handles XML escaping.
    return str(value or '').replace('\n', ' ').replace('\r', ' ')


def _duration(seconds):
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    return (f'{days}d ' if days else '') + format_time_h(rest * 1000, False)


def _age(when, now):
    if when is None:
        return 'Never'
    seconds = max(0, int(now - when))
    if seconds < 60:
        return f'{seconds}s ago'
    if seconds < 3600:
        return f'{seconds // 60}m ago'
    if seconds < 86400:
        return f'{seconds // 3600}h ago'
    return f'{seconds // 86400}d ago'


def _privileged(aseco, player):
    return bool(aseco.allow_ability(player, 'server'))


def enabled_integrations(aseco):
    active = {str(name).removeprefix('app/') for name in getattr(aseco, 'active_apps', ())}
    rows = []
    if 'tmx' in active:
        rows.append(('tmx', 'TMX'))
    dedi = _module('apps.records_dedimania.service')
    config = getattr(dedi, 'dedi_db', {})
    if 'records_dedimania' in active and config.get('Login') and config.get('Password'):
        rows.append(('dedimania', 'Dedimania'))
    karma = _module('apps.ui.karma')
    if 'ui' in active and getattr(getattr(karma, '_cfg', None), 'enabled', False):
        rows.append(('karma', 'ManiaKarma'))
    for app, label in (('records_trial', 'Trial Records'), ('records_rpg', 'RPG Records'),
                       ('records_ultimania', 'Ultimania Records')):
        service = _module(f'apps.{app}.service')
        if app in active and service is not None and service.is_enabled():
            rows.append((app, label))
    discord = getattr(_module('apps.discord.service'), '_state', None)
    if 'discord' in active and discord is not None and (
            discord.enabled_for('admin') or discord.enabled_for('chat')):
        rows.append(('discord', 'Discord'))
    stats = _module('apps.pyxa_stats.service')
    if 'pyxa_stats' in active and stats is not None and stats._is_enabled():
        rows.append(('public_stats', 'PYXA Stats'))
    updates = _module('apps.server_info.uptodate')
    if 'server_info' in active and getattr(updates, 'VERSION_URL', ''):
        rows.append(('update_check', 'Version Check'))
    return rows


def server_rows(aseco, player):
    server = aseco.server
    players = list(server.players.all())
    spectators = sum(bool(getattr(p, 'isspectator', False)) for p in players)
    maxrecs = getattr(getattr(server, 'records', None), 'max', getattr(aseco.settings, 'max_records', 50))
    rows = [
        ['Server Name', _formatted_text(server.name)],
        ['Comment', _formatted_text(getattr(server, 'comment', '') or '<none>')],
        ['Server Login', _text(getattr(server, 'serverlogin', '')) or 'Unknown'],
        ['Zone', _text(getattr(server, 'zone', '')) or 'Unknown'],
        ['Current Players', str(len(players) - spectators)],
        ['Spectators', str(spectators)],
        ['Max Players', str(server.maxplay)],
        ['Max Specs', str(server.maxspec)],
        ['Leaderboard Limit', str(maxrecs)],
        ['Dedicated Version', _text(getattr(server, 'version', '')) or 'Unknown'],
        ['Dedicated Build', _text(getattr(server, 'build', '')) or 'Unknown'],
    ]
    rights = 'United' if server.rights else 'Nations'
    if server.rights and aseco.allow_ability(player, 'server_coppers'):
        rights += f" / Coppers: {int(getattr(server, 'coppers', 0) or 0)}"
    rows += [['Rights', rights], ['Ladder Limits', f'{server.laddermin} - {server.laddermax}']]
    # Retain dedicated voting settings where they were already displayed, but
    # remove the redundant "Voting info /helpvote" row.
    voting = _module('apps.voting.voting')
    if not getattr(voting, 'feature_votes', False):
        rows += [['Vote Timeout', format_time(server.votetime)], ['Vote Ratio', str(round(server.voterate, 2))]]
    rankings = _module('apps.players.rankings')
    contact = getattr(rankings, 'admin_contact', '')
    if contact:
        rows.append(['Admin Contact', _formatted_text(contact)])
    services = getattr(aseco, 'services', None)
    playlist = services.get('playlist') if services is not None else None
    cached = getattr(playlist, '_rows', None)
    if isinstance(cached, list):
        rows.append(['Map Count (cached)', str(len(cached))])
    nations = {p.nation for p in players if getattr(p, 'nation', '')}
    playtime = sum(int(getattr(p, 'timeplayed', 0) or 0) for p in players)
    rows += [['Connected Accounts / Nations', f'{len(players)} / {len(nations)}'],
             ['Combined Connected Playtime', _duration(playtime)]]
    return rows


def runtime_rows(aseco):
    from pyxaseco.core.aseco import PYXASECO_VERSION
    uptime = getattr(aseco, 'uptime', None)
    jobs = getattr(aseco, 'jobs', None)
    services = getattr(jobs, '_services', {})
    pool = getattr(_module('apps.platform_core.localdb'), '_pool', None)
    if pool is None or getattr(pool, 'closed', False):
        pool_text = 'Unavailable'
    else:
        pool_text = f"{pool.size} connections / {pool.freesize} free"
    outbox = getattr(aseco, 'record_outbox', None)
    delivery = ('Persistent' if getattr(outbox, 'path', None) is not None else 'Memory only') if outbox else 'Unavailable'
    return [
        ['Controller', 'PyXaseco ' + PYXASECO_VERSION],
        ['Controller Uptime', _duration(time.time() - uptime) if uptime is not None else 'Unknown'],
        ['Python', platform.python_version()],
        ['Operating System', _text(platform.system() + ' ' + platform.release())],
        ['Architecture', _text(platform.machine())],
        ['Logical CPUs', str(os.cpu_count()) if os.cpu_count() is not None else 'Unknown'],
        ['Loaded Apps', str(len(getattr(aseco, 'active_apps', ())))],
        ['Outstanding Background Jobs', str(sum(s.outstanding for s in services.values()))],
        ['SQL Pool', pool_text],
        ['Record Delivery', delivery],
    ]


def service_rows(aseco):
    health = health_for(aseco)
    observations = health.snapshot() if health is not None else {}
    now = health.clock() if health is not None else time.monotonic()
    rows = [['Integration', 'Last Request', 'Duration', 'Last OK']]
    for key, label in enabled_integrations(aseco):
        item = observations.get(key)
        if item is None:
            rows.append([label, 'Not contacted yet', '--', 'Never'])
        else:
            rows.append([label, item.status + ' / ' + _age(item.finished_at, now),
                         f'{item.milliseconds:.1f} ms', _age(item.last_success_at, now)])
    if len(rows) == 1:
        rows.append(['No external integrations enabled.'])
    rows += [[], ['Refresh shows observations; it sends no probes.'],
             ['HTTP response times are not confirmation of record delivery.']]
    return rows


async def show(aseco, player, view='server', page=0):
    if view not in ('server', 'runtime', 'services'):
        view = 'server'
    privileged = _privileged(aseco, player)
    if view != 'server' and not privileged:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}Server overview details require the server admin ability.'), player.login)
        return
    sections = [('server', server_rows(aseco, player))]
    if privileged:
        sections += [('runtime', runtime_rows(aseco)), ('services', service_rows(aseco))]
    pages = []
    offset = 0
    for section, rows in sections:
        if section == view:
            offset = len(pages)
        for start in range(0, len(rows), PAGE_ROWS):
            pages.append((section, start // PAGE_ROWS, rows[start:start + PAGE_ROWS]))
    index = max(0, min(offset + page, len(pages) - 1))
    player.msgs = [[index + 1, 'Server Overview', [1.25, 0.4, 0.85],
                    ['Icons64x64_1', 'DisplaySettings', 0.01], _prepare_page,
                    [(section, number) for section, number, _rows in pages], REFRESH]]
    for section, _number, rows in pages:
        if section == 'services':
            content = [['{#black}' + cell for cell in row] for row in rows]
        else:
            content = [[label, '{#black}' + value] for label, value in rows]
        player.msgs.append(content)
    await _send_multipage(aseco, player)


def _prepare_page(aseco, player):
    meta = player.msgs[0]
    if not 1 <= meta[0] < len(player.msgs):
        return False
    view, page = meta[5][meta[0] - 1]
    if view != 'server' and not _privileged(aseco, player):
        return False
    meta[1] = 'Server Overview - ' + view.title()
    meta[2] = [1.45, 0.3, 0.55, 0.25, 0.35] if view == 'services' else [1.25, 0.4, 0.85]
    player._server_overview = (view, page)
    return True


async def on_answer(aseco, answer):
    if len(answer) < 3:
        return
    try:
        action = int(answer[2])
    except (TypeError, ValueError):
        return
    if action != REFRESH:
        return
    player = aseco.server.players.get_player(answer[1])
    if player is None:
        return
    messages = getattr(player, 'msgs', None)
    if not messages or len(messages[0]) < 5 or messages[0][4] is not _prepare_page:
        return
    state = getattr(player, '_server_overview', None)
    if isinstance(state, tuple) and len(state) == 2:
        view, page = state
        await show(aseco, player, view, page)
