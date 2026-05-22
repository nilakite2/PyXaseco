from __future__ import annotations

import importlib
import importlib.util
import sys
from types import ModuleType

from pyxaseco.core.legacy_plugin_namespace import FILE_ALIASES, MODULE_ALIASES, alias_for_entry


def import_runtime_module(module_ref: str) -> ModuleType:
    """
    Resolve an active or deferred runtime module without requiring callers to
    import through the legacy ``pyxaseco.plugins.*`` namespace.

    Supported refs:
    - ``apps.platform_ui.panels``
    - ``pyxaseco.helpers``
    - ``feature.rasp``
    - ``feature/rasp``
    - ``plugin_rpoints``
    """
    ref = str(module_ref or "").strip()
    if not ref:
        raise ImportError("Empty runtime module reference")

    if ref.startswith("apps.") or ref.startswith("pyxaseco."):
        return importlib.import_module(ref)

    legacy_name = alias_for_entry(ref.replace(".", "/"))

    target_name = MODULE_ALIASES.get(legacy_name)
    if target_name:
        return importlib.import_module(target_name)

    file_path = FILE_ALIASES.get(legacy_name)
    if file_path and file_path.exists():
        cached = sys.modules.get(legacy_name)
        if cached is not None:
            return cached

        spec = importlib.util.spec_from_file_location(legacy_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load runtime module {ref!r} from {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[legacy_name] = module
        spec.loader.exec_module(module)
        return module

    return importlib.import_module(ref)


def import_runtime_callable(callable_ref: str):
    """
    Resolve a callable from the runtime graph.

    Supported refs:
    - ``apps.platform_ui.panels.admin_panel``
    - ``apps.platform_ui.panels:admin_panel``
    - ``feature/rpoints:admin_rpoints``
    - ``plugin_autotime:admin_autotime``
    """
    ref = str(callable_ref or "").strip()
    if ":" in ref:
        module_ref, attr_name = ref.rsplit(":", 1)
    else:
        module_ref, attr_name = ref.rsplit(".", 1)

    module = import_runtime_module(module_ref)
    value = getattr(module, attr_name, None)
    if not callable(value):
        raise AttributeError(attr_name)
    return value
