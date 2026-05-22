from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "mania_karma",
    "display_name": "ManiaKarma",
    "description": "Karma voting service and scoreboard integration.",
    "modules": [
        "apps/mania_karma/service.py",
    ],
    "entries": [
        "app/mania_karma",
    ],
    "provides": [
        "service/mania_karma",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class ManiaKarmaApp(App):
    def __init__(self):
        super().__init__(
            app_id="mania_karma",
            display_name="ManiaKarma",
            description="Karma voting service and scoreboard integration.",
            depends_on=("platform_core",),
            entry_modules=("app/mania_karma",),
        )


APP_CLASS = ManiaKarmaApp


def register(aseco: "Aseco"):
    service.register(aseco)
