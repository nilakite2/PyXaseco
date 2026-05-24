from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import banner, panels, style

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "platform_ui",
    "display_name": "Platform UI",
    "description": "Shared style, panel, and banner infrastructure.",
    "modules": [
        "apps/platform_ui/style.py",
        "apps/platform_ui/panels.py",
        "apps/platform_ui/banner.py",
    ],
    "entries": [
        "app/platform_ui",
    ],
    "provides": [
        "ui/style",
        "ui/panels",
        "ui/banner",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class PlatformUiModuleSurface(Component):
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


class PlatformUiApp(App):
    def __init__(self):
        super().__init__(
            app_id="platform_ui",
            display_name="Platform UI",
            description="Shared style, panel, and banner infrastructure.",
            depends_on=("platform_core",),
            entry_modules=("app/platform_ui",),
        )
        self.ui_surfaces = (
            PlatformUiModuleSurface(
                component_id='platform_ui.style',
                description='Shared style loading and style preference surface.',
                module=style,
            ),
            PlatformUiModuleSurface(
                component_id='platform_ui.panels',
                description='Shared panel loading and panel preference surface.',
                module=panels,
            ),
            PlatformUiModuleSurface(
                component_id='platform_ui.banner',
                description='Server banner and intro surface.',
                module=banner,
            ),
        )
        self.components = self.ui_surfaces

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = PlatformUiApp
APP_INSTANCE = PlatformUiApp()


def register(aseco: "Aseco"):
    """Runtime app entry that delegates registration to the app instance."""
    APP_INSTANCE.register_runtime(aseco)
