from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat_records, chat_records2, chat_recrels

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "records_local",
    "display_name": "Local Records",
    "description": "Local record chat flows and related records widgets.",
    "modules": [
        "apps/records_local/chat_records.py",
        "apps/records_local/chat_records2.py",
        "apps/records_local/chat_recrels.py",
        "apps/records_local/views.py",
    ],
    "entries": [
        "app/records_local",
    ],
    "provides": [
        "chat/records",
        "chat/records2",
        "chat/recrels",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class RecordsLocalApp(App):
    def __init__(self):
        super().__init__(
            app_id="records_local",
            display_name="Local Records",
            description="Local record chat flows and related records widgets.",
            depends_on=("platform_core",),
            entry_modules=("app/records_local",),
        )


APP_CLASS = RecordsLocalApp


def register(aseco: "Aseco"):
    chat_records.register(aseco)
    chat_records2.register(aseco)
    chat_recrels.register(aseco)
