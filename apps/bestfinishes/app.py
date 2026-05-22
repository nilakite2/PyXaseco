from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import feature

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "bestfinishes",
    "display_name": "Best Finishes",
    "description": "Finish-time comparison features.",
    "modules": [
        "apps/bestfinishes/feature.py",
    ],
    "entries": [
        "app/bestfinishes",
    ],
    "provides": [
        "feature/bestfinishes",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class BestFinishesApp(App):
    def __init__(self):
        super().__init__(
            app_id="bestfinishes",
            display_name="Best Finishes",
            description="Finish-time comparison features.",
            depends_on=("platform_core",),
            entry_modules=("app/bestfinishes",),
        )


APP_CLASS = BestFinishesApp


def register(aseco: "Aseco"):
    feature.register(aseco)
