from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "tmxvideo",
    "display_name": "TMX Video",
    "description": "TMX video lookup feature.",
    "modules": [
        "apps/tmxvideo/feature.py",
    ],
    "entries": [
        "app/tmxvideo",
    ],
    "provides": [
        "feature/tmxvideo",
    ],
    "depends_on": [
        "tmx",
    ],
}


class TmxVideoApp(App):
    def __init__(self):
        super().__init__(
            app_id="tmxvideo",
            display_name="TMX Video",
            description="TMX video lookup feature.",
            depends_on=("tmx",),
            entry_modules=("app/tmxvideo",),
        )
        self.tmxvideo_surfaces = (
            TmxVideoModuleSurface(
                component_id='tmxvideo.feature',
                description='TMX video lookup feature surface.',
                module=feature,
            ),
        )
        self.components = self.tmxvideo_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class TmxVideoModuleSurface(Component):
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


APP_CLASS = TmxVideoApp
APP_INSTANCE = TmxVideoApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
