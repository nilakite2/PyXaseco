"""
records_chat.py - Port of plugins/chat.records.php

/recs [help|pb|new|live|first|last|next|diff|range]
  Shows local records on the current track, with optional sub-commands.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from apps.platform_ui import record_browser
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.helpers import format_text, display_manialink

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


def register(aseco: 'Aseco'):
    aseco.add_chat_command(
        'recs',
        'Displays all records on current track',
        owner='chat/records',
        app='records_local',
        category='chat-records',
        usage='/recs [help|pb|new|live|first|last|next|diff|range]',
        display_name='recs',
        order=100,
    )
    aseco.add_chat_command(
        'pb',
        'Shows your personal best on current track',
        owner='chat/records',
        app='records_local',
        category='chat-records',
        usage='/pb',
        display_name='pb',
        order=101,
    )
    aseco.register_event('onChat_recs', chat_recs)
    aseco.register_event('onChat_pb', chat_pb)


async def chat_recs(aseco: 'Aseco', command: dict):
    player: Player = command['author']
    login  = player.login
    param  = command['params'].strip().lower().split()[0] if command['params'].strip() else ''

# Sub-command dispatch based on the argument list.
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
        from apps.records_local.chat_recrels import chat_firstrec
        await chat_firstrec(aseco, command)
        return
    elif param == 'last':
        from apps.records_local.chat_recrels import chat_lastrec
        await chat_lastrec(aseco, command)
        return
    elif param == 'next':
        from apps.records_local.chat_recrels import chat_nextrec
        await chat_nextrec(aseco, command)
        return
    elif param == 'diff':
        from apps.records_local.chat_recrels import chat_diffrec
        await chat_diffrec(aseco, command)
        return
    elif param == 'range':
        from apps.records_local.chat_recrels import chat_recrange
        await chat_recrange(aseco, command)
        return

    if aseco.server.isrelay:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(format_text(aseco.get_chat_message('NOTONRELAY'))),
            login)
        return

    records = aseco.server.records
    runs = [record_browser.Run(rec.player.login, rec.player.nickname, rec.score, i + 1,
                               record_browser.split_values(rec.checks))
            for i in range(records.count()) if (rec := records.get_record(i)) is not None]
    challenge_id = aseco.server.challenge.id
    stunts = getattr(aseco.server.gameinfo, 'mode', 0) == 4

    async def personal(login, player_id, nickname):
        if not player_id or not challenge_id:
            return None
        pool = await localdb_get_pool(aseco)
        if pool is None:
            raise RuntimeError('Local records database unavailable')
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                values = (player_id, challenge_id)
                await cur.execute('SELECT Score, Checkpoints FROM records WHERE PlayerId=%s AND ChallengeId=%s', values)
                row = await cur.fetchone()
                order = 'DESC' if stunts else 'ASC'
                await cur.execute(f'SELECT score FROM rs_times WHERE playerID=%s AND challengeID=%s '
                                  f'ORDER BY score {order} LIMIT 1', values)
                legacy = await cur.fetchone()
        if legacy and legacy[0] > 0 and (not row or (legacy[0] > row[0] if stunts else legacy[0] < row[0])):
            row = (legacy[0], '')
        if row and row[0] > 0:
            return record_browser.Run(login, nickname, row[0], splits=record_browser.split_values(row[1]))
        return None

    await record_browser.show(aseco, player, f'Current TOP {records.max} Local Records', runs,
                              pb=personal, show_logins=aseco.settings.show_rec_logins)


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
            from apps.players.rankings import chat_pb
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
        from apps.records_local.chat_records2 import show_trackrecs
        mode = 0 if target == 'newrecs' else 2
        await show_trackrecs(aseco, command['author'].login, mode, 0)


async def chat_pb(aseco: 'Aseco', command: dict):
    await _dispatch(aseco, command, 'pb')


