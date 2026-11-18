from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from pyxaseco.core.base import App, Component

from . import allbutton, banner, callbacks, commands, karma, menu, models, views
from .config import MIN_DONATION_WIDTH, MIN_PAYOUT_WIDTH, MIN_RECORD_WIDTH, _state, _load_config

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def validate_config(document, _root):
    from .runtime_reload import BAR_TARGETS

    section = document.get('ui', {})
    width_limits = dict.fromkeys(('local_records', 'dedimania_records', 'live_rankings',
                                 'scoretable_lists', 'round_score'), MIN_RECORD_WIDTH)
    width_limits.update(donation_widget=MIN_DONATION_WIDTH, winning_payout=MIN_PAYOUT_WIDTH)

    def check(table, minimum_width, path, *, minimum_height=0):
        for key, value in table.items():
            if isinstance(value, dict):
                check(value, minimum_width, f'{path}.{key}', minimum_height=minimum_height)
            elif key in ('width', 'height', 'row_height'):
                minimum = {'width': minimum_width, 'height': minimum_height, 'row_height': 1}[key]
                number = float(value)
                if not isfinite(number) or number < minimum:
                    raise ValueError(f'{path}.{key} must be at least {minimum:g}.')

    for name, minimum in width_limits.items():
        if isinstance(table := section.get(name), dict):
            check(table, minimum, name)
    for name in (*BAR_TARGETS, 'checkpointcount_widget', 'challenge_widget'):
        if isinstance(table := section.get(name), dict):
            check(table, 4 if name == 'challenge_widget' else 1, name, minimum_height=1)


APP_METADATA = {
    "id": "ui",
    "display_name": "UI",
    "description": "Shared HUD shell, menu navigation, karma widgets, and records UI orchestration.",
    "modules": [
        "apps/ui/config.py",
        "apps/ui/models.py",
        "apps/ui/banner.py",
        "apps/ui/challenge_widget.py",
        "apps/ui/hud.py",
        "apps/ui/helpwin.py",
        "apps/ui/toplists.py",
        "apps/ui/score_preview.py",
        "apps/ui/race_preview.py",
        "apps/ui/tracklist.py",
        "apps/ui/hud_views.py",
        "apps/ui/record_views.py",
        "apps/ui/views.py",
        "apps/ui/internal/helpers.py",
        "apps/ui/internal/state.py",
        "apps/ui/internal/toml_loader.py",
        "apps/ui/internal/utils.py",
        "apps/ui/handlers/actions.py",
        "apps/ui/handlers/command_handlers.py",
        "apps/ui/handlers/events.py",
        "apps/ui/callbacks.py",
        "apps/ui/commands.py",
        "apps/ui/menu.py",
        "apps/ui/menu_layout.py",
        "apps/ui/record_widgets.py",
        "apps/ui/karma.py",
        "apps/ui/allbutton.py",
    ],
    "entries": [
        "app/ui",
    ],
    "provides": [
        "app/records_eyepiece",
        "app/fufi_menu",
        "app/mania_karma",
        "ui/records_eyepiece/app",
        "ui/custom_ui",
        "ui/fufi_menu",
        "ui/banner",
        "service/mania_karma",
        "plugin_tgj_allbutton",
    ],
}


class UiModuleSurface(Component):
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


class UiApp(App):
    def __init__(self):
        super().__init__(
            app_id="ui",
            display_name="UI",
            description="Shared HUD shell, menu navigation, karma widgets, and records UI orchestration.",
            depends_on=("platform_core", "platform_ui", "admin"),
            entry_modules=("app/ui",),
        )
        self.command_surface = commands.get_component()
        self.callback_surface = callbacks.get_component()
        self.model_surface = models.get_component()
        self.view_surface = views.get_component()
        self.menu_surface = UiModuleSurface(
            component_id='ui.menu',
            description='FuFi menu shell and navigation surface.',
            module=menu,
        )
        self.banner_surface = UiModuleSurface(
            component_id='ui.banner',
            description='Server banner and intro surface.',
            module=banner,
        )
        self.karma_surface = UiModuleSurface(
            component_id='ui.karma',
            description='Karma voting and scoreboard UI surface.',
            module=karma,
        )
        self.allbutton_surface = UiModuleSurface(
            component_id='ui.allbutton',
            description='Optional TGJ quick-chat allbutton surface.',
            module=allbutton,
        )
        self.components = (
            self.model_surface,
            self.view_surface,
            self.banner_surface,
            self.menu_surface,
            self.karma_surface,
            self.allbutton_surface,
            self.command_surface,
            self.callback_surface,
        )

    def register_runtime(self, aseco: 'Aseco') -> None:
        from .handlers.events import _apply_custom_ui
        from . import score_preview
        aseco.register_service('ui/custom_ui', _apply_custom_ui, owner='ui')
        score_preview.register(aseco)
        for component in self.components:
            component.register(aseco)

    async def startup(self, context) -> None:
        for component in self.components:
            await component.startup(context)

    async def shutdown(self, context) -> None:
        for component in reversed(self.components):
            await component.shutdown(context)


APP_CLASS = UiApp
APP_INSTANCE = UiApp()


def register(aseco: 'Aseco'):
    APP_INSTANCE.register_runtime(aseco)


def get_state():
    return _state


def reload_config(aseco: 'Aseco') -> None:
    _load_config(aseco)


async def reload_runtime(aseco: 'Aseco') -> None:
    if getattr(aseco, 'ui_delivery', None):
        aseco.ui_delivery.invalidate()
    from .handlers.command_handlers import reload_ui_layout_runtime

    await reload_ui_layout_runtime(aseco)
