from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import callbacks, commands, models, views
from .rasp import RASP_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "rasp",
    "display_name": "RASP",
    "description": "Gameplay flow, jukebox, votes, next-map flow, and rank flow.",
    "modules": [
        "apps/rasp/models.py",
        "apps/rasp/rankings.py",
        "apps/rasp/social.py",
        "apps/rasp/jukebox.py",
        "apps/rasp/voting.py",
        "apps/rasp/flow.py",
        "apps/rasp/commands.py",
        "apps/rasp/callbacks.py",
        "apps/rasp/views.py",
    ],
    "entries": [
        "app/rasp",
    ],
    "provides": [
        "feature/rasp",
        "feature/rasp_jukebox",
        "feature/rasp_chat",
        "feature/rasp_nextmap",
        "feature/rasp_nextrank",
        "feature/rasp_votes",
    ],
    "depends_on": [
        "platform_core",
        "tmx",
        "records_local",
    ],
}


class RaspApp(App):
    def __init__(self):
        super().__init__(
            app_id="rasp",
            display_name="RASP",
            description="Gameplay flow, jukebox, votes, next-map flow, and rank flow.",
            depends_on=("platform_core", "tmx", "records_local"),
            entry_modules=("app/rasp",),
            settings_schema=RASP_SETTINGS_SCHEMA,
        )
        self.command_surface = commands.get_component()
        self.callback_surface = callbacks.get_component()
        self.model_surface = models.get_component()
        self.view_surface = views.get_component()
        self.components = (
            self.model_surface,
            self.view_surface,
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


APP_CLASS = RaspApp
APP_INSTANCE = RaspApp()


def register(aseco: 'Aseco'):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
