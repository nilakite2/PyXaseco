"""RASP jukebox domain facade.

This module provides a stable app-level surface for jukebox state, TMX add,
history, xlist, and vote-to-add related interactions while the implementation
still lives in ``rasp_jukebox.py``.
"""

from __future__ import annotations

from . import rasp_jukebox as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'register',
    'get_jukebox',
    'choose_jukebox_next',
    'force_jukebox_next',
    'admin_add_tmx_track',
    'download_tmx_track',
    'jukebox',
    'jb_buffer',
    'jukebox_check',
    'tmxplaying',
    'tmxplayed',
    'chat_list',
    'chat_jukebox',
    'chat_autojuke',
    'chat_add',
    'chat_y',
    'chat_history',
    'chat_xlist',
]
