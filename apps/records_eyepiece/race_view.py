"""Records Eyepiece race-state view facade."""

from __future__ import annotations

from . import challenge_widget as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'draw_main_widget',
    'hide_main_widget',
]
