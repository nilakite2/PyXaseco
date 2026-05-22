from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat, service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "dedimania",
    "display_name": "Dedimania",
    "description": "Dedimania records service, chat flows, and related records widget ownership.",
    "modules": [
        "apps/dedimania/service.py",
        "apps/dedimania/chat.py",
        "apps/dedimania/views.py",
    ],
    "entries": [
        "app/dedimania",
    ],
    "provides": [
        "service/dedimania",
        "chat/dedimania",
    ],
    "depends_on": [
        "platform_core",
        "records_eyepiece",
    ],
}


class DedimaniaApp(App):
    def __init__(self):
        super().__init__(
            app_id="dedimania",
            display_name="Dedimania",
            description="Dedimania records service, chat flows, and related records widget ownership.",
            depends_on=("platform_core", "records_eyepiece"),
            entry_modules=("app/dedimania",),
        )


APP_CLASS = DedimaniaApp


def register(aseco: "Aseco"):
    service.register(aseco)
    chat.register(aseco)
