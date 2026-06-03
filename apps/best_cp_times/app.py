from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import best_cp_times_v2
from .best_cp_times_v2 import BEST_CP_TIMES_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "best_cp_times",
    "display_name": "Best CP Times",
    "description": "Checkpoint time analytics and leaderboard features.",
    "modules": [
        "apps/best_cp_times/best_cp_times_v2.py",
    ],
    "entries": [
        "app/best_cp_times",
    ],
    "provides": [
        "feature/best_cp_times_v2",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class BestCpTimesApp(App):
    def __init__(self):
        super().__init__(
            app_id="best_cp_times",
            display_name="Best CP Times",
            description="Checkpoint time analytics and leaderboard features.",
            depends_on=("platform_core",),
            entry_modules=("app/best_cp_times",),
            settings_schema=BEST_CP_TIMES_SETTINGS_SCHEMA,
        )
        self.best_cp_times_surfaces = (
            BestCpTimesModuleSurface(
                component_id='best_cp_times.best_cp_times_v2',
                description='Checkpoint time analytics and leaderboard feature surface.',
                module=best_cp_times_v2,
            ),
        )
        self.components = self.best_cp_times_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class BestCpTimesModuleSurface(Component):
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


APP_CLASS = BestCpTimesApp
APP_INSTANCE = BestCpTimesApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco: "Aseco") -> None:
    await best_cp_times_v2.reload_best_cp_times_runtime(aseco)
