from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import chatlog, checkpoints, donate, lastwin, localdb, rounds, track, uptodate

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "platform_core",
    "display_name": "Platform Core",
    "description": "Controller runtime backbone and low-level server state ownership.",
    "modules": [
        "apps/platform_core/localdb.py",
        "apps/platform_core/rounds.py",
        "apps/platform_core/track.py",
        "apps/platform_core/chatlog.py",
        "apps/platform_core/checkpoints.py",
        "apps/platform_core/donate.py",
        "apps/platform_core/uptodate.py",
        "apps/platform_core/lastwin.py",
    ],
    "entries": [
        "app/platform_core",
    ],
    "provides": [
        "core/localdb",
        "core/rounds",
        "core/track",
        "core/chatlog",
        "core/checkpoints",
        "core/donate",
        "core/uptodate",
        "chat/lastwin",
    ],
}


class PlatformCoreModuleSurface(Component):
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


class PlatformCoreApp(App):
    def __init__(self):
        super().__init__(
            app_id="platform_core",
            display_name="Platform Core",
            description="Controller runtime backbone and low-level server state ownership.",
            entry_modules=("app/platform_core",),
        )
        self.service_surfaces = (
            PlatformCoreModuleSurface(
                component_id='platform_core.localdb',
                description='Database, schema, and local player/track persistence surface.',
                module=localdb,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.rounds',
                description='Round and flow-state persistence surface.',
                module=rounds,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.track',
                description='Track and challenge list ownership surface.',
                module=track,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.chatlog',
                description='Chat logging surface.',
                module=chatlog,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.checkpoints',
                description='Checkpoint tracking and persistence surface.',
                module=checkpoints,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.donate',
                description='Donation handling surface.',
                module=donate,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.uptodate',
                description='Version check and update notice surface.',
                module=uptodate,
            ),
            PlatformCoreModuleSurface(
                component_id='platform_core.lastwin',
                description='Last-win chat information surface.',
                module=lastwin,
            ),
        )
        self.components = self.service_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = PlatformCoreApp
APP_INSTANCE = PlatformCoreApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
