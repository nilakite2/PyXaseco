from __future__ import annotations

import asyncio
import html
import re
from pyxaseco.helpers import validate_utf8


def _clip(text: str, n: int) -> str:
    text = str(text or '')
    if n <= 0 or len(text) <= n:
        return text
    return text[:max(0, n - 1)] + '…'


def _sanitise_nick(nick: str) -> str:
    if not nick:
        return ''
    nick = validate_utf8(str(nick))
    # TMF ManiaLink text handling is effectively BMP-only. XAseco's
    # validateUTF8String() drops unsupported 4+ byte UTF-8 sequences, so do
    # the same here to avoid whole rows failing to render on exotic nicknames.
    nick = ''.join(ch for ch in nick if ord(ch) <= 0xFFFF)
    nick = nick.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    return ' '.join(nick.split())


def _handle_special_chars(text: str) -> str:
    """
    TMF-safe nickname cleanup for widget text.

    This now follows the Trakman UI render path more closely:
      safeString(strip(nickname, false))

    In practice that means:
    - preserve colour codes
    - strip embedded H/L/P links
    - strip non-colour TM style toggles such as S/H/W/I/P/L/O/N/G/T/Z
    - keep literal $$ intact
    - drop unsupported 4-byte characters for TMF-safe ManiaLinks

    XML escaping is intentionally left to the caller.
    """
    text = validate_utf8(str(text or ''))
    # Mirror XAseco validateUTF8String(): TMF-safe subset only.
    text = ''.join(ch for ch in text if ord(ch) <= 0xFFFF)
    text = text.replace('$$', '\x00')

    # Trakman Utils.strip(str, false):
    # remove H/L/P links and non-colour formatting codes, while preserving
    # ordinary colour codes like $fff.
    text = re.sub(r'\$(L|H|P)\[.*?\](.*?)\$(L|H|P)', r'\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\$(L|H|P)\[.*?\](.*?)', r'\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\$(L|H|P)(.*?)', r'\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\$[SHWIPLONGTZ]', '', text, flags=re.IGNORECASE)

    text = text.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    text = ' '.join(text.split())
    return text.replace('\x00', '$$')


def _safe_ml_text(text: str) -> str:
    """
    TMF-safe text for ManiaLink XML attributes.
    Applies nickname sanitation and escapes double quotes as well.
    """
    return html.escape(_handle_special_chars(text), quote=True)


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
