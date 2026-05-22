from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "tmxvideo",
    "display_name": "TMX Video",
    "description": "TMX video lookup feature.",
    "modules": [
        "apps/tmxvideo/feature.py",
    ],
    "entries": [
        "app/tmxvideo",
    ],
    "provides": [
        "feature/tmxvideo",
    ],
    "depends_on": [
        "tmx",
    ],
}


class TmxVideoApp(App):
    def __init__(self):
        super().__init__(
            app_id="tmxvideo",
            display_name="TMX Video",
            description="TMX video lookup feature.",
            depends_on=("tmx",),
            entry_modules=("app/tmxvideo",),
        )


APP_CLASS = TmxVideoApp


def register(aseco: "Aseco"):
    feature.register(aseco)
