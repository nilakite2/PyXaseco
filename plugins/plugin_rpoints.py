"""
plugin_rpoints.py — Port of plugins/plugin.rpoints.php

Initialises custom rounds points system and provides /rpoints command.
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING
from pyxaseco.helpers import display_manialink_multi

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


async def chat_rpoints(aseco: 'Aseco', command: dict):
    player = command['author']

    head = 'Available Rounds Points Systems:'
    rows = []
    for key, (name, points) in ROUNDS_POINTS.items():
        pts_str = ','.join(str(p) for p in points[:8])
        if len(points) > 8:
            pts_str += ',...'
        rows.append(['{#black}' + key, name, pts_str])

    # Check current custom system
    try:
        result = await aseco.client.query('GetRoundCustomPoints')
        if result:
            rows.append([])
            rows.append([f'Current: ' + ','.join(str(p) for p in result)])
    except Exception:
        pass

    pages = [rows[i:i+15] for i in range(0, max(len(rows),1), 15)]
    player.msgs = [[1, head, [0.9, 0.25, 0.4, 0.25],
                    ['Icons64x64_1', 'FinishRace', 0.01]]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)
