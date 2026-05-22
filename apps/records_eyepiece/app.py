from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import callbacks, commands
from .config import _state, _load_config

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "records_eyepiece",
    "display_name": "Records Eyepiece",
    "description": "Base records HUD framework, shared widget shell, and records UI orchestration.",
    "modules": [
        "apps/records_eyepiece/models.py",
        "apps/records_eyepiece/hud.py",
        "apps/records_eyepiece/race_view.py",
        "apps/records_eyepiece/score_view.py",
        "apps/records_eyepiece/toplists_view.py",
        "apps/records_eyepiece/tracklist_view.py",
        "apps/records_eyepiece/views.py",
        "apps/records_eyepiece/callbacks.py",
    ],
    "entries": [
        "app/records_eyepiece",
    ],
    "provides": [
        "ui/records_eyepiece/app",
    ],
}


class RecordsEyepieceApp(App):
    def __init__(self):
        super().__init__(
            app_id="records_eyepiece",
            display_name="Records Eyepiece",
            description="Base records HUD framework, shared widget shell, and records UI orchestration.",
            entry_modules=("app/records_eyepiece",),
        )
        self.command_surface = commands.get_component()
        self.callback_surface = callbacks.get_component()
        self.components = (
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


APP_CLASS = RecordsEyepieceApp
APP_INSTANCE = RecordsEyepieceApp()


def register(aseco: 'Aseco'):
    APP_INSTANCE.register_runtime(aseco)


def get_state():
    return _state


def reload_config(aseco: 'Aseco') -> None:
    _load_config(aseco)
