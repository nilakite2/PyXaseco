"""RASP ranking domain facade.

This module provides a stable app-level surface for ranking state, commands,
and callbacks while the implementation still lives in ``rasp.py``.
"""

from __future__ import annotations

from . import rasp as _impl


def get_runtime_state() -> dict:
    return getattr(_impl, '_rasp', {})


def get_messages() -> dict:
    return getattr(_impl, '_rasp_messages', {})


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'register',
    'get_runtime_state',
    'get_messages',
    '_rasp',
    '_rasp_messages',
    '_challenge_list_cache',
    'feature_ranks',
    'feature_votes',
    'maxrecs',
    'chat_pb',
    'chat_rank',
    'chat_top10',
    'chat_top100',
    'chat_topwins',
    'chat_active',
]
