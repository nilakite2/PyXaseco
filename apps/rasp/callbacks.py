from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .flow import register as _register_rasp_flow
from .rankings import register as _register_rasp_core
from .voting import register as _register_rasp_votes

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class RaspCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.callbacks',
            description='RASP ranking, vote, next-map, and next-rank event surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_rasp_core(aseco)
        _register_rasp_flow(aseco)
        _register_rasp_votes(aseco)


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
