from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import chat

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "track",
    "display_name": "Track",
    "description": "Track-side chat info such as song and mod details.",
    "modules": [
        "apps/track/chat.py",
    ],
    "entries": [
        "app/track",
    ],
    "provides": [
        "chat/songmod",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class TrackApp(App):
    def __init__(self):
        super().__init__(
            app_id="track",
            display_name="Track",
            description="Track-side chat info such as song and mod details.",
            depends_on=("platform_core",),
            entry_modules=("app/track",),
        )
        self.track_surfaces = (
            TrackModuleSurface(
                component_id='track.chat',
                description='Track-side chat info and song/mod lookup surface.',
                module=chat,
            ),
        )
        self.components = self.track_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class TrackModuleSurface(Component):
    def __init__(self, component_id: str, description: str, module):
        super().__init__(component_id=component_id, description=description)
        self.module = module

    def register(self, aseco: 'Aseco') -> None:
        register = getattr(self.module, 'register', None)
        if callable(register):
            register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(self.module, 'startup', None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(self.module, 'shutdown', None)
        if callable(shutdown):
            await shutdown(context)


APP_CLASS = TrackApp
APP_INSTANCE = TrackApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
