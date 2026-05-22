"""RASP shared app state surface.

The long-term goal is to move app-owned state behind explicit models. For now,
this module provides one stable place for active apps to reach the RASP state
they are allowed to share, without importing the old monolith module names.
"""

from __future__ import annotations

from . import jukebox as _jukebox
from . import rankings as _rankings
from . import voting as _voting


def __getattr__(name: str):
    for module in (_rankings, _jukebox, _voting):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


__all__ = [
    '_rasp',
    '_rasp_messages',
    '_challenge_list_cache',
    'jukebox',
    'jb_buffer',
    'chatvote',
    'tmxadd',
    'plrvotes',
]
