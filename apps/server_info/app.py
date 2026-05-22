from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "server_info",
    "display_name": "Server Info",
    "description": "Server information and runtime introspection commands.",
    "modules": [
        "apps/server_info/chat.py",
    ],
    "entries": [
        "app/server_info",
    ],
    "provides": [
        "chat/server",
    ],
}


class ServerInfoApp(App):
    def __init__(self):
        super().__init__(
            app_id="server_info",
            display_name="Server Info",
            description="Server information and runtime introspection commands.",
            entry_modules=("app/server_info",),
        )


APP_CLASS = ServerInfoApp


def register(aseco: "Aseco"):
    chat.register(aseco)
