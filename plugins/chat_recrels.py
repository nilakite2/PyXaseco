"""
chat_recrels.py — Port of plugins/chat.recrels.php

/firstrec /lastrec /nextrec /diffrec /recrange
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, format_time, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    cmds = [
        ('firstrec', 'Shows first ranked record on current track'),
        ('lastrec',  'Shows last ranked record on current track'),
        ('nextrec',  'Shows next better ranked record to beat'),
        ('diffrec',  'Shows your difference to first ranked record'),
        ('recrange', 'Shows difference first to last ranked record'),
    ]
    for name, help_text in cmds:
        aseco.add_chat_command(name, help_text)
        aseco.register_event(f'onChat_{name}', globals()[f'chat_{name}'])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_stnt(aseco: 'Aseco') -> bool:
    return bool(aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)


def _fmt_rec(aseco: 'Aseco', rec, rank) -> str:
    """PHP: formatText(RANKING_RECORD_NEW, rank, nick, score) then strip trailing ', '"""
    is_stnt = _is_stnt(aseco)
    score   = str(rec.score) if is_stnt else format_time(rec.score)
    msg     = format_text(aseco.get_chat_message('RANKING_RECORD_NEW'),
                          rank, strip_colors(rec.player.nickname), score)
    return msg[:-2] if len(msg) >= 2 else msg


def _diff_fmt(diff_ms: int, sign: str = '') -> str:
    """Format millisecond difference as S.hh — PHP: sprintf('%s%d.%02d', sign, sec, hun)"""
    sec = diff_ms // 1000
    hun = (diff_ms % 1000) // 10
    return f'{sign}{sec}.{hun:02d}'


async def _relay_check(aseco: 'Aseco', login: str) -> bool:
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
        return True
    return False


async def _no_recs(aseco: 'Aseco', login: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors('{#server}> {#error}No records found!'), login)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def chat_firstrec(aseco: 'Aseco', command: dict):
    login = command['author'].login
    if await _relay_check(aseco, login):
        return
    if aseco.server.records.count() > 0:
        rec  = aseco.server.records.get_record(0)
        head = format_text(aseco.get_chat_message('FIRST_RECORD'))
        msg  = head + _fmt_rec(aseco, rec, 1)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
    else:
        await _no_recs(aseco, login)


async def chat_lastrec(aseco: 'Aseco', command: dict):
    login = command['author'].login
    if await _relay_check(aseco, login):
        return
    total = aseco.server.records.count()
    if total:
        rec  = aseco.server.records.get_record(total - 1)
        head = format_text(aseco.get_chat_message('LAST_RECORD'))
        msg  = head + _fmt_rec(aseco, rec, total)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
    else:
        await _no_recs(aseco, login)


async def chat_nextrec(aseco: 'Aseco', command: dict):
    player  = command['author']
    login   = player.login
    is_stnt = _is_stnt(aseco)
    if await _relay_check(aseco, login):
        return
    total = aseco.server.records.count()
    if not total:
        await _no_recs(aseco, login)
        return

    # Search for player's ranked record
    rank = None
    for i in range(total):
        if aseco.server.records.get_record(i).player.login == login:
            rank = i
            break

    if rank is not None:
        rec      = aseco.server.records.get_record(rank)
        nxt_rank = max(0, rank - 1)
        nxt      = aseco.server.records.get_record(nxt_rank)

        if is_stnt:
            diff     = nxt.score - rec.score
            diff_str = str(diff)
        else:
            diff     = rec.score - nxt.score
            diff_str = _diff_fmt(diff)

        msg1 = _fmt_rec(aseco, rec, rank + 1)
        msg2 = _fmt_rec(aseco, nxt, nxt_rank + 1)
        msg  = format_text(aseco.get_chat_message('DIFF_RECORD'), msg1, msg2, diff_str)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
    else:
        # Player not ranked — look for unranked time in rs_times
        unranked_score = await _get_unranked_time(aseco, player.id)
        if unranked_score is not None:
            last = aseco.server.records.get_record(total - 1)

            if is_stnt:
                diff     = last.score - unranked_score
                diff_str = str(diff)
            else:
                sign     = '-' if unranked_score < last.score else ''
                diff     = abs(unranked_score - last.score)
                diff_str = _diff_fmt(diff, sign)

            # Build fake record message for player's PB
            msg1 = format_text(aseco.get_chat_message('RANKING_RECORD_NEW'),
                                'PB', strip_colors(player.nickname),
                                str(unranked_score) if is_stnt else format_time(unranked_score))
            msg1 = msg1[:-2] if len(msg1) >= 2 else msg1
            msg2 = _fmt_rec(aseco, last, total)
            msg  = format_text(aseco.get_chat_message('DIFF_RECORD'), msg1, msg2, diff_str)
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
        else:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                aseco.format_colors(
                    "{#server}> {#error}You don't have a record on this track yet..."
                    " use {#highlite}$i/lastrec"),
                login)


async def chat_diffrec(aseco: 'Aseco', command: dict):
    player  = command['author']
    login   = player.login
    is_stnt = _is_stnt(aseco)
    if await _relay_check(aseco, login):
        return
    total = aseco.server.records.count()
    if not total:
        await _no_recs(aseco, login)
        return

    rank = None
    for i in range(total):
        if aseco.server.records.get_record(i).player.login == login:
            rank = i
            break

    if rank is not None:
        rec   = aseco.server.records.get_record(rank)
        first = aseco.server.records.get_record(0)

        if is_stnt:
            diff     = first.score - rec.score
            diff_str = str(diff)
        else:
            diff     = rec.score - first.score
            diff_str = _diff_fmt(diff)

        msg1 = _fmt_rec(aseco, rec, rank + 1)
        msg2 = _fmt_rec(aseco, first, 1)
        msg  = format_text(aseco.get_chat_message('DIFF_RECORD'), msg1, msg2, diff_str)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(
                "{#server}> {#error}You don't have a record on this track yet..."
                " use {#highlite}$i/lastrec"),
            login)


async def chat_recrange(aseco: 'Aseco', command: dict):
    login   = command['author'].login
    is_stnt = _is_stnt(aseco)
    if await _relay_check(aseco, login):
        return
    total = aseco.server.records.count()
    if not total:
        await _no_recs(aseco, login)
        return

    first = aseco.server.records.get_record(0)
    last  = aseco.server.records.get_record(total - 1)

    if is_stnt:
        diff     = first.score - last.score
        diff_str = str(diff)
    else:
        diff     = last.score - first.score
        diff_str = _diff_fmt(diff)

    msg1 = _fmt_rec(aseco, first, 1)
    msg2 = _fmt_rec(aseco, last, total)
    msg  = format_text(aseco.get_chat_message('DIFF_RECORD'), msg1, msg2, diff_str)
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

async def _get_unranked_time(aseco: 'Aseco', player_id: int):
    """Return player's best unranked time from rs_times, or None."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return None
        is_stnt = _is_stnt(aseco)
        order   = 'DESC' if is_stnt else 'ASC'
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f'SELECT score FROM rs_times WHERE playerID=%s AND challengeID=%s '
                    f'ORDER BY score {order} LIMIT 1',
                    (player_id, aseco.server.challenge.id))
                row = await cur.fetchone()
                return int(row[0]) if row else None
    except Exception:
        return None
