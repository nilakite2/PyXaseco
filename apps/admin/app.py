from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import callbacks, commands

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "admin",
    "display_name": "Admin",
    "description": "Admin commands, moderation, map control, and server management.",
    "modules": [
        "apps/admin/command_router.py",
        "apps/admin/server.py",
        "apps/admin/map.py",
        "apps/admin/player.py",
        "apps/admin/lists.py",
        "apps/admin/commands.py",
        "apps/admin/callbacks.py",
    ],
    "entries": [
        "app/admin",
    ],
    "provides": [
        "chat/admin",
        "bridge/server_admin_bridge",
    ],
    "depends_on": [
        "platform_core",
        "tmx",
        "jukebox",
        "voting",
        "records_local",
    ],
}


class AdminApp(App):
    def __init__(self):
        super().__init__(
            app_id="admin",
            display_name="Admin",
            description="Admin commands, moderation, map control, and server management.",
            depends_on=("platform_core", "tmx", "jukebox", "voting", "records_local"),
            entry_modules=("app/admin",),
        )
        self.domain_components = commands.get_domain_components()
        self.command_surface = commands.get_component()
        self.callback_surface = callbacks.get_component()
        self.components = self.domain_components + (
            self.command_surface,
            self.callback_surface,
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


APP_CLASS = AdminApp
APP_INSTANCE = AdminApp()


def register(aseco: 'Aseco'):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
