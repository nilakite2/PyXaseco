"""
track.py - Port of plugins/plugin.track.php

/track    - Shows info about the current track
/playtime - Shows time current track has been playing
/time     - Shows current server time & date
/nextmap  - Shows info about the next track

Also fires onNewChallenge2 events for timing and CURRENT_TRACK display.
"""

from __future__ import annotations
import datetime as _dt
import time as _time
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, format_time, format_time_h, strip_colors
from pyxaseco.models import Gameinfo
from pyxaseco.models import _strip_newlines
from pyxaseco.app_services import get_tmx_service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

_replays_total: int = 0
_replays_counter: int = 0


def _build_public_tmx_track_url(aseco: 'Aseco', challenge=None):
    service = get_tmx_service(aseco)
    impl = getattr(service, 'build_public_tmx_track_url', None) if service is not None else None
    if not callable(impl):
        return None
    return impl(aseco, challenge=challenge)


def register(aseco: 'Aseco'):
    aseco.register_event('onNewChallenge',  time_gameinfo)
    aseco.register_event('onNewChallenge2', time_newtrack)
    aseco.register_event('onEndRace',       time_endrace)
    aseco.register_event('onSync',          time_initreplays)

    aseco.add_chat_command('track',    'Shows info about the current track')
    aseco.add_chat_command('playtime', 'Shows time current track has been playing')
    aseco.add_chat_command('time',     'Shows current server time & date')
    aseco.add_chat_command('nextmap',  'Shows name of the next challenge')

    aseco.register_event('onChat_track',    chat_track)
    aseco.register_event('onChat_playtime', chat_playtime)
    aseco.register_event('onChat_time',     chat_time)
    aseco.register_event('onChat_nextmap',  chat_nextmap)


def _tmx_linked_name(aseco: 'Aseco', challenge) -> str:
    name = strip_colors(challenge.name)
    try:
        pageurl = _build_public_tmx_track_url(aseco, challenge=challenge)
    except Exception:
        pageurl = ''
    if pageurl:
        return f'$l[{pageurl}]{name}$l'
    return name


def _tz_abbrev() -> str:
    # Prefer a real timezone abbreviation -> CEST/CET.
    now = _dt.datetime.now().astimezone()
    abbr = now.strftime('%Z') or ''
    if abbr and ' ' not in abbr:
        return abbr
    offset = now.utcoffset()
    if offset is None:
        return 'UTC'
    total = int(offset.total_seconds() // 60)
    sign = '+' if total >= 0 else '-'
    total = abs(total)
    return f'UTC{sign}{total // 60:02d}:{total % 60:02d}'


def time_playing(aseco: 'Aseco') -> float:
    start_t = getattr(aseco.server.challenge, 'starttime', aseco.server.starttime)
    return max(0.0, float(int(_time.time()) - int(start_t)))


async def time_initreplays(aseco: 'Aseco', _param):
    global _replays_total, _replays_counter
    _replays_total = 0
    _replays_counter = 0
    aseco.server.starttime = int(_time.time())


async def time_newtrack(aseco: 'Aseco', _param):
    global _replays_total
    aseco.server.challenge.starttime = int(_time.time())
    if _replays_total == 0:
        aseco.server.starttime = int(_time.time())


async def time_gameinfo(aseco: 'Aseco', challenge):
    if not aseco.settings.show_curtrack:
        return

    name = _tmx_linked_name(aseco, challenge)
    is_stnt = aseco.server.gameinfo and aseco.server.gameinfo.mode == Gameinfo.STNT
    author_time = (getattr(getattr(challenge, 'gbx', None), 'author_score', 0)
                   if is_stnt else format_time(challenge.authortime))
    message = format_text(aseco.get_chat_message('CURRENT_TRACK'),
                          name, challenge.author, author_time)
    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))


async def time_endrace(aseco: 'Aseco', _params):
    global _replays_total
    is_stnt = aseco.server.gameinfo and aseco.server.gameinfo.mode == Gameinfo.STNT
    is_ta   = aseco.server.gameinfo and aseco.server.gameinfo.mode == Gameinfo.TA

    if not aseco.settings.show_playtime or is_ta or is_stnt:
        return

    name = _tmx_linked_name(aseco, aseco.server.challenge)
    start_t = getattr(aseco.server.challenge, 'starttime', aseco.server.starttime)
    playtime  = format_time_h((int(_time.time()) - start_t) * 1000, False)
    totaltime = format_time_h((int(_time.time()) - aseco.server.starttime) * 1000, False)

    message = format_text(aseco.get_chat_message('PLAYTIME_FINISH'), name, playtime)
    if _replays_total > 0:
        message += format_text(aseco.get_chat_message('PLAYTIME_REPLAY'),
                               _replays_total, '' if _replays_total == 1 else 's', totaltime)

    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))


