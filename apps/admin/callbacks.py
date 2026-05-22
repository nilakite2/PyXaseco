from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .bridge import (
    register as _register_admin_bridge,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class AdminCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.callbacks',
            description='Admin callback and bridge event surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_admin_bridge(aseco)


CALLBACK_SURFACE = AdminCallbackSurface()


def get_component() -> AdminCallbackSurface:
    return CALLBACK_SURFACE


def register(aseco: 'Aseco'):
    """Register the active admin callback/bridge surface."""
    CALLBACK_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
]
