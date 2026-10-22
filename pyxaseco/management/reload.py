"""Shared runtime configuration-reload contract, not Python source hot-loading."""

import importlib
import inspect

from .app_policy import RELOADABLE_APPS


def can_reload(aseco, app_id: str) -> bool:
    loaded = getattr(aseco, 'active_apps', None)
    return app_id in RELOADABLE_APPS and (loaded is None or app_id in loaded)


async def reload_app(aseco, app_id: str, item_key: str | None = None) -> bool:
    if not can_reload(aseco, app_id):
        return False
    from pyxaseco.app_config import clear_app_defaults_cache
    from pyxaseco.settings_loader import clear_app_defaults_cache as clear_settings_cache
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    clear_settings_cache()
    if app_id == 'ui' and item_key:
        from apps.ui.runtime_reload import reload_ui_item_runtime
        await reload_ui_item_runtime(aseco, item_key)
        return True
    module = importlib.import_module(f'apps.{app_id}.app')
    callback = getattr(module, 'reload_runtime', None)
    if not callable(callback):
        return False
    result = callback(aseco)
    if inspect.isawaitable(result):
        await result
    return True
