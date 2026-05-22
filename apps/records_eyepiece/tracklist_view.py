"""Records Eyepiece tracklist facade."""

from __future__ import annotations

from . import tracklist as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = [
    '_send_tracklist_window',
    '_close_tracklist_window',
    '_build_tracklist_window',
    '_build_tracklist_filter_window',
    '_build_tracklist_sorting_window',
    '_send_trackauthorlist_window',
    '_build_trackauthorlist_window',
]
