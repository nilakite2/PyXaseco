from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import commands, msglog, social

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "social_chat",
    "display_name": "Social Chat",
    "description": "Small social, expressive, and private-message chat commands.",
    "modules": [
        "apps/social_chat/commands.py",
        "apps/social_chat/social.py",
        "apps/social_chat/msglog.py",
    ],
    "entries": [
        "app/social_chat",
    ],
    "provides": [
        "chat/me",
        "feature/rasp_chat",
        "plugin_msglog",
    ],
}


class SocialChatApp(App):
    def __init__(self):
        super().__init__(
            app_id="social_chat",
            display_name="Social Chat",
            description="Small social, expressive, and private-message chat commands.",
            entry_modules=("app/social_chat",),
        )
        self.social_surfaces = (
            SocialChatModuleSurface(
                component_id='social_chat.commands',
                description='Small social and expressive chat command surface.',
                module=commands,
            ),
            SocialChatModuleSurface(
                component_id='social_chat.social',
                description='Private-message and lightweight social shortcuts.',
                module=social,
            ),
            SocialChatModuleSurface(
                component_id='social_chat.msglog',
                description='Optional recent system message log surface.',
                module=msglog,
            ),
        )
        self.components = self.social_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class SocialChatModuleSurface(Component):
    def __init__(self, component_id: str, description: str, module):
        super().__init__(component_id=component_id, description=description)
        self.module = module

    def register(self, aseco: 'Aseco') -> None:
        register = getattr(self.module, 'register', None)
        if callable(register):
            register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(self.module, 'startup', None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(self.module, 'shutdown', None)
        if callable(shutdown):
            await shutdown(context)


APP_CLASS = SocialChatApp
APP_INSTANCE = SocialChatApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
