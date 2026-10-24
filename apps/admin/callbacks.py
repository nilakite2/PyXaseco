from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Callback, Component

from .command_router import _admin_player_connect, _admin_startup, _event_admin
from .matchsettings import answer as matchsettings_answer

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class AdminCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.callbacks',
            description='Admin callback event surface.',
            callbacks=(
                Callback('onPlayerManialinkPageAnswer', _event_admin),
                Callback('onPlayerManialinkPageAnswer', matchsettings_answer),
                Callback('onStartup', _admin_startup),
                Callback('onPlayerConnect', _admin_player_connect),
            ),
        )


CALLBACK_SURFACE = AdminCallbackSurface()


def get_component() -> AdminCallbackSurface:
    return CALLBACK_SURFACE


def register(aseco: 'Aseco'):
    """Register the active admin callback surface."""
    CALLBACK_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
]
