"""Thin widget entry point for the Dedimania app records widget."""

from ..record_views import (
    ML_DEDI,
    ML_SUBWIN,
    ML_WINDOW,
    _build_dedi_records_window,
    _draw_dedi_player,
    _get_dedi_records,
)
from .records_common import _dedi_close_to_you, _digest_entries

__all__ = [
    "ML_DEDI",
    "ML_SUBWIN",
    "ML_WINDOW",
    "_build_dedi_records_window",
    "_dedi_close_to_you",
    "_digest_entries",
    "_draw_dedi_player",
    "_get_dedi_records",
]
