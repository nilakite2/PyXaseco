"""
plugin_rasp_karma.py — Port of plugins/plugin.rasp_karma.php

Simple RASP karma plugin:
  - /karma [Track_ID]
  - /++ and /--
  - optional public ++ / -- chat votes
  - per-track reminders on finish or end race

Dependencies:
  - plugin_rasp.py (for messages / shared RASP state)
  - plugin_localdatabase.py (for DB access)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

# Mirrors includes/rasp.settings.php defaults.
feature_karma = False
allow_public_karma = False
karma_show_start = False
karma_show_details = False
karma_show_votes = False
karma_require_finish = 0
remind_karma = 0  # 2 = every finish; 1 = at end of race; 0 = none
_active_aseco = None


def register(aseco: 'Aseco'):
    global _active_aseco
    _active_aseco = aseco
    aseco.register_event('onChat', check4karma)
    aseco.register_event('onPlayerFinish', remind_onfinish)
    aseco.register_event('onEndRace', remind_onendrace)

    aseco.add_chat_command('karma', 'Shows karma for the current track {Track_ID}')
    aseco.add_chat_command('++', 'Increases karma for the current track')
    aseco.add_chat_command('--', 'Decreases karma for the current track')

    aseco.register_event('onChat_karma', chat_karma)
    aseco.register_event('onChat_++', chat_plusplus)
    aseco.register_event('onChat_--', chat_dashdash)


def _rasp_messages() -> dict:
    try:
        from pyxaseco.plugins import plugin_rasp
        return getattr(plugin_rasp, '_rasp_messages', {}) or {}
    except Exception:
        return {}


def _msg(key: str, *args) -> str:
    raw = (_rasp_messages().get(key.upper(), ['']) or [''])[0]
    return format_text(raw, *args)


async def _send_player_msg(aseco: 'Aseco', login: str, message: str):
    message = message.replace('{#server}>> ', '{#server}> ')
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login
    )


async def _send_global_msg(aseco: 'Aseco', message: str):
    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))


async def _get_pool():
    from pyxaseco.plugins.plugin_localdatabase import get_pool
    return await get_pool()


async def _get_player_id(login: str) -> int:
    from pyxaseco.plugins.plugin_localdatabase import get_player_id
    return await get_player_id(login)


async def _get_finish_count(pid: int, cid: int) -> int:
    pool = await _get_pool()
    if pool is None or pid <= 0 or cid <= 0:
        return 0
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT COUNT(*) FROM rs_times WHERE playerID=%s AND challengeID=%s',
                (pid, cid),
            )
            row = await cur.fetchone()
            return int(row[0] or 0) if row else 0


async def _get_vote_row(pid: int, cid: int):
    pool = await _get_pool()
    if pool is None or pid <= 0 or cid <= 0:
        return None
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT Id, Score FROM rs_karma WHERE PlayerId=%s AND ChallengeId=%s',
                (pid, cid),
            )
            return await cur.fetchone()


async def _player_has_voted(pid: int, cid: int) -> bool:
    return (await _get_vote_row(pid, cid)) is not None


async def check4karma(aseco: 'Aseco', chat: list):
    if len(chat) < 3 or chat[0] == aseco.server.id:
        return

    text = str(chat[2]).strip()
    if text not in ('++', '--'):
        return

    if allow_public_karma:
        player = aseco.server.players.get_player(chat[1])
        if player is not None:
            await karma_vote(aseco, {'author': player, 'params': ''}, 1 if text == '++' else -1)
    else:
        await _send_global_msg(aseco, _msg('KARMA_NOPUBLIC'))


async def chat_plusplus(aseco: 'Aseco', command: dict):
    await karma_vote(aseco, command, 1)


async def chat_dashdash(aseco: 'Aseco', command: dict):
    await karma_vote(aseco, command, -1)


async def karma_vote(aseco: 'Aseco', command: dict, vote: int):
    if not feature_karma:
        return

    author = command.get('author')
    if author is None:
        return

    login = author.login
    pid = int(getattr(author, 'id', 0) or 0)
    cid = int(getattr(aseco.server.challenge, 'id', 0) or 0)

    if aseco.server.isrelay:
        not_on_relay = '{#server}> {#error}This command is not available on relay servers.'
        await _send_player_msg(aseco, login, not_on_relay)
        return

    if pid <= 0 or cid <= 0:
        return

    if karma_require_finish > 0:
        finishes = await _get_finish_count(pid, cid)
        if finishes < karma_require_finish:
            await _send_player_msg(
                aseco,
                login,
                _msg('KARMA_REQUIRE', karma_require_finish, '' if karma_require_finish == 1 else 's'),
            )
            return

    row = await _get_vote_row(pid, cid)
    pool = await _get_pool()
    if pool is None:
        await _send_player_msg(aseco, login, _msg('KARMA_FAIL'))
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if row is not None:
                vote_id, old_vote = int(row[0]), int(row[1])
                if old_vote == vote:
                    await _send_player_msg(aseco, login, _msg('KARMA_VOTED'))
                    return

                await cur.execute('UPDATE rs_karma SET Score=%s WHERE Id=%s', (vote, vote_id))
                if cur.rowcount < 1:
                    await _send_player_msg(aseco, login, _msg('KARMA_FAIL'))
                    return

                await _send_player_msg(aseco, login, _msg('KARMA_CHANGE'))
            else:
                await cur.execute(
                    'INSERT INTO rs_karma (Score, PlayerId, ChallengeId) VALUES (%s, %s, %s)',
                    (vote, pid, cid),
                )
                if cur.rowcount < 1:
                    await _send_player_msg(aseco, login, _msg('KARMA_FAIL'))
                    return

                await _send_player_msg(aseco, login, _msg('KARMA_DONE'))

    clean_command = dict(command)
    clean_command['params'] = ''
    await chat_karma(aseco, clean_command)
    await aseco.release_event('onKarmaChange', await get_karma_values(cid))


async def rasp_karma(cid: int, login: str = ''):
    """Show karma for a challenge to one player or server-wide."""
    if _active_aseco is None:
        return
    karma = await get_karma(cid, login)
    message = _msg('KARMA', karma)
    if login:
        await _send_player_msg(_active_aseco, login, message)
    else:
        await _send_global_msg(_active_aseco, message)


async def chat_karma(aseco: 'Aseco', command: dict):
    if not feature_karma:
        return

    player = command.get('author')
    if player is None:
        return

    login = player.login
    param = str(command.get('params', '') or '').strip()

    if param.isdigit():
        if not getattr(player, 'tracklist', None):
            await _send_player_msg(aseco, login, _msg('LIST_HELP'))
            return

        jid = int(param.lstrip('0') or '0') - 1
        if 0 <= jid < len(player.tracklist):
            uid = player.tracklist[jid].get('uid', '')
            pool = await _get_pool()
            if pool is None:
                return
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute('SELECT Id, Name FROM challenges WHERE Uid=%s', (uid,))
                    row = await cur.fetchone()
                    if row is None:
                        await _send_player_msg(aseco, login, _msg('JUKEBOX_NOTFOUND'))
                        return
                    cid = int(row[0])
                    name = strip_colors(str(row[1] or ''))
            karma = await get_karma(cid, login)
            message = _msg('KARMA_TRACK', name, karma)
        else:
            await _send_player_msg(aseco, login, _msg('JUKEBOX_NOTFOUND'))
            return
    else:
        cid = int(getattr(aseco.server.challenge, 'id', 0) or 0)
        if cid <= 0:
            return
        karma = await get_karma(cid, login)
        message = _msg('KARMA', karma)

    await _send_player_msg(aseco, login, message)


async def get_karma_values(cid: int) -> dict:
    pool = await _get_pool()
    if pool is None or cid <= 0:
        return {
            'Karma': 0,
            'Total': 0,
            'Good': 0,
            'Bad': 0,
            'GoodPct': 0.0,
            'BadPct': 0.0,
        }

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT COALESCE(SUM(Score), 0) AS karma, COUNT(Score) AS total '
                'FROM rs_karma WHERE ChallengeId=%s',
                (cid,),
            )
            row = await cur.fetchone()
            karma = int((row[0] if row else 0) or 0)
            total = int((row[1] if row else 0) or 0)

            if total > 0:
                await cur.execute(
                    'SELECT '
                    'SUM(CASE WHEN Score > 0 THEN 1 ELSE 0 END) AS plus_votes, '
                    'SUM(CASE WHEN Score < 0 THEN 1 ELSE 0 END) AS minus_votes '
                    'FROM rs_karma WHERE ChallengeId=%s',
                    (cid,),
                )
                row2 = await cur.fetchone()
                plus = int((row2[0] if row2 else 0) or 0)
                minus = int((row2[1] if row2 else 0) or 0)
                return {
                    'Karma': karma,
                    'Total': total,
                    'Good': plus,
                    'Bad': minus,
                    'GoodPct': (plus / total * 100.0) if total else 0.0,
                    'BadPct': (minus / total * 100.0) if total else 0.0,
                }

    return {
        'Karma': 0,
        'Total': 0,
        'Good': 0,
        'Bad': 0,
        'GoodPct': 0.0,
        'BadPct': 0.0,
    }


async def get_karma(cid: int, login: str) -> str:
    values = await get_karma_values(cid)
    karma = values['Karma']
    total = values['Total']
    plus = values['Good']
    minus = values['Bad']
    pluspct = values['GoodPct']
    minuspct = values['BadPct']

    rendered = str(karma)
    if karma_show_details:
        rendered = _msg('KARMA_DETAILS', rendered, plus, round(pluspct), minus, round(minuspct))

    if karma_show_votes and login:
        pid = await _get_player_id(login)
        vote = 'none'
        if pid != 0:
            row = await _get_vote_row(pid, cid)
            if row is not None:
                score = int(row[1])
                vote = '++' if score > 0 else '--'
        rendered += _msg('KARMA_VOTE', vote)

    return rendered


async def remind_onfinish(aseco: 'Aseco', finish_item):
    if not feature_karma or remind_karma != 2:
        return

    score = getattr(finish_item, 'score', None)
    player = getattr(finish_item, 'player', None)
    if not score or player is None:
        return

    pid = int(getattr(player, 'id', 0) or 0)
    cid = int(getattr(aseco.server.challenge, 'id', 0) or 0)
    if pid <= 0 or cid <= 0:
        return

    if not await _player_has_voted(pid, cid):
        await _send_player_msg(aseco, player.login, _msg('KARMA_REMIND'))


async def remind_onendrace(aseco: 'Aseco', _data):
    if not feature_karma or remind_karma != 1:
        return

    cid = int(getattr(aseco.server.challenge, 'id', 0) or 0)
    if cid <= 0:
        return

    for player in aseco.server.players.all():
        if getattr(player, 'isspectator', False):
            continue
        pid = int(getattr(player, 'id', 0) or 0)
        if pid <= 0:
            continue
        if not await _player_has_voted(pid, cid):
            await _send_player_msg(aseco, player.login, _msg('KARMA_REMIND'))
