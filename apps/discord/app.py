from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import bridge, service
from .service import DISCORD_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "discord",
    "display_name": "Discord",
    "description": "Discord integrations.",
    "modules": [
        "apps/discord/service.py",
        "apps/discord/bridge.py",
    ],
    "entries": [
        "app/discord",
    ],
    "provides": [
        "service/discord_webhook",
        "bridge/discord",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class DiscordApp(App):
    def __init__(self):
        super().__init__(
            app_id="discord",
            display_name="Discord",
            description="Discord integrations.",
            depends_on=("platform_core",),
            entry_modules=("app/discord",),
            settings_schema=DISCORD_SETTINGS_SCHEMA,
        )
        self.discord_surfaces = (
            DiscordModuleSurface(
                component_id='discord.service',
                description='Discord webhook service surface.',
                module=service,
            ),
            DiscordModuleSurface(
                component_id='discord.bridge',
                description='Discord bridge surface.',
                module=bridge,
            ),
        )
        self.components = self.discord_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class DiscordModuleSurface(Component):
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


APP_CLASS = DiscordApp
APP_INSTANCE = DiscordApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
