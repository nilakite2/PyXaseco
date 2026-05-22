from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import bridge, service

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "discord",
    "display_name": "Discord",
    "description": "Discord integrations.",
    "modules": [
        "apps/discord/service.py",
        "apps/discord/bridge.py",
    ],
    "entries": [
        "app/discord",
    ],
    "provides": [
        "service/discord_webhook",
        "bridge/discord",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class DiscordApp(App):
    def __init__(self):
        super().__init__(
            app_id="discord",
            display_name="Discord",
            description="Discord integrations.",
            depends_on=("platform_core",),
            entry_modules=("app/discord",),
        )


APP_CLASS = DiscordApp


def register(aseco: "Aseco"):
    service.register(aseco)
    bridge.register(aseco)
