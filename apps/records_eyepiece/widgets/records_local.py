"""Thin widget entry point for the Local Records app records widget."""

from apps.records_local.records_widget import (
    ML_LOCAL,
    ML_SUBWIN,
    ML_WINDOW,
    _build_local_records_window,
    _draw_local_player,
)

__all__ = [
    "ML_LOCAL",
    "ML_SUBWIN",
    "ML_WINDOW",
    "_build_local_records_window",
    "_draw_local_player",
]
