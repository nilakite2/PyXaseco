"""RASP shared player-facing surfaces.

RASP does not yet have a fully normalized view layer, but the player-visible
jukebox and vote interactions now have stable app-level facades here.
"""

from pyxaseco.core.base import Component

from . import flow, jukebox, voting

__all__ = [
    'jukebox',
    'voting',
    'flow',
]


class RaspViewSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.views',
            description='Composed RASP player-facing view and interaction surface.',
        )
        self.subcomponents = (
            jukebox.get_component(),
            voting.get_component(),
            flow.get_component(),
        )

    def register(self, aseco) -> None:
        return None

    async def startup(self, context) -> None:
        for component in self.subcomponents:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.subcomponents):
            await component.shutdown(context)


VIEW_SURFACE = RaspViewSurface()


def get_component() -> RaspViewSurface:
    return VIEW_SURFACE
