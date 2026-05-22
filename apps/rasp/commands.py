from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .rasp_chat import register as _register_rasp_chat
from .jukebox import (
    chat_add,
    chat_autojuke,
    chat_history,
    chat_jukebox,
    chat_list,
    chat_xlist,
    chat_y,
    register as _register_rasp_jukebox,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class RaspCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.commands',
            description='RASP chat commands, jukebox, TMX add, and xlist surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_rasp_chat(aseco)
        _register_rasp_jukebox(aseco)


COMMAND_SURFACE = RaspCommandSurface()


def get_component() -> RaspCommandSurface:
    return COMMAND_SURFACE


def register(aseco: 'Aseco'):
    """Register the active RASP command/chat surface."""
    COMMAND_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
    'chat_list',
    'chat_jukebox',
    'chat_autojuke',
    'chat_add',
    'chat_y',
    'chat_history',
    'chat_xlist',
]
