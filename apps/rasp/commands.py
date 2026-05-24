from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .flow import get_command_component as _get_flow_command_component
from .jukebox import (
    chat_add,
    chat_autojuke,
    chat_history,
    chat_jukebox,
    chat_list,
    chat_xlist,
    chat_y,
)
from .jukebox import get_command_component as _get_jukebox_command_component
from .rankings import get_command_component as _get_ranking_command_component
from .social import get_component as _get_social_component
from .voting import get_command_component as _get_voting_command_component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class RaspCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.commands',
            description='RASP chat commands, jukebox, TMX add, and xlist surface.',
        )
        self.subcomponents = (
            _get_ranking_command_component(),
            _get_social_component(),
            _get_jukebox_command_component(),
            _get_voting_command_component(),
            _get_flow_command_component(),
        )

    def register(self, aseco: 'Aseco') -> None:
        for component in self.subcomponents:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.subcomponents:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.subcomponents):
            await component.shutdown(context)


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
