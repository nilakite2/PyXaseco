from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "cpll",
    "display_name": "CPLL",
    "description": "Checkpoint list live feature.",
    "modules": [
        "apps/cpll/feature.py",
    ],
    "entries": [
        "app/cpll",
    ],
    "provides": [
        "feature/cpll",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class CpllApp(App):
    def __init__(self):
        super().__init__(
            app_id="cpll",
            display_name="CPLL",
            description="Checkpoint list live feature.",
            depends_on=("platform_core",),
            entry_modules=("app/cpll",),
        )


APP_CLASS = CpllApp


def register(aseco: "Aseco"):
    feature.register(aseco)
