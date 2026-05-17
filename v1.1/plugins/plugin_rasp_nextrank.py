"""
plugin_rasp_nextrank.py — Port of plugins/plugin.rasp_nextrank.php

/nextrank — Shows the next better ranked player.
"""

from __future__ import annotations
import math
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('nextrank', 'Shows the next better ranked player')
    aseco.register_event('onChat_nextrank', chat_nextrank)


async def _send_login(aseco: 'Aseco', login: str, message: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(message),
        login,
    )


async def chat_nextrank(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await _send_login(aseco, login, msg)
        return

    try:
        from pyxaseco.plugins.plugin_rasp import (
            feature_ranks, minrank, nextrank_show_rp, _rasp_messages
        )
        from pyxaseco.plugins.plugin_localdatabase import get_pool, get_player_id
    except ImportError:
        return

    if not feature_ranks:
        return

    msgs = _rasp_messages
    pool = await get_pool()
    if not pool:
        return

    player_id = getattr(player, 'id', 0) or await get_player_id(login)
    if not player_id:
        msg = format_text(
            msgs.get('RANK_NONE', ['{#server}> {#record}You must have {1} Local Records on this server before recieving a rank...'])[0],
            minrank,
        )
        await _send_login(aseco, login, msg)
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Current player's average
            await cur.execute(
                'SELECT avg FROM rs_rank WHERE playerID=%s',
                (player_id,)
            )
            row = await cur.fetchone()
            if not row:
                msg = format_text(
                    msgs.get('RANK_NONE', ['{#server}> {#record}You must have {1} Local Records on this server before recieving a rank...'])[0],
                    minrank,
                )
                await _send_login(aseco, login, msg)
                return

            my_avg = float(row[0])

    # Fetch all strictly better averages and take the nearest one above the player.
            await cur.execute(
                'SELECT playerID, avg FROM rs_rank WHERE avg < %s ORDER BY avg ASC',
                (my_avg,)
            )
            better_rows = await cur.fetchall()

            if not better_rows:
                msg = msgs.get('TOPRANK', ['{#server}> {#record}No better ranked player :-)'])[0]
                await _send_login(aseco, login, msg)
                return

            next_pid = None
            next_avg = None
            next_login = None
            next_nick = None

            # Walk from the closest better player backwards and explicitly skip self
            # in case of stale/duplicate data oddities.
            for cand_pid, cand_avg in reversed(better_rows):
                await cur.execute(
                    'SELECT Login, NickName FROM players WHERE Id=%s',
                    (cand_pid,)
                )
                prow = await cur.fetchone()
                if not prow:
                    continue
                cand_login, cand_nick = prow
                if str(cand_login).lower() == str(login).lower():
                    continue
                next_pid = cand_pid
                next_avg = float(cand_avg)
                next_login = cand_login
                next_nick = cand_nick
                break

            if not next_pid or next_login is None:
                msg = msgs.get('TOPRANK', ['{#server}> {#record}No better ranked player :-)'])[0]
                await _send_login(aseco, login, msg)
                return

            # rank position is count(players with avg < target_avg) + 1
            await cur.execute(
                'SELECT COUNT(*) FROM rs_rank WHERE avg < %s',
                (next_avg,)
            )
            less_row = await cur.fetchone()
            rank_pos = (int(less_row[0]) if less_row else 0) + 1

            await cur.execute('SELECT COUNT(*) FROM rs_rank')
            total_row = await cur.fetchone()
            total = int(total_row[0]) if total_row else 0

            rank_str = f'{{#rank}}{rank_pos}{{#record}}/{{#highlite}}{total}'
            message = format_text(
                msgs.get('NEXTRANK', ['{#server}> {#record}The next better ranked player is {1}: {2}'])[0],
                strip_colors(next_nick),
                rank_str,
            )

            if nextrank_show_rp and getattr(aseco.server, 'gameinfo', None):
                numchall = int(getattr(aseco.server.gameinfo, 'numchall', 0) or 0)
                if numchall > 0:
                    diff = (my_avg - next_avg) / 10000 * numchall
                    message += format_text(
                        msgs.get('NEXTRANK_RP', [' $n{#record}[{#highlite}-{1}{#record} RP]'])[0],
                        math.ceil(diff),
                    )

    await _send_login(aseco, login, message)
