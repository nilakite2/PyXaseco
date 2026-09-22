from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import commands, public_stats, uptodate

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "server_info",
    "display_name": "Server Info",
    "description": "Server information, runtime introspection, and update-check commands.",
    "modules": [
        "apps/server_info/commands.py",
        "apps/server_info/public_stats.py",
        "apps/server_info/uptodate.py",
    ],
    "entries": [
        "app/server_info",
    ],
    "provides": [
        "chat/server",
        "app/public_stats",
        "bridge/public_stats",
        "core/uptodate",
    ],
}


class ServerInfoApp(App):
    def __init__(self):
        super().__init__(
            app_id="server_info",
            display_name="Server Info",
            description="Server information, runtime introspection, and update-check commands.",
            entry_modules=("app/server_info",),
        )
        self.server_info_surfaces = (
            ServerInfoModuleSurface(
                component_id='server_info.commands',
                description='Server information and runtime introspection chat surface.',
                module=commands,
            ),
            ServerInfoModuleSurface(
                component_id='server_info.uptodate',
                description='Version check and update notice surface.',
                module=uptodate,
            ),
            ServerInfoModuleSurface(
                component_id='server_info.public_stats',
                description='External public statistics publishing surface.',
                module=public_stats,
            ),
        )
        self.components = self.server_info_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class ServerInfoModuleSurface(Component):
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


APP_CLASS = ServerInfoApp
APP_INSTANCE = ServerInfoApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
