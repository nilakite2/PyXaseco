"""RASP flow domain facade.

This module groups the next-map and next-rank flow surfaces behind one stable
app-level entry while their implementations remain in dedicated modules.
"""

from __future__ import annotations

from pyxaseco.core.base import Component

from . import rasp_nextmap as _nextmap_impl
from . import rasp_nextrank as _nextrank_impl


def register_commands(aseco) -> None:
    aseco.add_chat_command('nextmap', 'Shows name of the next challenge')
    aseco.register_event('onChat_nextmap', _nextmap_impl.chat_nextmap)
    aseco.add_chat_command('nextrank', 'Shows the next better ranked player')
    aseco.register_event('onChat_nextrank', _nextrank_impl.chat_nextrank)


def register(aseco) -> None:
    register_commands(aseco)


def __getattr__(name: str):
    if hasattr(_nextmap_impl, name):
        return getattr(_nextmap_impl, name)
    return getattr(_nextrank_impl, name)


class RaspFlowCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.flow.commands',
            description='RASP next-map and next-rank gameplay flow command surface.',
        )

    def register(self, aseco) -> None:
        register_commands(aseco)


FLOW_COMMAND_SURFACE = RaspFlowCommandSurface()


def get_command_component() -> RaspFlowCommandSurface:
    return FLOW_COMMAND_SURFACE


def get_component():
    return FLOW_COMMAND_SURFACE


__all__ = [
    'register',
    'register_commands',
    'RaspFlowCommandSurface',
    'FLOW_COMMAND_SURFACE',
    'get_component',
    'get_command_component',
    'chat_nextmap',
    'chat_nextrank',
]
