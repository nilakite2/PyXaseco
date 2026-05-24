from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import ui
from .ui import FUFI_MENU_SETTINGS_SCHEMA

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "fufi_menu",
    "display_name": "FuFi Menu",
    "description": "FuFi menu shell and menu navigation.",
    "modules": [
        "apps/fufi_menu/ui.py",
    ],
    "entries": [
        "app/fufi_menu",
    ],
    "provides": [
        "ui/fufi_menu",
    ],
    "depends_on": [
        "platform_ui",
        "admin",
        "rasp",
    ],
}


class FufiMenuApp(App):
    def __init__(self):
        super().__init__(
            app_id="fufi_menu",
            display_name="FuFi Menu",
            description="FuFi menu shell and menu navigation.",
            depends_on=("platform_ui", "admin", "rasp"),
            entry_modules=("app/fufi_menu",),
            settings_schema=FUFI_MENU_SETTINGS_SCHEMA,
        )


APP_CLASS = FufiMenuApp


def register(aseco: "Aseco"):
    ui.register(aseco)
