"""
chat_dedimania.py — Port of plugins/chat.dedimania.php

Commands:
  /helpdedi, /dedihelp
  /dedirecs [help|pb|new|live|first|last|next|diff|range]
  /dedinew, /dedilive, /dedipb
  /dedifirst, /dedilast, /dedinext, /dedidiff, /dedirange
  /dedicps
  /dedistats
  /dedicptms, /dedisectms
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import (display_manialink, display_manialink_multi,
                               format_text, format_time, strip_colors)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)


def register(aseco: 'Aseco'):
    for name, help_text in [
        ('helpdedi',  'Displays info about the Dedimania records system'),
        ('dedihelp',  'Displays info about the Dedimania records system'),
        ('dedirecs',  'Displays all Dedimania records on current track'),
        ('dedinew',   'Shows newly driven Dedimania records'),
        ('dedilive',  'Shows Dedimania records of online players'),
        ('dedipb',    'Shows your Dedimania personal best on current track'),
        ('dedifirst', 'Shows first Dedimania record on current track'),
        ('dedilast',  'Shows last Dedimania record on current track'),
        ('dedinext',  'Shows next better Dedimania record to beat'),
        ('dedidiff',  'Shows your difference to first Dedimania record'),
        ('dedirange', 'Shows difference first to last Dedimania record'),
        ('dedicps',   'Sets Dedimania record checkpoints tracking'),
        ('dedistats', 'Displays Dedimania track statistics'),
        ('dedicptms', "Displays all Dedimania records' checkpoint times"),
        ('dedisectms',"Displays all Dedimania records' sector times"),
    ]:
        aseco.add_chat_command(name, help_text)

    aseco.register_event('onChat_helpdedi',  chat_helpdedi)
    aseco.register_event('onChat_dedihelp',  chat_dedihelp)
    aseco.register_event('onChat_dedirecs',  chat_dedirecs)
    aseco.register_event('onChat_dedinew',   chat_dedinew)
    aseco.register_event('onChat_dedilive',  chat_dedilive)
    aseco.register_event('onChat_dedipb',    chat_dedipb)
    aseco.register_event('onChat_dedifirst', chat_dedifirst)
    aseco.register_event('onChat_dedilast',  chat_dedilast)
    aseco.register_event('onChat_dedinext',  chat_dedinext)
    aseco.register_event('onChat_dedidiff',  chat_dedidiff)
    aseco.register_event('onChat_dedirange', chat_dedirange)
    aseco.register_event('onChat_dedicps',   chat_dedicps)
    aseco.register_event('onChat_dedistats', chat_dedistats)
    aseco.register_event('onChat_dedicptms', chat_dedicptms)
    aseco.register_event('onChat_dedisectms',chat_dedisectms)


# ---------------------------------------------------------------------------
# Access to dedimania state
# ---------------------------------------------------------------------------

def _get_dedi_db() -> dict:
    from pyxaseco.plugins.plugin_dedimania import dedi_db
    return dedi_db


def _records() -> list[dict]:
    db   = _get_dedi_db()
    recs = db.get('Challenge', {}).get('Records', [])
    return recs if isinstance(recs, list) else []


def _server_maxrank() -> int:
    db = _get_dedi_db()
    return int(db.get('MaxRank', db.get('ServerMaxRank', 30)) or 30)


def _dedi_messages() -> dict:
    return _get_dedi_db().get('Messages', {})


def _msg(key: str, default: str) -> str:
    """Get message template from dedi_db['Messages'] with fallback."""
    val = _dedi_messages().get(key, [default])
    return val[0] if isinstance(val, list) and val else default


def _show_rec_logins() -> bool:
    return bool(_get_dedi_db().get('ShowRecLogins', False))


def _show_recs_range() -> bool:
    return bool(_get_dedi_db().get('ShowRecsRange', False))


def _show_min_recs() -> int:
    return int(_get_dedi_db().get('ShowMinRecs', 8) or 8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_stnt(aseco: 'Aseco') -> bool:
    return bool(aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)


def _score_str(aseco: 'Aseco', score: int) -> str:
    return str(score) if _is_stnt(aseco) else format_time(score)


def _diff_str(aseco: 'Aseco', diff: int, sign: str = '') -> str:
    if _is_stnt(aseco):
        return str(diff)
    sec = diff // 1000
    hun = (diff % 1000) // 10
    return f'{sign}{sec}.{hun:02d}'


def _rec_label(aseco: 'Aseco', rec: dict, pos) -> str:
    nick  = strip_colors(rec.get('NickName', rec.get('Login', '?')))
    score = _score_str(aseco, int(rec.get('Best', 0) or 0))
    msg   = format_text(aseco.get_chat_message('RANKING_RECORD_NEW'), pos, nick, score)
    return msg[:-2] if len(msg) >= 2 else msg


def _game_tag(aseco: 'Aseco') -> str:
    """TMF server -> look for 'TMU' game tag on records."""
    return 'TMU'   # TMF always uses TMU game tag for Dedimania records


def _find_player_record(aseco: 'Aseco', login: str) -> tuple[int, dict] | tuple[None, None]:
    game = _game_tag(aseco)
    for idx, rec in enumerate(_records()):
        if rec.get('Login') == login and rec.get('Game') == game:
            return idx, rec
    return None, None


async def _send(aseco: 'Aseco', login: str, message: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login)


# ---------------------------------------------------------------------------
# show_dedirecs — universal Dedimania ranking message
# ---------------------------------------------------------------------------

async def show_dedirecs(aseco: 'Aseco', name: str, uid: str,
                        dedi_recs: list, login: str | None,
                        mode: int, window: int):
    """
    Show Dedimania ranking message to a player (login set) or all (login=None).
    mode: 0=new only, 1=start, 2=during, 3=end of track
    Called by chat_dedinew, chat_dedilive, and plugin_dedimania begin/end-race hooks.
    """
    is_stnt      = _is_stnt(aseco)
    show_min     = _show_min_recs()
    total        = len(dedi_recs) if dedi_recs else 0
    online_logins = {p.login for p in aseco.server.players.all()}
    game_tag      = _game_tag(aseco)

    rec_parts = []
    totalnew  = 0

    # Compute range diff
    range_diff = None
    if _show_recs_range() and total > 0:
        first = dedi_recs[0]
        last  = dedi_recs[total - 1]
        if is_stnt:
            range_diff = int(first['Best']) - int(last['Best'])
        else:
            d = int(last['Best']) - int(first['Best'])
            range_diff = f'{d//1000}.{(d%1000)//10:02d}'

    if total == 0:
        totalnew = -1
    else:
        for i, cur_record in enumerate(dedi_recs):
            is_last  = (i == total - 1)
            best     = int(cur_record.get('Best', 0) or 0)
            score_s  = _score_str(aseco, best)
            nick     = strip_colors(cur_record.get('NickName', cur_record.get('Login', '?')))
            is_new   = bool(cur_record.get('NewBest'))
            is_online = (cur_record.get('Login') in online_logins and
                         cur_record.get('Game') == game_tag)

            if is_new:
                totalnew += 1
                rec_parts.append(format_text(
                    aseco.get_chat_message('RANKING_RECORD_NEW_ON'), i+1, nick, score_s))
            elif is_online:
                part = format_text(
                    aseco.get_chat_message('RANKING_RECORD_ON'), i+1, nick, score_s)
                if (mode != 0 and is_last) or mode in (1, 2):
                    rec_parts.append(part)
                elif mode == 3 and i < show_min:
                    rec_parts.append(part)
            else:
                part = format_text(
                    aseco.get_chat_message('RANKING_RECORD'), i+1, nick, score_s)
                if mode != 0 and is_last:
                    rec_parts.append(part)
                elif (mode == 2 and i < show_min - 2) or \
                     (mode in (1, 3) and i < show_min):
                    rec_parts.append(part)

    timing = {0: 'during', 1: 'before', 2: 'during', 3: 'after'}.get(mode, 'during')

    track_name = strip_colors(name)
    track_name = (f'$l[http://www.dedimania.net/tmstats/?do=stat&Show=RECORDS'
                  f'&RecOrder3=RANK-ASC&Uid={uid}]{track_name}$l')

    has_recs = bool(rec_parts)
    if totalnew > 0:
        message = format_text(_msg('RANKING_NEW', aseco.get_chat_message('RANKING_NEW')),
                              track_name, timing, totalnew)
    elif totalnew == 0 and has_recs:
        if _show_recs_range() and range_diff is not None:
            message = format_text(
                _msg('RANKING_RANGE', aseco.get_chat_message('RANKING_RANGE')),
                track_name, timing, range_diff)
        else:
            message = format_text(
                _msg('RANKING', aseco.get_chat_message('RANKING')),
                track_name, timing)
    elif totalnew == 0 and not has_recs:
        message = format_text(
            _msg('RANKING_NONEW', aseco.get_chat_message('RANKING_NONEW')),
            track_name, timing)
    else:
        message = format_text(
            _msg('RANKING_NONE', aseco.get_chat_message('RANKING_NONE')),
            track_name, timing)

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


# ---------------------------------------------------------------------------
# /helpdedi /dedihelp
# ---------------------------------------------------------------------------

async def chat_dedihelp(aseco: 'Aseco', command: dict):
    await chat_helpdedi(aseco, command)


async def chat_helpdedi(aseco: 'Aseco', command: dict):
    """PHP: display_manialink with widths [0.95] (single full-width column), 15 rows."""
    login = command['author'].login
    header = 'Dedimania information:'
    data = [
        ['{#dedimsg}Dedimania$g is an online World Records database for {#black}all'],
        ['TrackMania games.  See its official site at:'],
        ['{#black}$l[http://www.dedimania.net/]http://www.dedimania.net/$l$g and the records database:'],
        ['{#black}$l[http://www.dedimania.net/tmstats/?do=stat]http://www.dedimania.net/tmstats/?do=stat$l$g .'],
        [],
        ['Dedimania records are stored per game (TMN, TMU, etc)'],
        ['and mode (TimeAttack, Rounds, etc) and shared between'],
        ['all servers that operate with Dedimania support.'],
        [],
        ['The available Dedimania commands are similar to local'],
        ['record commands:'],
        ['{#black}/dedirecs$g, {#black}/dedinew$g, {#black}/dedilive$g, {#black}/dedipb$g, {#black}/dedicps$g, {#black}/dedistats$g,'],
        ['{#black}/dedifirst$g, {#black}/dedilast$g, {#black}/dedinext$g, {#black}/dedidiff$g, {#black}/dedirange$g'],
        [],
        ['See the {#black}/helpall$g command for detailed descriptions.'],
    ]
    display_manialink(aseco, login, header, ['Icons64x64_1', 'TrackInfo', -0.01],
                      data, [0.95], 'OK')


# ---------------------------------------------------------------------------
# /dedirecs [help|pb|new|live|first|last|next|diff|range]
# ---------------------------------------------------------------------------

async def chat_dedirecs(aseco: 'Aseco', command: dict):
    player   = command['author']
    login    = player.login
    recs     = _records()
    arglist  = command['params'].strip().lower().split()
    sub      = arglist[0] if arglist else ''

    # Sub-command dispatch
    if sub == 'help':
        await _dedirecs_help(aseco, login)
        return
    elif sub == 'pb':
        await chat_dedipb(aseco, command)
        return
    elif sub == 'new':
        await chat_dedinew(aseco, command)
        return
    elif sub == 'live':
        await chat_dedilive(aseco, command)
        return
    elif sub == 'first':
        await chat_dedifirst(aseco, command)
        return
    elif sub == 'last':
        await chat_dedilast(aseco, command)
        return
    elif sub == 'next':
        await chat_dedinext(aseco, command)
        return
    elif sub == 'diff':
        await chat_dedidiff(aseco, command)
        return
    elif sub == 'range':
        await chat_dedirange(aseco, command)
        return

    if not recs:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return

    maxrank     = max(_server_maxrank(), int(getattr(player, 'dedirank', 0) or 0))
    show_logins = _show_rec_logins()
    extra       = 0.2 if aseco.settings.lists_colornicks else 0

    rows = []
    for i, rec in enumerate(recs):
        nick  = rec.get('NickName', rec.get('Login', '?'))
        if not aseco.settings.lists_colornicks:
            nick = strip_colors(nick)
        score = _score_str(aseco, int(rec.get('Best', 0) or 0))
        color = '{#black}' if rec.get('NewBest') else ''

        if show_logins:
            rows.append([f'{i+1:02d}.', '{#black}' + nick,
                         '{#login}' + rec.get('Login', ''), color + score])
        else:
            rows.append([f'{i+1:02d}.', '{#black}' + nick, color + score])

    if show_logins:
        widths = [1.2+extra, 0.1, 0.45+extra, 0.4, 0.25]
    else:
        widths = [0.8+extra, 0.1, 0.45+extra, 0.25]

    pages = [rows[i:i+15] for i in range(0, len(rows), 15)]
    player.msgs = [[1, f'Current TOP {maxrank} Dedimania Records:',
                    widths, ['BgRaceScore2', 'Podium']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def _dedirecs_help(aseco: 'Aseco', login: str):
    header = '{#black}/dedirecs <option>$g shows Dedimania records and relations:'
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
                      help_data, [1.2, 0.05, 0.3, 0.85], 'OK')


# ---------------------------------------------------------------------------
# /dedinew /dedilive — call show_dedirecs() like PHP does
# ---------------------------------------------------------------------------

async def chat_dedinew(aseco: 'Aseco', command: dict):
    ch  = aseco.server.challenge
    await show_dedirecs(aseco, ch.name, ch.uid, _records(),
                        command['author'].login, 0, 0)


async def chat_dedilive(aseco: 'Aseco', command: dict):
    ch = aseco.server.challenge
    await show_dedirecs(aseco, ch.name, ch.uid, _records(),
                        command['author'].login, 2, 0)


# ---------------------------------------------------------------------------
# /dedipb
# ---------------------------------------------------------------------------

async def chat_dedipb(aseco: 'Aseco', command: dict):
    player = command['author']
    login  = player.login
    idx, rec = _find_player_record(aseco, login)

    if rec is None:
        await _send(aseco, login,
                    _msg('PB_NONE',
                         "{#server}> {#error}You don't have a Dedimania record on this track yet..."))
        return

    score = int(rec.get('Best', 0) or 0)
    msg   = format_text(_msg('PB', '{#server}> {#dedirec}Dedimania Personal Best: '
                                   '{#highlite}{1}{#dedirec} ({#rank}{2}{#dedirec})'),
                        _score_str(aseco, score), idx + 1)
    await _send(aseco, login, msg)


# ---------------------------------------------------------------------------
# /dedifirst /dedilast
# ---------------------------------------------------------------------------

async def chat_dedifirst(aseco: 'Aseco', command: dict):
    recs = _records()
    login = command['author'].login
    if not recs:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return
    prefix = format_text(_msg('FIRST_RECORD', '{#server}> {#dedirec}The first Dedimania record is: '))
    msg    = prefix + _rec_label(aseco, recs[0], 1)
    await _send(aseco, login, msg)


async def chat_dedilast(aseco: 'Aseco', command: dict):
    recs  = _records()
    login = command['author'].login
    if not recs:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return
    pos    = len(recs)
    prefix = format_text(_msg('LAST_RECORD', '{#server}> {#dedirec}The last Dedimania record is: '))
    msg    = prefix + _rec_label(aseco, recs[-1], pos)
    await _send(aseco, login, msg)


# ---------------------------------------------------------------------------
# /dedinext
# ---------------------------------------------------------------------------

async def chat_dedinext(aseco: 'Aseco', command: dict):
    player  = command['author']
    login   = player.login
    is_stnt = _is_stnt(aseco)
    recs    = _records()
    total   = len(recs)

    if not total:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return

    idx, rec = _find_player_record(aseco, login)

    if rec is not None:
        nxt_rank = max(0, idx - 1)
        nxt      = recs[nxt_rank]

        if is_stnt:
            diff     = int(nxt['Best']) - int(rec['Best'])
            diff_str = str(diff)
        else:
            diff     = int(rec['Best']) - int(nxt['Best'])
            diff_str = _diff_str(aseco, diff)

        msg1 = _rec_label(aseco, rec, idx + 1)
        msg2 = _rec_label(aseco, nxt, nxt_rank + 1)
        msg  = format_text(_msg('DIFF_RECORD', aseco.get_chat_message('DIFF_RECORD')),
                           msg1, msg2, diff_str)
        await _send(aseco, login, msg)
    else:
        unranked = await _get_unranked_time(aseco, player.id)
        if unranked is not None:
            last = recs[total - 1]
            if is_stnt:
                diff     = int(last['Best']) - unranked
                diff_str = str(diff)
            else:
                sign     = '-' if unranked < int(last['Best']) else ''
                diff     = abs(unranked - int(last['Best']))
                diff_str = _diff_str(aseco, diff, sign)

            # Build PB fake record label
            nick    = strip_colors(player.nickname)
            pb_score = _score_str(aseco, unranked)
            msg1    = format_text(aseco.get_chat_message('RANKING_RECORD_NEW'),
                                  'PB', nick, pb_score)
            msg1    = msg1[:-2] if len(msg1) >= 2 else msg1
            msg2    = _rec_label(aseco, last, total)
            msg     = format_text(_msg('DIFF_RECORD', aseco.get_chat_message('DIFF_RECORD')),
                                  msg1, msg2, diff_str)
            await _send(aseco, login, msg)
        else:
            await _send(aseco, login,
                        "{#server}> {#error}You don't have a Dedimania record on this track yet..."
                        " use {#highlite}$i/dedilast")


# ---------------------------------------------------------------------------
# /dedidiff
# ---------------------------------------------------------------------------

async def chat_dedidiff(aseco: 'Aseco', command: dict):
    player  = command['author']
    login   = player.login
    is_stnt = _is_stnt(aseco)
    recs    = _records()

    if not recs:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return

    idx, rec = _find_player_record(aseco, login)
    if rec is None:
        await _send(aseco, login,
                    "{#server}> {#error}You don't have a Dedimania record on this track yet..."
                    " use {#highlite}$i/dedilast")
        return

    first = recs[0]
    if is_stnt:
        diff     = int(first['Best']) - int(rec['Best'])
        diff_str = str(diff)
    else:
        diff     = int(rec['Best']) - int(first['Best'])
        diff_str = _diff_str(aseco, diff)

    msg1 = _rec_label(aseco, rec, idx + 1)
    msg2 = _rec_label(aseco, first, 1)
    msg  = format_text(_msg('DIFF_RECORD', aseco.get_chat_message('DIFF_RECORD')),
                       msg1, msg2, diff_str)
    await _send(aseco, login, msg)


# ---------------------------------------------------------------------------
# /dedirange
# ---------------------------------------------------------------------------

async def chat_dedirange(aseco: 'Aseco', command: dict):
    login   = command['author'].login
    is_stnt = _is_stnt(aseco)
    recs    = _records()

    if not recs:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return

    first = recs[0]
    last  = recs[-1]

    if is_stnt:
        diff     = int(first['Best']) - int(last['Best'])
        diff_str = str(diff)
    else:
        diff     = int(last['Best']) - int(first['Best'])
        diff_str = _diff_str(aseco, diff)

    msg1 = _rec_label(aseco, first, 1)
    msg2 = _rec_label(aseco, last, len(recs))
    msg  = format_text(_msg('DIFF_RECORD', aseco.get_chat_message('DIFF_RECORD')),
                       msg1, msg2, diff_str)
    await _send(aseco, login, msg)


# ---------------------------------------------------------------------------
# /dedicps
# ---------------------------------------------------------------------------

async def chat_dedicps(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    await _send(
        aseco,
        login,
        '{#server}> {#error}/dedicps is no longer available. '
        '{#dedimsg}Use {#highlite}/ztrack dedi <nr>{#dedimsg} instead.'
    )


# ---------------------------------------------------------------------------
# /dedistats
# ---------------------------------------------------------------------------

async def chat_dedistats(aseco: 'Aseco', command: dict):
    player = command['author']
    login  = player.login
    db     = _get_dedi_db()
    ch     = db.get('Challenge', {})
    uid    = ch.get('Uid', getattr(aseco.server.challenge, 'uid', ''))
    total_races   = int(ch.get('TotalRaces', 0) or 0)
    total_players = int(ch.get('TotalPlayers', 0) or 0)
    avg_players   = round(total_players / total_races, 2) if total_races > 0 else 0

    header = f'Dedimania Stats: {{#black}}{strip_colors(aseco.server.challenge.name)}'
    stats  = [
        ['Server MaxRank', f'{{#black}}{_server_maxrank()}'],
        ['Your MaxRank',   f'{{#black}}{int(getattr(player, "dedirank", 0) or _server_maxrank())}'],
        [],
        ['UID',            f'{{#black}}{uid}'],
        ['Total Races',    f'{{#black}}{total_races}'],
        ['Total Players',  f'{{#black}}{total_players}'],
        ['Avg. Players',   f'{{#black}}{avg_players}'],
        [],
        [f'               {{#black}}$l[http://dedimania.net/tmstats/?do=stat'
         f'&RecOrder3=RANK-ASC&Uid={uid}&Show=RECORDS]View all Dedimania records for this track$l'],
    ]
    display_manialink(aseco, login, header,
                      ['Icons64x64_1', 'Maximize', -0.01],
                      stats, [1.0, 0.3, 0.7], 'OK')


# ---------------------------------------------------------------------------
# /dedicptms /dedisectms
# ---------------------------------------------------------------------------

async def chat_dedicptms(aseco: 'Aseco', command: dict):
    await _show_dedi_cp_times(aseco, command, diff=False)


async def chat_dedisectms(aseco: 'Aseco', command: dict):
    await _show_dedi_cp_times(aseco, command, diff=True)


async def _show_dedi_cp_times(aseco: 'Aseco', command: dict, diff: bool):
    player = command['author']
    login  = player.login
    recs   = _records()

    if not recs:
        await _send(aseco, login, '{#server}> {#error}No Dedimania records found!')
        return

    first_checks = recs[0].get('Checks', []) or []
    cpscnt       = len(first_checks)
    if cpscnt == 0:
        await _send(aseco, login,
                    '{#server}> {#error}No Dedimania '
                    + ('sector' if diff else 'CP') + ' times available')
        return

    maxrank = max(_server_maxrank(), int(getattr(player, 'dedirank', 0) or 0))
    cpsmax  = 12

    width  = 0.1 + 0.18 + min(cpscnt, cpsmax) * 0.1 + (0.06 if cpscnt > cpsmax else 0.0)
    if width < 1.0:
        width = 1.0
    widths = [width, 0.1, 0.18]
    widths.extend([0.1] * min(cpscnt, cpsmax))
    if cpscnt > cpsmax:
        widths.append(0.06)

    title = (f'Current TOP {maxrank} Dedimania '
             f'{"Sector" if diff else "CP"} Times ({cpscnt}):')
    rows  = []
    for i, rec in enumerate(recs, 1):
        is_new  = bool(rec.get('NewBest'))
        best    = int(rec.get('Best', 0) or 0)
        line    = [f'{i:02d}.', ('{#black}' if is_new else '') + format_time(best)]
        checks  = rec.get('Checks', []) or []
        prev    = 0
        j       = 0
        for cp in checks:
            if j >= cpsmax:
                break
            value = (cp - prev) if diff else cp
            line.append('$n' + format_time(int(value)))
            if diff:
                prev = cp
            j += 1
        if cpscnt > cpsmax:
            line.append('+')
        rows.append(line)

    pages = [rows[i:i+15] for i in range(0, len(rows), 15)]
    player.msgs = [[1, title, widths, ['BgRaceScore2', 'Podium']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

async def _get_unranked_time(aseco: 'Aseco', player_id: int):
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
