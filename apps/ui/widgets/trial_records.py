"""Thin widget entry point for the Trial Records app records widget."""

from apps.records_trial.records_widget import (
    ML_DEDI,
    ML_SUBWIN,
    ML_WINDOW,
    _build_trial_records_window,
    _draw_trial_player,
    _get_trial_records,
    _get_trial_track,
    _is_trial_track_active,
    _trial_title,
)

__all__ = [
    "ML_DEDI",
    "ML_SUBWIN",
    "ML_WINDOW",
    "_build_trial_records_window",
    "_draw_trial_player",
    "_get_trial_records",
    "_get_trial_track",
    "_is_trial_track_active",
    "_trial_title",
]
