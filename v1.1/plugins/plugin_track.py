"""
plugin_track.py — Port of plugins/plugin.track.php

/track    — Shows info about the current track
/playtime — Shows time current track has been playing
/time     — Shows current server time & date

Also fires onNewChallenge2 events for timing and CURRENT_TRACK display.
"""

from __future__ import annotations
import datetime as _dt
import time as _time
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, format_time, format_time_h, strip_colors
from pyxaseco.models import Gameinfo
from pyxaseco.plugins.plugin_tmxinfo import build_public_tmx_track_url as _build_public_tmx_track_url

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

_replays_total: int = 0
_replays_counter: int = 0


def register(aseco: 'Aseco'):
    aseco.register_event('onNewChallenge',  time_gameinfo)
    aseco.register_event('onNewChallenge2', time_newtrack)
    aseco.register_event('onEndRace',       time_endrace)
    aseco.register_event('onSync',          time_initreplays)

    aseco.add_chat_command('track',    'Shows info about the current track')
    aseco.add_chat_command('playtime', 'Shows time current track has been playing')
    aseco.add_chat_command('time',     'Shows current server time & date')

    aseco.register_event('onChat_track',    chat_track)
    aseco.register_event('onChat_playtime', chat_playtime)
    aseco.register_event('onChat_time',     chat_time)


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
