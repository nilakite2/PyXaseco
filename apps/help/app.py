from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "help",
    "display_name": "Help",
    "description": "Shared help and command discovery surfaces.",
    "modules": [
        "apps/help/chat.py",
    ],
    "entries": [
        "app/help",
    ],
    "provides": [
        "chat/help",
    ],
}


class HelpApp(App):
    def __init__(self):
        super().__init__(
            app_id="help",
            display_name="Help",
            description="Shared help and command discovery surfaces.",
            entry_modules=("app/help",),
        )


APP_CLASS = HelpApp


def register(aseco: "Aseco"):
    chat.register(aseco)
