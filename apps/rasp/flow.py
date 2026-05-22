"""RASP flow domain facade.

This module groups the next-map and next-rank flow surfaces behind one stable
app-level entry while their implementations remain in dedicated modules.
"""

from __future__ import annotations

from . import rasp_nextmap as _nextmap_impl
from . import rasp_nextrank as _nextrank_impl


def register(aseco) -> None:
    _nextmap_impl.register(aseco)
    _nextrank_impl.register(aseco)


def __getattr__(name: str):
    if hasattr(_nextmap_impl, name):
        return getattr(_nextmap_impl, name)
    return getattr(_nextrank_impl, name)


__all__ = [
    'register',
    'chat_nextmap',
    'chat_nextrank',
]