async def chat_track(aseco: 'Aseco', command: dict):
    challenge = aseco.server.challenge
    is_stnt = aseco.server.gameinfo and aseco.server.gameinfo.mode == Gameinfo.STNT
    name = strip_colors(challenge.name)

    if is_stnt:
        author_score = getattr(getattr(challenge, 'gbx', None), 'author_score', 0)
        message = format_text(aseco.get_chat_message('TRACK'),
                              name, challenge.author, author_score,
                              challenge.goldtime, challenge.silvertime,
                              challenge.bronzetime, challenge.copperprice)
    else:
        message = format_text(aseco.get_chat_message('TRACK'),
                              name, challenge.author,
                              format_time(challenge.authortime),
                              format_time(challenge.goldtime),
                              format_time(challenge.silvertime),
                              format_time(challenge.bronzetime),
                              challenge.copperprice)

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message),
        command['author'].login)


async def chat_playtime(aseco: 'Aseco', command: dict):
    global _replays_total
    name = _tmx_linked_name(aseco, aseco.server.challenge)
    start_t   = getattr(aseco.server.challenge, 'starttime', aseco.server.starttime)
    playtime  = int(_time.time()) - start_t
    totaltime = int(_time.time()) - aseco.server.starttime

    message = format_text(aseco.get_chat_message('PLAYTIME'),
                          name, format_time_h(playtime * 1000, False))
    if _replays_total > 0:
        message += format_text(aseco.get_chat_message('PLAYTIME_REPLAY'),
                               _replays_total, '' if _replays_total == 1 else 's',
                               format_time_h(totaltime * 1000, False))

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message),
        command['author'].login)


async def chat_time(aseco: 'Aseco', command: dict):
    now = _dt.datetime.now().astimezone()
    message = format_text(
        aseco.get_chat_message('TIME'),
        now.strftime('%H:%M:%S ') + _tz_abbrev(),
        now.strftime('%Y/%b/%d'),
    )
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message),
        command['author'].login)


async def chat_nextmap(aseco: 'Aseco', command: dict):
    login = command['author'].login

    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
        return

    try:
        from apps.players.rankings import get_messages
        msgs = get_messages()
    except Exception:
        msgs = {}

    next_name = ''
    next_env = ''

    try:
        from apps.jukebox.jukebox import get_jukebox
        jukebox = get_jukebox()
    except Exception:
        jukebox = {}

    if jukebox:
        _uid, track = next(iter(jukebox.items()))
        next_name = track.get('Name', '')
        try:
            info = await aseco.client.query('GetChallengeInfo', track.get('FileName', ''))
            next_env = info.get('Environnement', '')
        except Exception:
            pass
    else:
        try:
            if aseco.server.get_game() != 'TMF':
                current_idx = await aseco.client.query('GetCurrentChallengeIndex')
                track_list = await aseco.client.query('GetChallengeList', 1, int(current_idx) + 1)
                if not track_list:
                    track_list = await aseco.client.query('GetChallengeList', 1, 0)
            else:
                next_idx = await aseco.client.query('GetNextChallengeIndex')
                track_list = await aseco.client.query('GetChallengeList', 1, next_idx)
                if not track_list:
                    track_list = await aseco.client.query('GetChallengeList', 1, 0)
            if track_list:
                next_name = _strip_newlines(track_list[0].get('Name', ''))
                next_env = track_list[0].get('Environnement', '')
        except Exception:
            next_name = '?'

    if aseco.server.packmask == 'Stadium':
        message = format_text(
            msgs.get('NEXTMAP', ['{#server}> The next Challenge will be: {#highlite}{1}'])[0],
            strip_colors(next_name),
        )
    else:
        message = format_text(
            msgs.get('NEXTENVMAP', ['{#server}> The next Challenge will be: {#highlite}[{1}] {2}'])[0],
            next_env,
            strip_colors(next_name),
        )

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login)

