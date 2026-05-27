from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import voting
from .backend import VOTING_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "voting",
    "display_name": "Voting",
    "description": "Chat-based vote flows for replay, skip, moderation, and vote-to-add.",
    "modules": [
        "apps/voting/voting.py",
        "apps/voting/backend.py",
    ],
    "entries": [
        "app/voting",
    ],
    "provides": [
        "feature/rasp_votes",
    ],
    "depends_on": [
        "platform_core",
        "platform_ui",
        "players",
    ],
}


class VotingApp(App):
    def __init__(self):
        super().__init__(
            app_id="voting",
            display_name="Voting",
            description="Chat-based vote flows for replay, skip, moderation, and vote-to-add.",
            depends_on=("platform_core", "platform_ui", "players"),
            entry_modules=("app/voting",),
            settings_schema=VOTING_SETTINGS_SCHEMA,
        )
        self.command_surface = voting.get_command_component()
        self.callback_surface = voting.get_callback_component()
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


APP_CLASS = VotingApp
APP_INSTANCE = VotingApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
