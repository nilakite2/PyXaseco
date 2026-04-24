from __future__ import annotations

import asyncio
from pyxaseco.helpers import strip_colors, validate_utf8


def _clip(text: str, n: int) -> str:
    text = str(text or '')
    if n <= 0 or len(text) <= n:
        return text
    return text[:max(0, n - 1)] + '…'


def _sanitise_nick(nick: str) -> str:
    if not nick:
        return ''
    nick = validate_utf8(str(nick))
    nick = nick.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    return ' '.join(nick.split())


def _digest_entries(entries: list, login: str) -> str:
    """
    Fast content fingerprint to skip sending unchanged ManiaLinks.
    """
    key = str((login, [(e.get('rank'), e.get('login'), e.get('score'), e.get('self'))
                       for e in entries]))
    return str(hash(key))


def _loop_time() -> float:
    try:
        return asyncio.get_running_loop().time()
    except RuntimeError:
        import time
        return time.monotonic()


def _mode_name(mode: int) -> str:
    from pyxaseco.models import Gameinfo

    return {
        Gameinfo.RNDS: 'Rounds',
        Gameinfo.TA: 'Time Attack',
        Gameinfo.TEAM: 'Team',
        Gameinfo.LAPS: 'Laps',
        Gameinfo.STNT: 'Stunts',
        Gameinfo.CUP: 'Cup',
    }.get(mode, f'Unknown ({mode})')
