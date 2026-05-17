"""
plugin_rounds.py — Port of plugins/plugin.rounds.php

Reports finishes in each individual round (Rounds/Team/Cup modes).
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, format_time, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

_rounds_count: int = 0
_round_times: dict = {}
_round_pbs: dict = {}


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',             reset_rounds)
    aseco.register_event('onNewChallenge',     reset_rounds)
    aseco.register_event('onEndRound',         report_round)
    aseco.register_event('onPlayerFinish',     store_time)
    aseco.register_event('onRestartChallenge', reset_rounds)


async def reset_rounds(aseco: 'Aseco', _param):
    global _rounds_count, _round_times, _round_pbs
    _rounds_count = 0
    _round_times  = {}
    _round_pbs    = {}


async def report_round(aseco: 'Aseco', _param):
    global _rounds_count, _round_times

    if not _round_times:
        return

    _rounds_count += 1

    # Flatten and sort all times
    all_entries = []
    for score_group in _round_times.values():
        all_entries.extend(score_group)

    all_entries.sort(key=lambda e: (
        e['score'],
        _round_pbs.get(e['login'], 0),
        e['playerid']
    ))

    pos = 1
    message = format_text(aseco.get_chat_message('ROUND'), _rounds_count)

    for tm in all_entries:
        player = aseco.server.players.get_player(tm['login'])
        nick = strip_colors(player.nickname) if player else tm['login']
        is_new = False

        for i in range(aseco.server.records.count()):
            rec = aseco.server.records.get_record(i)
            if (rec.new and rec.player.login == tm['login'] and
                    rec.score == tm['score']):
                is_new = True
                break

        if is_new:
            message += format_text(aseco.get_chat_message('RANKING_RECORD_NEW'),
                                   pos, nick, format_time(tm['score']))
        elif pos <= aseco.settings.show_min_recs:
            message += format_text(aseco.get_chat_message('RANKING_RECORD'),
                                   pos, nick, format_time(tm['score']))
        else:
            message += format_text(aseco.get_chat_message('RANKING_RECORD2'),
                                   pos, nick)
        pos += 1

    # Strip trailing ', '
    if message.endswith(', '):
        message = message[:-2]

    msg_colored = aseco.format_colors(message)
    await aseco.client.query_ignore_result('ChatSendServerMessage', msg_colored)
    _round_times.clear()


async def store_time(aseco: 'Aseco', params: list):
    global _round_times, _round_pbs

    gi = aseco.server.gameinfo
    if not gi or gi.mode not in (0, 2, 5):  # Rounds, Team, Cup
        return
    if len(params) < 3 or params[2] == 0:
        return

    _uid, login, score = params[0], params[1], params[2]
    player = aseco.server.players.get_player(login)
    if not player:
        return

    _round_times.setdefault(score, []).append({
        'playerid': player.pid,
        'login':    login,
        'score':    score,
    })

    if login not in _round_pbs or _round_pbs[login] > score:
        _round_pbs[login] = score
