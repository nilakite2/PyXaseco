"""Records Eyepiece score-state view facade."""

from __future__ import annotations

from .widgets import score_widgets as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    'draw_round_score',
    'hide_round_score',
    'draw_all_score_lists',
    'hide_all_score_lists',
    'build_local_records_for_score',
    'build_dedi_records_for_score',
]
