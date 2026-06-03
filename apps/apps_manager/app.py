from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from .service import AppsManagerService

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "apps_manager",
    "display_name": "Apps Manager",
    "description": "Optional in-game app and app_defaults manager for admin use.",
    "modules": [
        "apps/apps_manager/service.py",
    ],
    "entries": [
        "app/apps_manager",
    ],
    "provides": [
        "service/apps_manager",
    ],
}


class AppsManagerSurface(Component):
    def __init__(self, service: AppsManagerService):
        super().__init__(
            component_id='apps_manager.service',
            description='In-game apps manager service surface.',
            services=(
                ('apps_manager', service),
                ('service/apps_manager', service),
            ),
        )


class AppsManagerApp(App):
    def __init__(self):
        super().__init__(
            app_id="apps_manager",
            display_name="Apps Manager",
            description="Optional in-game app and app_defaults manager for admin use.",
            entry_modules=("app/apps_manager",),
        )
        self.service = AppsManagerService()
        self.components = (AppsManagerSurface(self.service),)

    def register_runtime(self, aseco: 'Aseco') -> None:
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = AppsManagerApp
APP_INSTANCE = AppsManagerApp()


def register(aseco: "Aseco"):
    APP_INSTANCE.register_runtime(aseco)
