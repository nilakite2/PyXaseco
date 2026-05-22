from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "ztrack",
    "display_name": "ZTrack",
    "description": "ZTrack helper and map integration feature.",
    "modules": [
        "apps/ztrack/feature.py",
    ],
    "entries": [
        "app/ztrack",
    ],
    "provides": [
        "feature/ztrack",
    ],
    "depends_on": [
        "platform_core",
        "tmx",
    ],
}


class ZTrackApp(App):
    def __init__(self):
        super().__init__(
            app_id="ztrack",
            display_name="ZTrack",
            description="ZTrack helper and map integration feature.",
            depends_on=("platform_core", "tmx"),
            entry_modules=("app/ztrack",),
        )


APP_CLASS = ZTrackApp


def register(aseco: "Aseco"):
    feature.register(aseco)
