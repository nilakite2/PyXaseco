from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

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


class PlatformUiApp(App):
    def __init__(self):
        super().__init__(
            app_id="platform_ui",
            display_name="Platform UI",
            description="Shared style, panel, and banner infrastructure.",
            depends_on=("platform_core",),
            entry_modules=("app/platform_ui",),
        )


APP_CLASS = PlatformUiApp


def register(aseco: "Aseco"):
    style.register(aseco)
    panels.register(aseco)
    banner.register(aseco)
