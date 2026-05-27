from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import laston, nextrank, players, players2, rankings, stats, wins
from .ranking_backend import PLAYER_RANKING_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "players",
    "display_name": "Players",
    "description": "Player browsing, stats, rank lookup, wins, and last seen flows.",
    "modules": [
        "apps/players/players.py",
        "apps/players/players2.py",
        "apps/players/wins.py",
        "apps/players/laston.py",
        "apps/players/stats.py",
        "apps/players/rankings.py",
        "apps/players/nextrank.py",
        "apps/players/ranking_backend.py",
    ],
    "entries": [
        "app/players",
    ],
    "provides": [
        "chat/players",
        "chat/players2",
        "chat/wins",
        "chat/laston",
        "chat/stats",
        "chat/topdons",
        "feature/rasp",
        "feature/rasp_nextrank",
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
            description="Player browsing, stats, rank lookup, wins, and last seen flows.",
            depends_on=("platform_core",),
            entry_modules=("app/players",),
            settings_schema=PLAYER_RANKING_SETTINGS_SCHEMA,
        )
        self.player_surfaces = (
            PlayersModuleSurface(
                component_id='players.players',
                description='Online player listing and player list click handling surface.',
                module=players,
            ),
            PlayersModuleSurface(
                component_id='players.players2',
                description='Ranks, clans, and topclans surface.',
                module=players2,
            ),
            PlayersModuleSurface(
                component_id='players.wins',
                description='Player wins chat surface.',
                module=wins,
            ),
            PlayersModuleSurface(
                component_id='players.laston',
                description='Last online lookup surface.',
                module=laston,
            ),
            PlayersStatsSurface(
                component_id='players.stats',
                description='Player statistics and top-donators command surface.',
            ),
            rankings.get_command_component(),
            nextrank.get_command_component(),
            rankings.get_callback_component(),
        )
        self.components = self.player_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class PlayersModuleSurface(Component):
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


class PlayersStatsSurface(Component):
    def __init__(self, component_id: str, description: str):
        super().__init__(component_id=component_id, description=description)

    def register(self, aseco: 'Aseco') -> None:
        stats.register(aseco)


APP_CLASS = PlayersApp
APP_INSTANCE = PlayersApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
