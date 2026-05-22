from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import bridge

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "public_stats",
    "display_name": "Public Stats",
    "description": "External public statistics publishing.",
    "modules": [
        "apps/public_stats/bridge.py",
    ],
    "entries": [
        "app/public_stats",
    ],
    "provides": [
        "bridge/public_stats",
    ],
}


class PublicStatsApp(App):
    def __init__(self):
        super().__init__(
            app_id="public_stats",
            display_name="Public Stats",
            description="External public statistics publishing.",
            entry_modules=("app/public_stats",),
        )


APP_CLASS = PublicStatsApp


def register(aseco: "Aseco"):
    bridge.register(aseco)
