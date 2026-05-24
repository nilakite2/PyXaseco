"""RASP shared app state surface.

The long-term goal is to move app-owned state behind explicit models. For now,
this module provides one stable place for active apps to reach the RASP state
they are allowed to share, without importing the old monolith module names.
"""

from __future__ import annotations

from pyxaseco.core.base import Component

from . import jukebox as _jukebox
from . import rankings as _rankings
from . import voting as _voting


def __getattr__(name: str):
    for module in (_rankings, _jukebox, _voting):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


class RaspModelSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.models',
            description='Composed RASP shared runtime state across rankings, jukebox, and voting.',
        )
        self.subcomponents = (
            _rankings.get_component(),
            _jukebox.get_component(),
            _voting.get_component(),
        )

    def register(self, aseco) -> None:
        return None

    async def startup(self, context) -> None:
        for component in self.subcomponents:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.subcomponents):
            await component.shutdown(context)


MODEL_SURFACE = RaspModelSurface()


def get_component() -> RaspModelSurface:
    return MODEL_SURFACE


__all__ = [
    'RaspModelSurface',
    'MODEL_SURFACE',
    'get_component',
    '_rasp',
    '_rasp_messages',
    '_challenge_list_cache',
    'jukebox',
    'jb_buffer',
    'chatvote',
    'tmxadd',
    'plrvotes',
]
