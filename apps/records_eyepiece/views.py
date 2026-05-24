from __future__ import annotations

from pyxaseco.core.base import Component

from . import (
    helpwin,
    hud,
    hud_views,
    record_views,
    toplists,
)


class RecordsEyepieceViewSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.views',
            description='Composed Records Eyepiece view surface spanning HUD, race, score, toplists, and tracklist views.',
        )
        self.subcomponents = (
            hud.get_component(),
            hud_views.get_component(),
            record_views.get_component(),
            toplists.get_component(),
            helpwin.get_component(),
        )

    def register(self, aseco) -> None:
        for component in self.subcomponents:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.subcomponents:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.subcomponents):
            await component.shutdown(context)


VIEW_SURFACE = RecordsEyepieceViewSurface()


def get_component() -> RecordsEyepieceViewSurface:
    return VIEW_SURFACE


__all__ = [
    'hud',
    'toplists',
    'hud_views',
    'record_views',
    'helpwin',
    'RecordsEyepieceViewSurface',
    'VIEW_SURFACE',
    'get_component',
]
