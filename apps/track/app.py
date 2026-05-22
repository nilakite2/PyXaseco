from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "track",
    "display_name": "Track",
    "description": "Track-side chat info such as song and mod details.",
    "modules": [
        "apps/track/chat.py",
    ],
    "entries": [
        "app/track",
    ],
    "provides": [
        "chat/songmod",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class TrackApp(App):
    def __init__(self):
        super().__init__(
            app_id="track",
            display_name="Track",
            description="Track-side chat info such as song and mod details.",
            depends_on=("platform_core",),
            entry_modules=("app/track",),
        )


APP_CLASS = TrackApp


def register(aseco: "Aseco"):
    chat.register(aseco)
