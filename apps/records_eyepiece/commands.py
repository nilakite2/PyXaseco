from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Command, Component

from .handlers.chat import (
    _elist_redirect,
    chat_estat,
    chat_eyepiece,
    chat_eyeset,
    chat_togglewidgets,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class RecordsEyepieceCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.commands',
            description='Records Eyepiece chat commands and HUD user actions.',
            commands=(
                Command('togglewidgets', 'Toggle the display of the Records-Eyepiece widgets', chat_togglewidgets),
                Command('eyepiece', 'Displays help for the Records-Eyepiece widgets', chat_eyepiece),
                Command('elist', 'Lists tracks currently on the server', _elist_redirect),
                Command('estat', 'Display one of the MoreRankingLists', chat_estat),
                Command('eyeset', 'Adjust Records-Eyepiece settings', chat_eyeset, is_admin=True),
            ),
        )

    def register(self, aseco: 'Aseco') -> None:
        super().register(aseco)


COMMAND_SURFACE = RecordsEyepieceCommandSurface()


def get_component() -> RecordsEyepieceCommandSurface:
    return COMMAND_SURFACE


def register(aseco: 'Aseco'):
    """Register the active Records Eyepiece chat/command surface."""
    COMMAND_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
    'chat_togglewidgets',
    'chat_eyepiece',
    '_elist_redirect',
    'chat_estat',
    'chat_eyeset',
]
