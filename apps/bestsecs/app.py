from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import widget
from .widget import BESTSECS_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "bestsecs",
    "display_name": "BestSecs",
    "description": "Best sectors widget.",
    "modules": [
        "apps/bestsecs/widget.py",
    ],
    "entries": [
        "app/bestsecs",
    ],
    "provides": [
        "feature/bestsecs",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class BestSecsApp(App):
    def __init__(self):
        super().__init__(
            app_id="bestsecs",
            display_name="BestSecs",
            description="Best sectors widget.",
            depends_on=("platform_core",),
            entry_modules=("app/bestsecs",),
            settings_schema=BESTSECS_SETTINGS_SCHEMA,
        )
        self.bestsecs_surfaces = (
            BestSecsModuleSurface(
                component_id="bestsecs.widget",
                description="Best sectors widget surface.",
                module=widget,
            ),
        )
        self.components = self.bestsecs_surfaces

    def register_runtime(self, aseco: "Aseco") -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class BestSecsModuleSurface(Component):
    def __init__(self, component_id: str, description: str, module):
        super().__init__(component_id=component_id, description=description)
        self.module = module

    def register(self, aseco: "Aseco") -> None:
        register = getattr(self.module, "register", None)
        if callable(register):
            register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(self.module, "startup", None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(self.module, "shutdown", None)
        if callable(shutdown):
            await shutdown(context)


APP_CLASS = BestSecsApp
APP_INSTANCE = BestSecsApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco: "Aseco") -> None:
    await widget.reload_bestsecs_runtime(aseco)
