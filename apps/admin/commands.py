from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .chat import (
    chat_admin,
    chat_listadmins,
    chat_listmasters,
    chat_listops,
    register as _register_admin_chat,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class AdminCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.commands',
            description='Admin chat commands and command metadata surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_admin_chat(aseco)


COMMAND_SURFACE = AdminCommandSurface()


def get_component() -> AdminCommandSurface:
    return COMMAND_SURFACE


def register(aseco: 'Aseco'):
    """Register the active admin command/chat surface."""
    COMMAND_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
    'chat_admin',
    'chat_listmasters',
    'chat_listadmins',
    'chat_listops',
]
