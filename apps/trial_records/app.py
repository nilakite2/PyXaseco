from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "trial_records",
    "display_name": "Trial Records",
    "description": "Trial API-backed records service and related records widget ownership.",
    "modules": [
        "apps/trial_records/service.py",
        "apps/trial_records/views.py",
    ],
    "entries": [
        "app/trial_records",
    ],
    "provides": [
        "service/trial_records",
    ],
    "depends_on": [
        "platform_core",
        "records_eyepiece",
    ],
}


class TrialRecordsApp(App):
    def __init__(self):
        super().__init__(
            app_id="trial_records",
            display_name="Trial Records",
            description="Trial API-backed records service and related records widget ownership.",
            depends_on=("platform_core", "records_eyepiece"),
            entry_modules=("app/trial_records",),
        )


APP_CLASS = TrialRecordsApp


def register(aseco: "Aseco"):
    service.register(aseco)
