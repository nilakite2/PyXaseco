from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chat

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "social_chat",
    "display_name": "Social Chat",
    "description": "Small social and expressive chat commands.",
    "modules": [
        "apps/social_chat/chat.py",
    ],
    "entries": [
        "app/social_chat",
    ],
    "provides": [
        "chat/me",
    ],
}


class SocialChatApp(App):
    def __init__(self):
        super().__init__(
            app_id="social_chat",
            display_name="Social Chat",
            description="Small social and expressive chat commands.",
            entry_modules=("app/social_chat",),
        )


APP_CLASS = SocialChatApp


def register(aseco: "Aseco"):
    chat.register(aseco)
