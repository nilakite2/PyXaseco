"""
plugin_rpoints.py — Port of plugins/plugin.rpoints.php

Initialises custom rounds points system and provides /rpoints command.
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING
from pyxaseco.helpers import display_manialink, display_manialink_multi, format_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

ROUNDS_POINTS = {
    'f1old':      ('Formula 1 GP Old',          [10,8,6,5,4,3,2,1]),
    'f1new':      ('Formula 1 GP New',           [25,18,15,12,10,8,6,4,2,1]),
    'motogp':     ('MotoGP',                     [25,20,16,13,11,10,9,8,7,6,5,4,3,2,1]),
    'motogp5':    ('MotoGP + 5',                 [30,25,21,18,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1]),
    'fet1':       ('Formula ET Season 1',        [12,10,9,8,7,6,5,4,4,3,3,3,2,2,2,1]),
    'fet2':       ('Formula ET Season 2',        [15,12,11,10,9,8,7,6,6,5,5,4,4,3,3,3,2,2,2,1]),
    'fet3':       ('Formula ET Season 3',        [15,12,11,10,9,8,7,6,6,5,5,4,4,3,3,3,2,2,2,2,1]),
    'champcar':   ('Champ Car World Series',     [31,27,25,23,21,19,17,15,13,11,10,9,8,7,6,5,4,3,2,1]),
    'superstars': ('Superstars',                 [20,15,12,10,8,6,4,3,2,1]),
    'simple5':    ('Simple 5',                   [5,4,3,2,1]),
    'simple10':   ('Simple 10',                  [10,9,8,7,6,5,4,3,2,1]),
}


def register(aseco: 'Aseco'):
    aseco.register_event('onSync', init_rpoints)
    aseco.add_chat_command('rpoints', 'Shows current Rounds points system')
    aseco.register_event('onChat_rpoints', chat_rpoints)


async def init_rpoints(aseco: 'Aseco', _param):
    system = aseco.settings.default_rpoints
    if not system:
        return

    if re.match(r'^\d+,[\d,]*\d+$', system):
        points = list(map(int, system.split(',')))
        try:
            await aseco.client.query('SetRoundCustomPoints', points, False)
            aseco.console('Initialize default rounds points: {1}', system)
        except Exception as e:
            aseco.console('Invalid rounds points: {1}  Error: {2}', system, str(e))
    elif system in ROUNDS_POINTS:
        name, points = ROUNDS_POINTS[system]
        try:
            await aseco.client.query('SetRoundCustomPoints', points, False)
            aseco.console('Initialize default rounds points: {1} - {2}', system, name)
        except Exception as e:
            aseco.console('Invalid rounds points: {1}  Error: {2}', system, str(e))
    elif system == '':
        try:
            await aseco.client.query('SetRoundCustomPoints', [], False)
        except Exception:
            pass


async def _get_current_points(aseco: 'Aseco') -> list[int]:
    try:
        result = await aseco.client.query('GetRoundCustomPoints')
        return list(result or [])
    except Exception:
        return []


def _match_named_system(points: list[int]) -> str | None:
    for _key, (name, values) in ROUNDS_POINTS.items():
        if list(points) == list(values):
            return name
    return None


async def _send_login(aseco: 'Aseco', login: str, message: str) -> None:
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(message),
        login,
    )


async def admin_rpoints(aseco: 'Aseco', admin, logtitle: str, chattitle: str, command: str):
    login = admin.login
    command = re.sub(r' +', ' ', str(command or '').strip())
    parts = command.split(' ') if command else []
    sub = (parts[0].lower() if parts else 'show')

    if sub == 'help':
        header = '{#black}/admin rpoints$g sets custom Rounds points:'
        help_rows = [
            ['...', '{#black}help', 'Displays this help information'],
            ['...', '{#black}list', 'Displays available points systems'],
            ['...', '{#black}show', 'Shows current points system'],
            ['...', '{#black}xxx', 'Sets custom points system labelled xxx'],
            ['...', '{#black}X,Y,...,Z', 'Sets custom points system with specified values;'],
            ['', '', 'X,Y,...,Z must be decreasing integers and there'],
            ['', '', 'must be at least two values with no spaces'],
            ['...', '{#black}off', 'Disables custom points system'],
        ]
        display_manialink(
            aseco, login, header,
            ['Icons64x64_1', 'TrackInfo', -0.01],
            help_rows, [1.05, 0.05, 0.2, 0.8], 'OK'
        )
        return

    if sub == 'list':
        head = 'Currently available Rounds points systems:'
        rows = [['Label', '{#black}System', '{#black}Distribution']]
        pages = []
        line_count = 0
        for tag, (name, values) in ROUNDS_POINTS.items():
            rows.append(['{#black}' + tag, name, ','.join(str(v) for v in values) + ',...'])
            line_count += 1
            if line_count > 14:
                pages.append(rows)
                rows = []
                line_count = 0
        if rows:
            pages.append(rows)
        admin.msgs = [[1, head, [1.3, 0.2, 0.4, 0.7], ['Icons128x32_1', 'RT_Rounds']]]
        admin.msgs.extend(pages or [[['{#black}No points systems']]])
        display_manialink_multi(aseco, admin)
        return

    if sub == 'show':
        points = await _get_current_points(aseco)
        system = _match_named_system(points)
        if not points:
            message = format_text(aseco.get_chat_message('NO_RPOINTS'), '{#admin}')
        elif system:
            message = format_text(
                aseco.get_chat_message('RPOINTS_NAMED'),
                '{#admin}', system, '{#admin}', ','.join(str(p) for p in points)
            )
        else:
            message = format_text(
                aseco.get_chat_message('RPOINTS_NAMELESS'),
                '{#admin}', ','.join(str(p) for p in points)
            )
        await _send_login(aseco, login, message)
        return

    if sub == 'off':
        try:
            await aseco.client.query('SetRoundCustomPoints', [], False)
        except Exception as e:
            await _send_login(aseco, login, f'{{#server}}> {{#error}}Unable to disable custom points: {{#highlite}}$i {e}')
            return
        aseco.console('{1} [{2}] disabled custom points', logtitle, login)
        message = format_text(
            '{#server}>> {#admin}{1}$z$s {#highlite}{2}$z$s{#admin} disables custom rounds points',
            chattitle, admin.nickname
        )
        await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))
        return

    if re.match(r'^\d+,[\d,]*\d+$', sub):
        points = list(map(int, sub.split(',')))
        try:
            await aseco.client.query('SetRoundCustomPoints', points, False)
        except Exception as e:
            await _send_login(aseco, login, f'{{#server}}> {{#error}}Invalid point distribution!  Error: {{#highlite}}$i {e}')
            return
        aseco.console('{1} [{2}] set new custom points: {3}', logtitle, login, sub)
        message = format_text(
            '{#server}>> {#admin}{1}$z$s {#highlite}{2}$z$s{#admin} sets custom rounds points: {#highlite}{3},...',
            chattitle, admin.nickname, sub
        )
        await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))
        return

    if sub in ROUNDS_POINTS:
        name, values = ROUNDS_POINTS[sub]
        try:
            await aseco.client.query('SetRoundCustomPoints', values, False)
        except Exception as e:
            await _send_login(aseco, login, f'{{#server}}> {{#error}}Unable to set custom points: {{#highlite}}$i {e}')
            return
        aseco.console('{1} [{2}] set new custom points [{3}]', logtitle, login, sub.upper())
        message = format_text(
            '{#server}>> {#admin}{1}$z$s {#highlite}{2}$z$s{#admin} sets rounds points to {#highlite}{3}{#admin}: {#highlite}{4},...',
            chattitle, admin.nickname, name, ','.join(str(v) for v in values)
        )
        await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))
        return

    await _send_login(
        aseco, login,
        '{#server}> {#error}Unknown points system {#highlite}$i ' + str(parts[0]).upper() + '$z$s {#error}!'
    )


async def chat_rpoints(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    points = await _get_current_points(aseco)
    system = _match_named_system(points)

    if not points:
        message = format_text(aseco.get_chat_message('NO_RPOINTS'), '')
    elif system:
        message = format_text(
            aseco.get_chat_message('RPOINTS_NAMED'),
            '', system, '', ','.join(str(p) for p in points)
        )
    else:
        message = format_text(
            aseco.get_chat_message('RPOINTS_NAMELESS'),
            '', ','.join(str(p) for p in points)
        )
    await _send_login(aseco, login, message)
