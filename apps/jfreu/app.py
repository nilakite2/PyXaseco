from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "jfreu",
    "display_name": "JFreu",
    "description": "JFreu gameplay and rights feature set.",
    "modules": [
        "apps/jfreu/feature.py",
    ],
    "entries": [
        "app/jfreu",
    ],
    "provides": [
        "feature/jfreu",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class JFreuApp(App):
    def __init__(self):
        super().__init__(
            app_id="jfreu",
            display_name="JFreu",
            description="JFreu gameplay and rights feature set.",
            depends_on=("platform_core",),
            entry_modules=("app/jfreu",),
        )
        self.jfreu_surfaces = (
            JFreuModuleSurface(
                component_id='jfreu.feature',
                description='JFreu gameplay and rights feature surface.',
                module=feature,
            ),
        )
        self.components = self.jfreu_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class JFreuModuleSurface(Component):
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


APP_CLASS = JFreuApp
APP_INSTANCE = JFreuApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
