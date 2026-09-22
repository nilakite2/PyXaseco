from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import listing, live

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "checkpoint_tools",
    "display_name": "Checkpoint Tools",
    "description": "Checkpoint live overlays and checkpoint list tools.",
    "modules": [
        "apps/checkpoint_tools/live.py",
        "apps/checkpoint_tools/listing.py",
    ],
    "entries": [
        "app/checkpoint_tools",
    ],
    "provides": [
        "feature/cplive",
        "feature/cpll",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class CheckpointToolsModuleSurface(Component):
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


class CheckpointToolsApp(App):
    def __init__(self):
        super().__init__(
            app_id="checkpoint_tools",
            display_name="Checkpoint Tools",
            description="Checkpoint live overlays and checkpoint list tools.",
            depends_on=("platform_core",),
            entry_modules=("app/checkpoint_tools",),
        )
        self.components = (
            CheckpointToolsModuleSurface(
                component_id='checkpoint_tools.cplive',
                description='Checkpoint live overlay surface.',
                module=live,
            ),
            CheckpointToolsModuleSurface(
                component_id='checkpoint_tools.cpll',
                description='Checkpoint list live command and overlay surface.',
                module=listing,
            ),
        )

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = CheckpointToolsApp
APP_INSTANCE = CheckpointToolsApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco: "Aseco") -> None:
    await live.reload_cplive_runtime(aseco)
