from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "cplive",
    "display_name": "CPLive",
    "description": "Checkpoint live feature.",
    "modules": [
        "apps/cplive/feature.py",
    ],
    "entries": [
        "app/cplive",
    ],
    "provides": [
        "feature/cplive",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class CpliveApp(App):
    def __init__(self):
        super().__init__(
            app_id="cplive",
            display_name="CPLive",
            description="Checkpoint live feature.",
            depends_on=("platform_core",),
            entry_modules=("app/cplive",),
        )


APP_CLASS = CpliveApp


def register(aseco: "Aseco"):
    feature.register(aseco)
