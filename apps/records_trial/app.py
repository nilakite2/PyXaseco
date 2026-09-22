from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "records_trial",
    "display_name": "Records Trial",
    "description": "Trial API-backed records service and related records widget ownership.",
    "modules": [
        "apps/records_trial/service.py",
        "apps/records_trial/records_widget.py",
    ],
    "entries": [
        "app/records_trial",
    ],
    "provides": [
        "app/trial_records",
        "service/records_trial",
        "service/trial_records",
    ],
    "depends_on": [
        "platform_core",
        "ui",
    ],
}


class TrialRecordsApp(App):
    def __init__(self):
        super().__init__(
            app_id="records_trial",
            display_name="Records Trial",
            description="Trial API-backed records service and related records widget ownership.",
            depends_on=("platform_core", "ui"),
            entry_modules=("app/records_trial",),
        )


APP_CLASS = TrialRecordsApp


def register(aseco: "Aseco"):
    service.register(aseco)
