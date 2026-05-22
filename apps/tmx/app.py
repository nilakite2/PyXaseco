from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "tmx",
    "display_name": "TMX",
    "description": "TMX metadata service and tracklist ownership.",
    "modules": [
        "apps/tmx/service.py",
        "apps/tmx/tracklist.py",
    ],
    "entries": [
        "app/tmx",
    ],
    "provides": [
        "service/tmx",
    ],
    "depends_on": [
        "platform_core",
        "admin",
        "records_eyepiece",
    ],
}


class TmxApp(App):
    def __init__(self):
        super().__init__(
            app_id="tmx",
            display_name="TMX",
            description="TMX metadata service and tracklist ownership.",
            depends_on=("platform_core", "admin", "records_eyepiece"),
            entry_modules=("app/tmx",),
        )


APP_CLASS = TmxApp


def register(aseco: "Aseco"):
    service.register(aseco)
