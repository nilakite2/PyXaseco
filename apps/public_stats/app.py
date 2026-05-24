from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import bridge

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "public_stats",
    "display_name": "Public Stats",
    "description": "External public statistics publishing.",
    "modules": [
        "apps/public_stats/bridge.py",
    ],
    "entries": [
        "app/public_stats",
    ],
    "provides": [
        "bridge/public_stats",
    ],
}


class PublicStatsApp(App):
    def __init__(self):
        super().__init__(
            app_id="public_stats",
            display_name="Public Stats",
            description="External public statistics publishing.",
            entry_modules=("app/public_stats",),
        )
        self.public_stats_surfaces = (
            PublicStatsModuleSurface(
                component_id='public_stats.bridge',
                description='External public statistics bridge surface.',
                module=bridge,
            ),
        )
        self.components = self.public_stats_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class PublicStatsModuleSurface(Component):
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


APP_CLASS = PublicStatsApp
APP_INSTANCE = PublicStatsApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
