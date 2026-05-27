from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import jukebox

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "jukebox",
    "display_name": "Jukebox",
    "description": "Track queue, history, TMX add, list browsing, and autojuke flows.",
    "modules": [
        "apps/jukebox/jukebox.py",
        "apps/jukebox/backend.py",
    ],
    "entries": [
        "app/jukebox",
    ],
    "provides": [
        "feature/rasp_jukebox",
    ],
    "depends_on": [
        "platform_core",
        "players",
        "records_local",
        "tmx",
    ],
}


class JukeboxApp(App):
    def __init__(self):
        super().__init__(
            app_id="jukebox",
            display_name="Jukebox",
            description="Track queue, history, TMX add, list browsing, and autojuke flows.",
            depends_on=("platform_core", "players", "records_local", "tmx"),
            entry_modules=("app/jukebox",),
        )
        self.command_surface = jukebox.get_command_component()
        self.callback_surface = jukebox.get_callback_component()
        self.components = (
            self.command_surface,
            self.callback_surface,
        )

    def register_runtime(self, aseco: "Aseco") -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = JukeboxApp
APP_INSTANCE = JukeboxApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
