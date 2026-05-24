from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import service
from .service import MANIA_KARMA_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "mania_karma",
    "display_name": "ManiaKarma",
    "description": "Karma voting service and scoreboard integration.",
    "modules": [
        "apps/mania_karma/service.py",
    ],
    "entries": [
        "app/mania_karma",
    ],
    "provides": [
        "service/mania_karma",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class ManiaKarmaApp(App):
    def __init__(self):
        super().__init__(
            app_id="mania_karma",
            display_name="ManiaKarma",
            description="Karma voting service and scoreboard integration.",
            depends_on=("platform_core",),
            entry_modules=("app/mania_karma",),
            settings_schema=MANIA_KARMA_SETTINGS_SCHEMA,
        )
        self.mania_karma_surfaces = (
            ManiaKarmaModuleSurface(
                component_id='mania_karma.service',
                description='Karma voting and scoreboard service surface.',
                module=service,
            ),
        )
        self.components = self.mania_karma_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class ManiaKarmaModuleSurface(Component):
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


APP_CLASS = ManiaKarmaApp
APP_INSTANCE = ManiaKarmaApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
