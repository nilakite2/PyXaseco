"""Stable window interface for apps that do not depend on Eyepiece."""

from pyxaseco.helpers import (
    ML_ID_MAIN,
    _player_window_style as player_window_style,
    _s as style_value,
    _send_multipage as send_page,
)

__all__ = ['ML_ID_MAIN', 'player_window_style', 'style_value', 'send_page']
