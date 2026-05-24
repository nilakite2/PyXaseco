from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


_ROOT = Path(__file__).resolve().parents[2]
_DISABLED_ROOT = _ROOT / "not_required" / "apps" / "00disabled"

_OPTIONAL_DISABLED_FILES = {
    "feature/rpoints": _DISABLED_ROOT / "skip" / "rpoints.py",
    "plugin_rpoints": _DISABLED_ROOT / "skip" / "rpoints.py",
    "skip/rpoints": _DISABLED_ROOT / "skip" / "rpoints.py",
    "plugin_autotime": _DISABLED_ROOT / "skip" / "autotime.py",
    "skip/autotime": _DISABLED_ROOT / "skip" / "autotime.py",
    "plugin_access": _DISABLED_ROOT / "skip" / "access.py",
    "skip/access": _DISABLED_ROOT / "skip" / "access.py",
}


def import_runtime_module(module_ref: str) -> ModuleType:
    """Resolve an active runtime module, with disabled-only fallbacks."""
    ref = str(module_ref or "").strip()
    if not ref:
        raise ImportError("Empty runtime module reference")

    normalized = ref.replace("\\", "/")
    if normalized.startswith("apps.") or normalized.startswith("pyxaseco."):
        return importlib.import_module(normalized)

    if "/" in normalized:
        parts = normalized.split("/", 1)
        if parts[0] == "app" and parts[1]:
            return importlib.import_module(f"apps.{parts[1]}.app")

    file_path = _OPTIONAL_DISABLED_FILES.get(normalized)
    if file_path and file_path.exists():
        cache_key = f"pyxaseco.runtime.disabled.{normalized.replace('/', '.')}"
        cached = sys.modules.get(cache_key)
        if cached is not None:
            return cached

        spec = importlib.util.spec_from_file_location(cache_key, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load disabled runtime module {ref!r} from {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[cache_key] = module
        spec.loader.exec_module(module)
        return module

    return importlib.import_module(ref)


def import_runtime_callable(callable_ref: str):
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
