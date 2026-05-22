"""RASP voting domain facade.

This module provides a stable app-level surface for vote state and callbacks
while the implementation still lives in ``rasp_votes.py``.
"""

from __future__ import annotations

from . import rasp_votes as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'register',
    'chatvote',
    'tmxadd',
    'plrvotes',
    'chat_helpvote',
    'chat_endround',
    'chat_ladder',
    'chat_replay',
    'chat_skip',
    'chat_ignore',
    'chat_kick',
    'chat_cancel',
]
