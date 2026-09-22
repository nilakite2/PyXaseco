from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import commands, service
from .service import DEDI_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "records_dedimania",
    "display_name": "Records Dedimania",
    "description": "Dedimania records service, chat flows, and related records widget ownership.",
    "modules": [
        "apps/records_dedimania/service.py",
        "apps/records_dedimania/commands.py",
        "apps/records_dedimania/records_widget.py",
    ],
    "entries": [
        "app/records_dedimania",
    ],
    "provides": [
        "app/dedimania",
        "service/records_dedimania",
        "service/dedimania",
        "chat/dedimania",
    ],
    "depends_on": [
        "platform_core",
        "ui",
    ],
}


class DedimaniaApp(App):
    def __init__(self):
        super().__init__(
            app_id="records_dedimania",
            display_name="Records Dedimania",
            description="Dedimania records service, chat flows, and related records widget ownership.",
            depends_on=("platform_core", "ui"),
            entry_modules=("app/records_dedimania",),
            settings_schema=DEDI_SETTINGS_SCHEMA,
        )
        self.dedimania_surfaces = (
            DedimaniaModuleSurface(
                component_id='records_dedimania.service',
                description='Dedimania service integration and record synchronization surface.',
                module=service,
            ),
            DedimaniaModuleSurface(
                component_id='records_dedimania.commands',
                description='Dedimania command surface.',
                module=commands,
            ),
        )
        self.components = self.dedimania_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class DedimaniaModuleSurface(Component):
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


APP_CLASS = DedimaniaApp
APP_INSTANCE = DedimaniaApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
