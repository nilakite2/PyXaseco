from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "player_stats",
    "display_name": "Player Stats",
    "description": "Player statistics and ranking summaries.",
    "modules": [
        "apps/player_stats/chat.py",
    ],
    "entries": [
        "app/player_stats",
    ],
    "provides": [
        "chat/stats",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class PlayerStatsApp(App):
    def __init__(self):
        super().__init__(
            app_id="player_stats",
            display_name="Player Stats",
            description="Player statistics and ranking summaries.",
            depends_on=("platform_core",),
            entry_modules=("app/player_stats",),
        )


APP_CLASS = PlayerStatsApp


def register(aseco: "Aseco"):
    chat.register(aseco)
