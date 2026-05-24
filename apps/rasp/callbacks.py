from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .jukebox import get_callback_component as _get_jukebox_callback_component
from .rankings import get_callback_component as _get_ranking_callback_component
from .voting import get_callback_component as _get_voting_callback_component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class RaspCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.callbacks',
            description='RASP ranking, vote, next-map, and next-rank event surface.',
        )
        self.subcomponents = (
            _get_ranking_callback_component(),
            _get_jukebox_callback_component(),
            _get_voting_callback_component(),
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


CALLBACK_SURFACE = RaspCallbackSurface()


def get_component() -> RaspCallbackSurface:
    return CALLBACK_SURFACE


def register(aseco: 'Aseco'):
    """Register the active RASP callback/event surface."""
    CALLBACK_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
]
