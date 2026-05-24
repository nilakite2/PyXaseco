"""
RASP nextmap backend - ported from the original XAseco nextmap runtime.

/nextmap - Shows name of the next challenge.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text, strip_colors
from pyxaseco.models import _strip_newlines

from .jukebox import get_jukebox
from .rankings import get_messages

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('nextmap', 'Shows name of the next challenge')
    aseco.register_event('onChat_nextmap', chat_nextmap)


async def chat_nextmap(aseco: 'Aseco', command: dict):
    login = command['author'].login

    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
        return

    try:
        msgs = get_messages()
    except Exception:
        msgs = {}

    # Check jukebox first
    jukebox = get_jukebox()
    next_name = ''
    next_env  = ''

    if jukebox:
        uid, track = next(iter(jukebox.items()))
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
                next_env  = track_list[0].get('Environnement', '')
        except Exception:
            next_name = '?'

    if aseco.server.packmask == 'Stadium':
        msg_key = 'NEXTMAP'
        message = format_text(msgs.get(msg_key, ['{#server}> Next map: {1}'])[0],
                              strip_colors(next_name))
    else:
        msg_key = 'NEXTENVMAP'
        message = format_text(msgs.get(msg_key, ['{#server}> Next [{1}]: {2}'])[0],
                              next_env, strip_colors(next_name))

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login)

