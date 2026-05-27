from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

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
        "chat/pb",
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
        self.components = (
            RecordsLocalModuleSurface(
                component_id="records_local.records",
                description="Primary local records and personal-best command surface.",
                module=chat_records,
            ),
            RecordsLocalModuleSurface(
                component_id="records_local.rankings",
                description="Additional ranked record list and summary command surface.",
                module=chat_records2,
            ),
            RecordsLocalModuleSurface(
                component_id="records_local.relations",
                description="Relative local record lookup command surface.",
                module=chat_recrels,
            ),
        )

    def register_runtime(self, aseco: "Aseco") -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


class RecordsLocalModuleSurface(Component):
    def __init__(self, component_id: str, description: str, module):
        super().__init__(component_id=component_id, description=description)
        self.module = module

    def register(self, aseco: "Aseco") -> None:
        register = getattr(self.module, "register", None)
        if callable(register):
            register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(self.module, "startup", None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(self.module, "shutdown", None)
        if callable(shutdown):
            await shutdown(context)


APP_CLASS = RecordsLocalApp
APP_INSTANCE = RecordsLocalApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
