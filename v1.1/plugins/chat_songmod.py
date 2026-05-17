"""
chat_songmod.py — Port of plugins/chat.songmod.php

/song — Shows current track's song filename
/mod  — Shows current track's mod name/filename
"""

from __future__ import annotations

import html
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Any

from pyxaseco.helpers import format_text, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


def register(aseco: 'Aseco'):
    aseco.add_chat_command('song', "Shows filename of current track's song")
    aseco.add_chat_command('mod',  "Shows (file)name of current track's mod")
    aseco.register_event('onChat_song', chat_song)
    aseco.register_event('onChat_mod',  chat_mod)


def _gbx_value(gbx: Any, *names: str):
    """Return the first present non-empty GBX attribute from multiple aliases."""
    if gbx is None:
        return None
    for name in names:
        value = getattr(gbx, name, None)
        if value not in (None, ''):
            return value
    return None


def _first_param(command: dict) -> str:
    params = command.get('params') or ''
    if isinstance(params, str):
        parts = params.split(None, 1)
    else:
        parts = list(params) if params else []
    return str(parts[0]).lower() if parts else ''


def _has_music_command(aseco: 'Aseco') -> bool:
    try:
        return 'music' in getattr(aseco, '_chat_commands', {})
    except Exception:
        return False


def _challenge_abs_path(aseco: 'Aseco') -> pathlib.Path | None:
    challenge = getattr(aseco.server, 'challenge', None)
    filename = getattr(challenge, 'filename', '') or ''
    if not filename:
        return None
    try:
        return (aseco._base_dir.parent / 'GameData' / 'Tracks' / filename).resolve()
    except Exception:
        return None


def _parse_songmod_from_gbx(path: pathlib.Path) -> dict[str, str]:
    """
    Parse song/mod dependency info directly from the GBX header text.
    """
    with open(path, 'rb') as f:
        data = f.read(262144)  # 256 KiB is plenty for the XML header

    text = data.decode('utf-8', errors='ignore')

    dep_re = re.compile(
        r'<dep\b[^>]*\bfile="([^"]+)"[^>]*\burl="([^"]*)"',
        re.IGNORECASE
    )

    song_file = ''
    song_url = ''
    mod_name = ''
    mod_file = ''
    mod_url = ''

    for file_attr, url_attr in dep_re.findall(text):
        file_attr = html.unescape(file_attr or '').strip()
        url_attr = html.unescape(url_attr or '').strip()
        # Normalise to forward slashes so this works on both Linux and Windows servers
        norm = file_attr.replace('\\', '/').lower()

        if not song_file and norm.startswith('challengemusics/'):
            basename = pathlib.PureWindowsPath(file_attr).name
            song_file = pathlib.PureWindowsPath(basename).stem
            song_url = url_attr

        if not mod_file and '/mod/' in norm:
            basename = pathlib.PureWindowsPath(file_attr).name
            mod_file = basename
            mod_name = pathlib.PureWindowsPath(basename).stem
            mod_url = url_attr

    return {
        'song_file': song_file,
        'song_url': song_url,
        'mod_name': mod_name,
        'mod_file': mod_file,
        'mod_url': mod_url,
    }


async def _get_songmod(aseco: 'Aseco') -> dict[str, str]:
    """
    Prefer challenge.gbx runtime fields when present, but fall back to parsing the
    GBX file directly.
    """
    challenge = aseco.server.challenge
    gbx = getattr(challenge, 'gbx', None)

    song_file = _gbx_value(gbx, 'song_file', 'songFile') or ''
    song_url = _gbx_value(gbx, 'song_url', 'songUrl') or ''
    mod_name = _gbx_value(gbx, 'mod_name', 'modName') or ''
    mod_file = _gbx_value(gbx, 'mod_file', 'modFile') or ''
    mod_url = _gbx_value(gbx, 'mod_url', 'modUrl') or ''

    if song_file or mod_name:
        return {
            'song_file': str(song_file),
            'song_url': str(song_url),
            'mod_name': str(mod_name),
            'mod_file': str(mod_file),
            'mod_url': str(mod_url),
        }

    path = _challenge_abs_path(aseco)
    if path and path.exists():
        try:
            return await __import__('asyncio').to_thread(_parse_songmod_from_gbx, path)
        except Exception as e:
            logger.debug('[SongMod] GBX parse failed for %s: %s', path, e)

    return {
        'song_file': '',
        'song_url': '',
        'mod_name': '',
        'mod_file': '',
        'mod_url': '',
    }


async def chat_song(aseco: 'Aseco', command: dict):
    player = command['author']
    challenge = aseco.server.challenge
    info = await _get_songmod(aseco)

    if info['song_file']:
        msg = format_text(
            aseco.get_chat_message('SONG'),
            strip_colors(challenge.name),
            info['song_file'],
        )
        param = _first_param(command)
        if param in ('url', 'loc') and info['song_url']:
            msg += '\n{#highlite}$l[' + info['song_url'] + ']' + info['song_url'] + '$l'
    else:
        msg = '{#server}> {#error}No track song found!'
        if getattr(aseco.server, 'get_game', lambda: '')() == 'TMF' and _has_music_command(aseco):
            msg += '  Try {#highlite}$i /music current {#error}instead.'

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg),
        player.login,
    )


async def chat_mod(aseco: 'Aseco', command: dict):
    player = command['author']
    challenge = aseco.server.challenge
    info = await _get_songmod(aseco)

    if info['mod_name']:
        msg = format_text(
            aseco.get_chat_message('MOD'),
            strip_colors(challenge.name),
            info['mod_name'],
            info['mod_file'],
        )
        param = _first_param(command)
        if param in ('url', 'loc') and info['mod_url']:
            msg += '\n{#highlite}$l[' + info['mod_url'] + ']' + info['mod_url'] + '$l'
    else:
        msg = '{#server}> {#error}No track mod found!'

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg),
        player.login,
    )
