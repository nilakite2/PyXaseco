"""Records Eyepiece HUD shell facade."""

from __future__ import annotations

from . import ui as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'append_window_start',
    'append_window_end',
    'append_four_player_columns',
]
