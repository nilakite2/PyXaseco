from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import feature
from .feature import BESTFINISHES_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "bestfinishes",
    "display_name": "Best Finishes",
    "description": "Finish-time comparison features.",
    "modules": [
        "apps/bestfinishes/feature.py",
    ],
    "entries": [
        "app/bestfinishes",
    ],
    "provides": [
        "feature/bestfinishes",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class BestFinishesApp(App):
    def __init__(self):
        super().__init__(
            app_id="bestfinishes",
            display_name="Best Finishes",
            description="Finish-time comparison features.",
            depends_on=("platform_core",),
            entry_modules=("app/bestfinishes",),
            settings_schema=BESTFINISHES_SETTINGS_SCHEMA,
        )
        self.bestfinishes_surfaces = (
            BestFinishesModuleSurface(
                component_id='bestfinishes.feature',
                description='Finish-time comparison feature surface.',
                module=feature,
            ),
        )
        self.components = self.bestfinishes_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class BestFinishesModuleSurface(Component):
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


APP_CLASS = BestFinishesApp
APP_INSTANCE = BestFinishesApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
