from __future__ import annotations

from pyxaseco.core.base import Component

from . import ui as _impl


def append_window_start(*args, **kwargs):
    return _impl.append_window_start(*args, **kwargs)


def append_window_end(*args, **kwargs):
    return _impl.append_window_end(*args, **kwargs)


def append_four_player_columns(*args, **kwargs):
    return _impl.append_four_player_columns(*args, **kwargs)


class RecordsEyepieceHudSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.hud',
            description='Shared HUD shell builders for Records Eyepiece windows and columns.',
        )


HUD_SURFACE = RecordsEyepieceHudSurface()


def get_component() -> RecordsEyepieceHudSurface:
    return HUD_SURFACE


__all__ = [
    'append_window_start',
    'append_window_end',
    'append_four_player_columns',
    'RecordsEyepieceHudSurface',
    'HUD_SURFACE',
    'get_component',
]
