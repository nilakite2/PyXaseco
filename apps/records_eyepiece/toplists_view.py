"""Records Eyepiece toplist and score-column facade."""

from __future__ import annotations

from . import toplists as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'draw_all_score_columns',
    'hide_all_score_columns',
]
