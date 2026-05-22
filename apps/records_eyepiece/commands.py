from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

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
        )

    def register(self, aseco: 'Aseco') -> None:
        aseco.add_chat_command('togglewidgets', 'Toggle the display of the Records-Eyepiece widgets')
        aseco.add_chat_command('eyepiece',      'Displays help for the Records-Eyepiece widgets')
        aseco.add_chat_command('elist',         'Lists tracks currently on the server')
        aseco.add_chat_command('estat',         'Display one of the MoreRankingLists')
        aseco.add_chat_command('eyeset',        'Adjust Records-Eyepiece settings', True)

        aseco.register_event('onChat_togglewidgets', chat_togglewidgets)
        aseco.register_event('onChat_eyepiece',      chat_eyepiece)
        aseco.register_event('onChat_elist',         _elist_redirect)
        aseco.register_event('onChat_estat',         chat_estat)
        aseco.register_event('onChat_eyeset',        chat_eyeset)


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
