from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Command, Component

from . import lists, map, player, server
from .command_router import (
    chat_admin,
    chat_listadmins,
    chat_listmasters,
    chat_listops,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class AdminCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.commands',
            description='Admin chat commands and command metadata surface.',
            commands=(
                Command(
                    name='admin',
                    help_text='Provides admin commands (see: /admin help)',
                    handler=chat_admin,
                    is_admin=True,
                    owner='chat/admin',
                    aliases=('ad', 'a', '/'),
                    usage='/admin <subcommand>',
                    display_name='admin',
                    category='admin-entry',
                    order=0,
                ),
                Command(
                    name='listmasters',
                    help_text='Displays current masteradmin list',
                    handler=chat_listmasters,
                    is_admin=True,
                    owner='chat/admin',
                    usage='/listmasters',
                    display_name='listmasters',
                    category='admin-public',
                    public=True,
                    permission='listmasters',
                    role='public',
                    order=5,
                ),
                Command(
                    name='listadmins',
                    help_text='Displays current admin list',
                    handler=chat_listadmins,
                    is_admin=True,
                    owner='chat/admin',
                    usage='/listadmins',
                    display_name='listadmins',
                    category='admin-public',
                    public=True,
                    permission='listadmins',
                    role='public',
                    order=6,
                ),
                Command(
                    name='listops',
                    help_text='Displays current operator list',
                    handler=chat_listops,
                    is_admin=True,
                    owner='chat/admin',
                    usage='/listops',
                    display_name='listops',
                    category='admin-public',
                    public=True,
                    permission='listops',
                    role='public',
                    order=7,
                ),
            ),
        )

    def register(self, aseco: 'Aseco') -> None:
        super().register(aseco)


COMMAND_SURFACE = AdminCommandSurface()
DOMAIN_COMPONENTS = (
    server.get_component(),
    map.get_component(),
    player.get_component(),
    lists.get_component(),
)


def get_component() -> AdminCommandSurface:
    return COMMAND_SURFACE


def get_domain_components() -> tuple[Component, ...]:
    return DOMAIN_COMPONENTS


def register(aseco: 'Aseco'):
    """Register the active admin command/chat surface."""
    COMMAND_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
    'get_domain_components',
    'chat_admin',
    'chat_listmasters',
    'chat_listadmins',
    'chat_listops',
]
