from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import flexitime

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "flexitime",
    "display_name": "FlexiTime",
    "description": "Optional flexible TimeAttack timer and per-track time management.",
    "modules": [
        "apps/flexitime/flexitime.py",
    ],
    "entries": [
        "app/flexitime",
    ],
    "provides": [
        "plugin_flexitime",
        "skip/flexitime",
    ],
    "depends_on": [
        "platform_core",
    ],
}


class FlexiTimeModuleSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='flexitime.timer',
            description='Optional flexible TimeAttack timer surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        register = getattr(flexitime, 'register', None)
        if callable(register):
            register(aseco)

    async def startup(self, context) -> None:
        startup = getattr(flexitime, 'startup', None)
        if callable(startup):
            await startup(context)

    async def shutdown(self, context) -> None:
        shutdown = getattr(flexitime, 'shutdown', None)
        if callable(shutdown):
            await shutdown(context)


class FlexiTimeApp(App):
    def __init__(self):
        super().__init__(
            app_id="flexitime",
            display_name="FlexiTime",
            description="Optional flexible TimeAttack timer and per-track time management.",
            depends_on=("platform_core",),
            entry_modules=("app/flexitime",),
        )
        self.components = (FlexiTimeModuleSurface(),)

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = FlexiTimeApp
APP_INSTANCE = FlexiTimeApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
