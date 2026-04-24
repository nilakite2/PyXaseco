"""
chat_records.py — Port of plugins/chat.records.php

/recs [help|pb|new|live|first|last|next|diff|range]
  Shows local records on the current track, with optional sub-commands.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import (format_text, format_time, strip_colors,
                               display_manialink, display_manialink_multi)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


def register(aseco: 'Aseco'):
    aseco.add_chat_command('recs', 'Displays all records on current track')
    aseco.register_event('onChat_recs', chat_recs)


async def chat_recs(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    login  = player.login
    param  = command['params'].strip().lower().split()[0] if command['params'].strip() else ''

    # Sub-command dispatch (mirrors PHP chat_recs arglist dispatch)
    if param == 'help':
        await _show_help(aseco, login)
        return
    elif param == 'pb':
        await _dispatch(aseco, command, 'pb')
        return
    elif param == 'new':
        await _dispatch(aseco, command, 'newrecs')
        return
    elif param == 'live':
        await _dispatch(aseco, command, 'liverecs')
        return
    elif param == 'first':
        from pyxaseco.plugins.chat_recrels import chat_firstrec
        await chat_firstrec(aseco, command)
        return
    elif param == 'last':
        from pyxaseco.plugins.chat_recrels import chat_lastrec
        await chat_lastrec(aseco, command)
        return
    elif param == 'next':
        from pyxaseco.plugins.chat_recrels import chat_nextrec
        await chat_nextrec(aseco, command)
        return
    elif param == 'diff':
        from pyxaseco.plugins.chat_recrels import chat_diffrec
        await chat_diffrec(aseco, command)
        return
    elif param == 'range':
        from pyxaseco.plugins.chat_recrels import chat_recrange
        await chat_recrange(aseco, command)
        return

    if aseco.server.isrelay:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(format_text(aseco.get_chat_message('NOTONRELAY'))),
            login)
        return

    total = aseco.server.records.count()
    if not total:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No records found!'), login)
        return

    is_stnt    = (aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)
    show_logins = aseco.settings.show_rec_logins
    extra       = 0.2 if aseco.settings.lists_colornicks else 0
    head        = f'Current TOP {aseco.server.records.max} Local Records:'

    rows = []
    for i in range(total):
        rec        = aseco.server.records.get_record(i)
        nick       = rec.player.nickname if aseco.settings.lists_colornicks \
                     else strip_colors(rec.player.nickname)
        score_str  = str(rec.score) if is_stnt else format_time(rec.score)
        color      = '{#black}' if rec.new else ''
        if show_logins:
            rows.append([f'{i+1:02d}.', '{#black}' + nick,
                         '{#login}' + rec.player.login, color + score_str])
        else:
            rows.append([f'{i+1:02d}.', '{#black}' + nick, color + score_str])

    if show_logins:
        widths = [1.2+extra, 0.1, 0.45+extra, 0.4, 0.25]
    else:
        widths = [0.8+extra, 0.1, 0.45+extra, 0.25]

    pages = [rows[i:i+15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, head, widths, ['BgRaceScore2', 'Podium']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def _show_help(aseco: 'Aseco', login: str):
    header    = '{#black}/recs <option>$g shows local records and relations:'
    help_data = [
        ['...', '{#black}help',  'Displays this help information'],
        ['...', '{#black}pb',    'Shows your personal best on current track'],
        ['...', '{#black}new',   'Shows newly driven records'],
        ['...', '{#black}live',  'Shows records of online players'],
        ['...', '{#black}first', 'Shows first ranked record on current track'],
        ['...', '{#black}last',  'Shows last ranked record on current track'],
        ['...', '{#black}next',  'Shows next better ranked record to beat'],
        ['...', '{#black}diff',  'Shows your difference to first ranked record'],
        ['...', '{#black}range', 'Shows difference first to last ranked record'],
        [],
        ['Without an option, the normal records list is displayed.'],
    ]
    display_manialink(aseco, login, header,
                      ['Icons64x64_1', 'TrackInfo', -0.01],
                      help_data, [1.1, 0.05, 0.3, 0.75], 'OK')


async def _dispatch(aseco: 'Aseco', command: dict, target: str):
    """Dispatch sub-command to the relevant handler."""
    if target == 'pb':
        try:
            from pyxaseco.plugins.plugin_rasp import chat_pb
            await chat_pb(aseco, command)
        except ImportError:
            pass
    elif target in ('newrecs', 'liverecs'):
        if aseco.server.isrelay:
            msg = format_text(aseco.get_chat_message('NOTONRELAY'))
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', aseco.format_colors(msg),
                command['author'].login)
            return
        from pyxaseco.plugins.chat_records2 import show_trackrecs
        mode = 0 if target == 'newrecs' else 2
        await show_trackrecs(aseco, command['author'].login, mode, 0)
