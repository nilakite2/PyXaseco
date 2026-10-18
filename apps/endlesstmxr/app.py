from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "endlesstmxr",
    "display_name": "Endless TMX Random",
    "description": "Skips to a random TMX map when someone beats the current map author time.",
    "modules": [
        "apps/endlesstmxr/service.py",
    ],
    "entries": [
        "app/endlesstmxr",
    ],
    "provides": [
        "feature/endlesstmxr",
    ],
    "depends_on": [
        "platform_core",
        "jukebox",
        "tmx",
    ],
}


class EndlessTmxrModuleSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='endlesstmxr.service',
            description='Author-time endless random TMX flow surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        service.register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(service, 'startup', None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(service, 'shutdown', None)
        if callable(shutdown):
            await shutdown(context)


class EndlessTmxrApp(App):
    def __init__(self):
        super().__init__(
            app_id="endlesstmxr",
            display_name="Endless TMX Random",
            description="Skips to a random TMX map when someone beats the current map author time.",
            depends_on=("platform_core", "jukebox", "tmx"),
            entry_modules=("app/endlesstmxr",),
        )
        self.components = (
            EndlessTmxrModuleSurface(),
        )

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = EndlessTmxrApp
APP_INSTANCE = EndlessTmxrApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco: "Aseco") -> None:
    await service.reload_runtime(aseco)
