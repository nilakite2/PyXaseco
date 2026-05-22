from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import laston, players, players2, wins

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "players",
    "display_name": "Players",
    "description": "Player browsing, rank lookup, wins, and last seen flows.",
    "modules": [
        "apps/players/players.py",
        "apps/players/players2.py",
        "apps/players/wins.py",
        "apps/players/laston.py",
    ],
    "entries": [
        "app/players",
    ],
    "provides": [
        "chat/players",
        "chat/players2",
        "chat/wins",
        "chat/laston",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class PlayersApp(App):
    def __init__(self):
        super().__init__(
            app_id="players",
            display_name="Players",
            description="Player browsing, rank lookup, wins, and last seen flows.",
            depends_on=("platform_core",),
            entry_modules=("app/players",),
        )


APP_CLASS = PlayersApp


def register(aseco: "Aseco"):
    players.register(aseco)
    players2.register(aseco)
    wins.register(aseco)
    laston.register(aseco)
