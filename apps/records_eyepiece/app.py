from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import callbacks, commands, models, views
from .config import _state, _load_config

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "records_eyepiece",
    "display_name": "Records Eyepiece",
    "description": "Base records HUD framework, shared widget shell, and records UI orchestration.",
    "modules": [
        "apps/records_eyepiece/config.py",
        "apps/records_eyepiece/models.py",
        "apps/records_eyepiece/challenge_widget.py",
        "apps/records_eyepiece/hud.py",
        "apps/records_eyepiece/helpwin.py",
        "apps/records_eyepiece/toplists.py",
        "apps/records_eyepiece/tracklist.py",
        "apps/records_eyepiece/hud_views.py",
        "apps/records_eyepiece/record_views.py",
        "apps/records_eyepiece/views.py",
        "apps/records_eyepiece/internal/helpers.py",
        "apps/records_eyepiece/internal/state.py",
        "apps/records_eyepiece/internal/toml_loader.py",
        "apps/records_eyepiece/internal/utils.py",
        "apps/records_eyepiece/handlers/actions.py",
        "apps/records_eyepiece/handlers/chat.py",
        "apps/records_eyepiece/handlers/events.py",
        "apps/records_eyepiece/callbacks.py",
        "apps/records_eyepiece/commands.py",
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


APP_CLASS = RecordsEyepieceApp
APP_INSTANCE = RecordsEyepieceApp()


def register(aseco: 'Aseco'):
    APP_INSTANCE.register_runtime(aseco)


def get_state():
    return _state


def reload_config(aseco: 'Aseco') -> None:
    _load_config(aseco)
