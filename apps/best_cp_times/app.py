from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import best_cp_times_v2

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
        )


APP_CLASS = BestCpTimesApp


def register(aseco: "Aseco"):
    best_cp_times_v2.register(aseco)
