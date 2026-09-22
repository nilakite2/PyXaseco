from pyxaseco.core.base import Component

from .internal.state import (
    _clear_per_challenge_state,
    _init_player,
    _loop_time,
    _state,
    get_state,
)


class RecordsEyepieceModelSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.models',
            description='Shared Records Eyepiece runtime state and per-player challenge caches.',
        )


MODEL_SURFACE = RecordsEyepieceModelSurface()


def get_component() -> RecordsEyepieceModelSurface:
    return MODEL_SURFACE

__all__ = [
    '_state',
    'get_state',
    '_init_player',
    '_clear_per_challenge_state',
    '_loop_time',
    'RecordsEyepieceModelSurface',
    'MODEL_SURFACE',
    'get_component',
]
