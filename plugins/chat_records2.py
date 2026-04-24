"""
chat_records2.py — Port of plugins/chat.records2.php

Provides:
  show_trackrecs() — universal ranking message (called by aseco core + /newrecs /liverecs)
  get_recs()       — per-player ranked record list from DB (used by /best /worst /summary /stats)
  /newrecs /liverecs /best /worst /summary /topsums /toprecs
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from pyxaseco.helpers import (format_text, format_time, strip_colors,
                               display_manialink_multi)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)


def register(aseco: 'Aseco'):
    aseco.add_chat_command('newrecs',  'Shows newly driven records')
    aseco.add_chat_command('liverecs', 'Shows records of online players')
    aseco.add_chat_command('best',     'Displays your best records')
    aseco.add_chat_command('worst',    'Displays your worst records')
    aseco.add_chat_command('summary',  'Shows summary of all your records')
    aseco.add_chat_command('topsums',  'Displays top 100 of top-3 record holders')
    aseco.add_chat_command('toprecs',  'Displays top 100 ranked records holders')

    aseco.register_event('onChat_newrecs',  chat_newrecs)
    aseco.register_event('onChat_liverecs', chat_liverecs)
    aseco.register_event('onChat_best',     chat_best)
    aseco.register_event('onChat_worst',    chat_worst)
    aseco.register_event('onChat_summary',  chat_summary)
    aseco.register_event('onChat_topsums',  chat_topsums)
    aseco.register_event('onChat_toprecs',  chat_toprecs)

    aseco.register_event('onEndRace',   event_endrace_recs)
    aseco.register_event('onBeginRace', event_beginrace_recs)


# ---------------------------------------------------------------------------
# Universal ranking message
# ---------------------------------------------------------------------------

async def show_trackrecs(aseco: 'Aseco', login: str | None, mode: int, window: int):
    """
    Show ranking records to a player (login set) or all (login=None).
    mode: 0=new only, 1=start of track, 2=during track, 3=end of track
    window: bitmask, 4=use message window if available
    """
    records   = aseco.server.records
    total     = records.count()
    is_stnt   = aseco.server.gameinfo and aseco.server.gameinfo.mode == 4
    online_logins = {p.login for p in aseco.server.players.all()}
    show_min  = aseco.settings.show_min_recs

    # Compute range diff
    range_diff = None
    if aseco.settings.show_recs_range and total > 0:
        first = records.get_record(0)
        last  = records.get_record(total - 1)
        if is_stnt:
            range_diff = first.score - last.score
        else:
            d = last.score - first.score
            range_diff = f'{d//1000}.{(d%1000)//10:02d}'

    # Build record parts; we use a list
    rec_parts = []
    totalnew  = 0
    if total == 0:
        totalnew = -1
    else:
        for i in range(total):
            rec      = records.get_record(i)
            score_str = str(rec.score) if is_stnt else format_time(rec.score)
            nick      = strip_colors(rec.player.nickname)
            is_online = rec.player.login in online_logins
            is_last   = (i == total - 1)

            if rec.new:
                totalnew += 1
                rec_parts.append(format_text(
                    aseco.get_chat_message('RANKING_RECORD_NEW_ON'), i+1, nick, score_str))
            elif is_online:
                part = format_text(
                    aseco.get_chat_message('RANKING_RECORD_ON'), i+1, nick, score_str)
                if (mode != 0 and is_last) or mode in (1, 2) or (mode == 3 and i < show_min):
                    rec_parts.append(part)
            else:
                part = format_text(
                    aseco.get_chat_message('RANKING_RECORD'), i+1, nick, score_str)
                if mode != 0 and is_last:
                    rec_parts.append(part)
                elif (mode == 2 and i < show_min - 2) or (mode in (1, 3) and i < show_min):
                    rec_parts.append(part)

    timing = {0: 'during', 1: 'before', 2: 'during', 3: 'after'}.get(mode, 'during')
    name   = strip_colors(aseco.server.challenge.name)

    # Choose header message
    has_recs = bool(rec_parts)
    if totalnew > 0:
        message = format_text(aseco.get_chat_message('RANKING_NEW'), name, timing, totalnew)
    elif totalnew == 0 and has_recs:
        if aseco.settings.show_recs_range and range_diff is not None:
            message = format_text(aseco.get_chat_message('RANKING_RANGE'),
                                  name, timing, range_diff)
        else:
            message = format_text(aseco.get_chat_message('RANKING'), name, timing)
    elif totalnew == 0 and not has_recs:
        message = format_text(aseco.get_chat_message('RANKING_NONEW'), name, timing)
    else:
        message = format_text(aseco.get_chat_message('RANKING_NONE'), name, timing)

    # Append records
    if rec_parts:
        records_str = ''.join(rec_parts)
        if records_str.endswith(', '):
            records_str = records_str[:-2]
        message += '\n' + records_str

    if login:
        message = message.replace('{#server}>> ', '{#server}> ')
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(message), login)
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(message))


async def event_endrace_recs(aseco: 'Aseco', _params):
    if aseco.settings.show_recs_after:
        await show_trackrecs(aseco, None, 3, aseco.settings.show_recs_after)


async def event_beginrace_recs(aseco: 'Aseco', _challenge):
    if aseco.settings.show_recs_before:
        await show_trackrecs(aseco, None, 1, aseco.settings.show_recs_before)


# ---------------------------------------------------------------------------
# get_recs — per-player ranked record list from DB
# ---------------------------------------------------------------------------

async def get_recs(aseco: 'Aseco', player_id: int) -> dict:
    """
    Return dict of {uid: rank} for all tracks where player_id has a record.
    """
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return {}
        is_stnt = aseco.server.gameinfo and aseco.server.gameinfo.mode == 4
        order   = 'DESC' if is_stnt else 'ASC'
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f'SELECT Uid, PlayerId FROM records r '
                    f'LEFT JOIN challenges c ON (r.ChallengeId=c.Id) '
                    f'WHERE Uid IS NOT NULL '
                    f'ORDER BY ChallengeId ASC, Score {order}, Date ASC'
                )
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning('get_recs error: %s', e)
        return {}

    result   = {}
    last_uid = None
    pos      = 1
    for uid, pid in rows:
        if uid != last_uid:
            last_uid = uid
            pos      = 1
        if uid in result:
            pos += 1
            continue
        if pid == player_id:
            result[uid] = pos
        pos += 1

    return result


async def _get_challenge_list(aseco: 'Aseco') -> dict:
    """Get server challenge list. Returns {uid: track_info}."""
    try:
        batch_size = 500
        offset = 0
        result = {}
        while True:
            tracks = await aseco.client.query('GetChallengeList', batch_size, offset) or []
            if not tracks:
                break
            for t in tracks:
                uid = t.get('UId', '')
                if uid:
                    result[uid] = t
            if len(tracks) < batch_size:
                break
            offset += batch_size
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# /newrecs /liverecs
# ---------------------------------------------------------------------------

async def chat_newrecs(aseco: 'Aseco', command: dict):
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), command['author'].login)
        return
    await show_trackrecs(aseco, command['author'].login, 0, 0)


async def chat_liverecs(aseco: 'Aseco', command: dict):
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), command['author'].login)
        return
    await show_trackrecs(aseco, command['author'].login, 2, 0)


# ---------------------------------------------------------------------------
# /best /worst
# ---------------------------------------------------------------------------

async def chat_best(aseco: 'Aseco', command: dict):
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), command['author'].login)
        return
    await _disp_recs(aseco, command, best=True)


async def chat_worst(aseco: 'Aseco', command: dict):
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), command['author'].login)
        return
    await _disp_recs(aseco, command, best=False)


_DISP_HEADER_STADIUM     = ['Id', 'Rec', 'Name', 'Author']
_DISP_HEADER_NONSTADIUM  = ['Id', 'Rec', 'Name', 'Author', 'Env']
_ENV_IDS = {'Stadium': 11, 'Alpine': 12, 'Bay': 13, 'Coast': 14,
            'Island': 15, 'Rally': 16, 'Speed': 17}


async def _disp_recs(aseco: 'Aseco', command: dict, best: bool):
    player = command['author']
    target = player

    # Checks allowAbility for admin cross-lookup
    if command['params'].strip() and aseco.allow_ability(player, 'chat_bestworst'):
        t = aseco.server.players.get_player(command['params'].strip())
        if t:
            target = t

    rec_list = await get_recs(aseco, target.id)
    if not rec_list:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No records found!'), player.login)
        return

    sorted_list = sorted(rec_list.items(), key=lambda x: x[1], reverse=not best)
    newlist     = await _get_challenge_list(aseco)

    is_stadium  = (getattr(aseco.server, 'packmask', 'Stadium') == 'Stadium')
    HEADER      = _DISP_HEADER_STADIUM if is_stadium else _DISP_HEADER_NONSTADIUM

    head = (('Best' if best else 'Worst') + ' Records for '
            + target.nickname.replace('$w', '').replace('$W', '') + '$z:')

    if is_stadium:
        widths = [1.42, 0.12, 0.1, 0.8, 0.4]
    else:
        widths = [1.59, 0.12, 0.1, 0.8, 0.4, 0.17]

    player.tracklist = []
    tid              = 1
    page_data        = []   # accumulates entries (not including header)
    pages_built      = []   # final list of pages for player.msgs
    lines            = 0

    for uid, pos in sorted_list:
        if uid not in newlist:
            continue
        row = newlist[uid]
        player.tracklist.append({
            'name': row.get('Name', ''), 'author': row.get('Author', ''),
            'environment': row.get('Environnement', ''),
            'filename': row.get('FileName', ''), 'uid': uid
        })

        trackname = row.get('Name', '')
        if not aseco.settings.lists_colortracks:
            trackname = strip_colors(trackname)
        trackname = '{#black}' + trackname
        if aseco.settings.clickable_lists and tid <= 1900:
            trackname = [trackname, tid + 100]

        trackauthor = row.get('Author', '')
        if aseco.settings.clickable_lists and tid <= 1900:
            trackauthor = [trackauthor, -100 - tid]

        if is_stadium:
            entry = [f'{tid:03d}.', f'{pos:02d}.', trackname, trackauthor]
        else:
            trackenv = row.get('Environnement', '')
            if aseco.settings.clickable_lists:
                trackenv = [trackenv, _ENV_IDS.get(trackenv, 11)]
            entry = [f'{tid:03d}.', f'{pos:02d}.', trackname, trackauthor, trackenv]

        page_data.append(entry)
        tid   += 1
        lines += 1
        if lines > 14:
            pages_built.append([HEADER] + page_data)
            lines     = 0
            page_data = []

    if page_data:
        pages_built.append([HEADER] + page_data)

    if not pages_built:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No records found!'), player.login)
        return

    player.msgs = [[1, head, widths, ['Icons128x128_1', 'NewTrack', 0.02]]]
    player.msgs.extend(pages_built)
    display_manialink_multi(aseco, player)


# ---------------------------------------------------------------------------
# /summary
# ---------------------------------------------------------------------------

async def chat_summary(aseco: 'Aseco', command: dict):
    player = command['author']
    target = player
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), player.login)
        return

    # Checks allowAbility for admin cross-lookup
    if command['params'].strip() and aseco.allow_ability(player, 'chat_summary'):
        t = aseco.server.players.get_player(command['params'].strip())
        if t:
            target = t

    maxrecs = 0
    try:
        from pyxaseco.plugins.plugin_rasp import maxrecs as _mr
        maxrecs = _mr
    except ImportError:
        pass

    rec_list = await get_recs(aseco, target.id)
    if not rec_list:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No ranked records found!'), player.login)
        return

    newlist     = await _get_challenge_list(aseco)
    sorted_list = sorted(rec_list.items(), key=lambda x: x[1])

    show   = 3
    total  = 0
    cntrec = 0
    currec = 0
    message = ''

    for uid, rec in sorted_list:
        if rec > maxrecs:
            break
        if uid not in newlist:
            continue
        total += 1
        if show > 0:
            if rec == currec:
                cntrec += 1
            else:
                if currec > 0:
                    message += format_text(aseco.get_chat_message('SUM_ENTRY'),
                                           cntrec, 's' if cntrec > 1 else '', currec)
                    show -= 1
                cntrec = 1
                currec = rec

    if show > 0 and currec > 0:
        message += format_text(aseco.get_chat_message('SUM_ENTRY'),
                               cntrec, 's' if cntrec > 1 else '', currec)

    if message:
        show_word = {1: 'one', 2: 'two', 3: 'three'}.get(3 - show, str(3 - show))
        if message.endswith(', '):
            message = message[:-2]
        full_msg = format_text(aseco.get_chat_message('SUMMARY'),
                               target.nickname,
                               total, 's' if total > 1 else '',
                               show_word) + message
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(full_msg), player.login)
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No ranked records found!'), player.login)


# ---------------------------------------------------------------------------
# /topsums — Top 100 of top-3 record holders
# ---------------------------------------------------------------------------

async def chat_topsums(aseco: 'Aseco', command: dict):
    player = command['author']
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), player.login)
        return

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return
        is_stnt = aseco.server.gameinfo and aseco.server.gameinfo.mode == 4
        order   = 'DESC' if is_stnt else 'ASC'
        newlist = await _get_challenge_list(aseco)

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT Id, Uid FROM challenges')
                chal_rows = await cur.fetchall()
                tid_list  = [row[0] for row in chal_rows if row[1] in newlist]

        recs: dict[str, list] = {}
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for tid in tid_list:
                    await cur.execute(
                        f'SELECT login FROM players,records '
                        f'WHERE players.id=records.playerid AND challengeid=%s '
                        f'ORDER BY score {order}, date ASC LIMIT 3',
                        (tid,))
                    top3 = await cur.fetchall()
                    for i, row in enumerate(top3):
                        lgn = row[0]
                        if lgn not in recs:
                            recs[lgn] = [0, 0, 0]
                        recs[lgn][i] += 1

        if not recs:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                aseco.format_colors('{#server}> {#error}No players with ranked records found!'),
                player.login)
            return

        sorted_recs = sorted(recs.items(),
                             key=lambda x: (-x[1][0], -x[1][1], -x[1][2]))[:100]

        head  = 'TOP 100 of Top-3 Record Holders:'
        extra = 0.2 if aseco.settings.lists_colornicks else 0
        rows  = []
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for i, (lgn, top3) in enumerate(sorted_recs, 1):
                    await cur.execute(
                        'SELECT NickName FROM players WHERE Login=%s', (lgn,))
                    nrow = await cur.fetchone()
                    nick = nrow[0] if nrow else lgn
                    if not aseco.settings.lists_colornicks:
                        nick = strip_colors(nick)
                    rows.append([f'{i:02d}.', '{#black}' + nick,
                                 f'{top3[0]:3d} / {top3[1]:3d} / {top3[2]:3d}'])

        pages = [rows[i:i+15] for i in range(0, max(len(rows), 1), 15)]
        player.msgs = [[1, head, [0.85+extra, 0.1, 0.45+extra, 0.3],
                        ['BgRaceScore2', 'LadderRank']]]
        player.msgs.extend(pages)
        display_manialink_multi(aseco, player)

    except Exception as e:
        logger.warning('chat_topsums error: %s', e)


# ---------------------------------------------------------------------------
# /toprecs — Top 100 ranked record holders
# ---------------------------------------------------------------------------

async def chat_toprecs(aseco: 'Aseco', command: dict):
    player = command['author']
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), player.login)
        return

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        maxrecs = 0
        try:
            from pyxaseco.plugins.plugin_rasp import maxrecs as _mr
            maxrecs = _mr
        except ImportError:
            pass

        pool = await get_pool()
        if not pool:
            return
        is_stnt = aseco.server.gameinfo and aseco.server.gameinfo.mode == 4
        order   = 'DESC' if is_stnt else 'ASC'
        newlist = await _get_challenge_list(aseco)

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT Id, Uid FROM challenges')
                chal_rows = await cur.fetchall()
                tid_list  = [row[0] for row in chal_rows if row[1] in newlist]

        recs: dict[str, int] = {}
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for tid in tid_list:
                    await cur.execute(
                        f'SELECT login FROM players,records '
                        f'WHERE players.id=records.playerid AND challengeid=%s '
                        f'ORDER BY score {order}, date ASC LIMIT %s',
                        (tid, maxrecs))
                    for row in await cur.fetchall():
                        lgn       = row[0]
                        recs[lgn] = recs.get(lgn, 0) + 1

        if not recs:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                aseco.format_colors('{#server}> {#error}No players with ranked records found!'),
                player.login)
            return

        sorted_recs = sorted(recs.items(), key=lambda x: -x[1])[:100]

        head  = 'TOP 100 Ranked Record Holders:'
        extra = 0.2 if aseco.settings.lists_colornicks else 0
        rows_out: list = []
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for i, (lgn, count) in enumerate(sorted_recs, 1):
                    await cur.execute(
                        'SELECT NickName FROM players WHERE Login=%s', (lgn,))
                    nrow = await cur.fetchone()
                    nick = nrow[0] if nrow else lgn
                    if not aseco.settings.lists_colornicks:
                        nick = strip_colors(nick)
                    rows_out.append([f'{i:02d}.', '{#black}' + nick, str(count)])

        pages = [rows_out[i:i+15] for i in range(0, max(len(rows_out), 1), 15)]
        player.msgs = [[1, head, [0.7+extra, 0.1, 0.45+extra, 0.15],
                        ['BgRaceScore2', 'LadderRank']]]
        player.msgs.extend(pages)
        display_manialink_multi(aseco, player)

    except Exception as e:
        logger.warning('chat_toprecs error: %s', e)
