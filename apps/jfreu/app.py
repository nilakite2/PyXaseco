from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "jfreu",
    "display_name": "JFreu",
    "description": "JFreu gameplay and rights feature set.",
    "modules": [
        "apps/jfreu/feature.py",
    ],
    "entries": [
        "app/jfreu",
    ],
    "provides": [
        "feature/jfreu",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class JFreuApp(App):
    def __init__(self):
        super().__init__(
            app_id="jfreu",
            display_name="JFreu",
            description="JFreu gameplay and rights feature set.",
            depends_on=("platform_core",),
            entry_modules=("app/jfreu",),
        )


APP_CLASS = JFreuApp


def register(aseco: "Aseco"):
    feature.register(aseco)
