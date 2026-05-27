from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "records_rpg",
    "display_name": "RPG Records",
    "description": "RPG API-backed records service and related records widget ownership.",
    "modules": [
        "apps/records_rpg/service.py",
        "apps/records_rpg/views.py",
    ],
    "entries": [
        "app/records_rpg",
    ],
    "provides": [
        "service/records_rpg",
    ],
    "depends_on": [
        "platform_core",
        "ui",
    ],
}


class RecordsRpgApp(App):
    def __init__(self):
        super().__init__(
            app_id="records_rpg",
            display_name="RPG Records",
            description="RPG API-backed records service and related records widget ownership.",
            depends_on=("platform_core", "ui"),
            entry_modules=("app/records_rpg",),
        )


APP_CLASS = RecordsRpgApp


def register(aseco: "Aseco"):
    service.register(aseco)
