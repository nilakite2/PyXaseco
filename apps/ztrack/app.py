from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "ztrack",
    "display_name": "ZTrack",
    "description": "ZTrack helper and map integration feature.",
    "modules": [
        "apps/ztrack/feature.py",
    ],
    "entries": [
        "app/ztrack",
    ],
    "provides": [
        "feature/ztrack",
    ],
    "depends_on": [
        "platform_core",
        "tmx",
    ],
}


class ZTrackApp(App):
    def __init__(self):
        super().__init__(
            app_id="ztrack",
            display_name="ZTrack",
            description="ZTrack helper and map integration feature.",
            depends_on=("platform_core", "tmx"),
            entry_modules=("app/ztrack",),
        )
        self.ztrack_surfaces = (
            ZTrackModuleSurface(
                component_id='ztrack.feature',
                description='ZTrack helper and map integration feature surface.',
                module=feature,
            ),
        )
        self.components = self.ztrack_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class ZTrackModuleSurface(Component):
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


APP_CLASS = ZTrackApp
APP_INSTANCE = ZTrackApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
