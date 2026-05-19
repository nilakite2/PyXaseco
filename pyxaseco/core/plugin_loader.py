"""
Plugin loader for PyXaseco v1.2.

The active runtime now uses category-based plugin entries from `plugins.toml`,
for example:

- `core/localdb`
- `service/dedimania`
- `feature/rasp_jukebox`
- `ui/records_eyepiece/plugin`

Every active plugin is loaded under the `pyxaseco.plugins.*` package tree.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


class PluginLoader:
    """Loads and initialises plugin modules."""

    def __init__(self, plugins_dir: str | Path = "plugins"):
        self.plugins_dir = Path(plugins_dir)
        self._plugins_dir_str = str(self.plugins_dir.resolve())
        self._loaded: list[str] = []
        self._ensure_plugin_packages()

    def _ensure_plugin_packages(self) -> None:
        """Expose the shared plugins folder as `pyxaseco.plugins`."""
        if self._plugins_dir_str not in sys.path:
            sys.path.insert(0, self._plugins_dir_str)

        pyxaseco_pkg = sys.modules.get("pyxaseco.plugins")
        if pyxaseco_pkg is None:
            pyxaseco_pkg = types.ModuleType("pyxaseco.plugins")
            pyxaseco_pkg.__path__ = [self._plugins_dir_str]
            sys.modules["pyxaseco.plugins"] = pyxaseco_pkg
        elif not hasattr(pyxaseco_pkg, "__path__"):
            pyxaseco_pkg.__path__ = [self._plugins_dir_str]

        parent_pkg = sys.modules.get("pyxaseco")
        if parent_pkg is not None and getattr(parent_pkg, "plugins", None) is None:
            setattr(parent_pkg, "plugins", pyxaseco_pkg)

    def _ensure_module_packages(self, dotted_module_name: str) -> None:
        """Create intermediate `pyxaseco.plugins.*` namespace packages."""
        parts = dotted_module_name.split(".")
        if len(parts) <= 1:
            return

        base_path = Path(self._plugins_dir_str)
        current_name = "pyxaseco.plugins"
        for depth, part in enumerate(parts[:-1], start=1):
            current_name = f"{current_name}.{part}"
            package = sys.modules.get(current_name)
            if package is None:
                package = types.ModuleType(current_name)
                package.__path__ = [str(base_path.joinpath(*parts[:depth]).resolve())]
                sys.modules[current_name] = package
            elif not hasattr(package, "__path__"):
                package.__path__ = [str(base_path.joinpath(*parts[:depth]).resolve())]

    def load_all(self, plugin_entries: list[str], aseco: "Aseco") -> None:
        """Load each plugin by category-style entry from `plugins.toml`."""
        for entry in plugin_entries:
            resolved = self._resolve_plugin(entry)
            if resolved is None:
                logger.error("PluginLoader: plugin file not found for entry: %s", entry)
                continue
            entry_name, module_name, plugin_path = resolved
            self._load_plugin(entry_name, module_name, plugin_path, aseco)

    def _resolve_plugin(self, entry: str) -> tuple[str, str, Path] | None:
        """
        Resolve a category-style plugin entry to a dotted module name and path.

        Examples:
        - `chat/admin` -> `pyxaseco.plugins.chat.admin`
        - `feature/rasp_votes` -> `pyxaseco.plugins.feature.rasp_votes`
        - `ui/records_eyepiece/plugin` -> `pyxaseco.plugins.ui.records_eyepiece.plugin`
        """
        base = (entry or "").strip()
        if not base:
            return None
        if base.endswith(".php"):
            base = base[:-4]

        normalized = base.replace("\\", "/").strip("/")
        parts = [part for part in re.split(r"[/.]+", normalized) if part]
        if not parts:
            return None

        path_root = self.plugins_dir.joinpath(*parts)
        candidates = (
            path_root / "plugin.py",
            path_root.with_suffix(".py"),
            path_root / "__init__.py",
        )
        for candidate in candidates:
            if candidate.exists():
                module_name = ".".join(parts)
                return normalized, module_name, candidate
        return None

    def _load_plugin(self, entry_name: str, module_name: str, plugin_path: Path, aseco: "Aseco") -> None:
        """Import a single plugin module and call its `register()` function."""
        self._ensure_plugin_packages()
        self._ensure_module_packages(module_name)

        full_module_name = f"pyxaseco.plugins.{module_name}"
        spec = importlib.util.spec_from_file_location(full_module_name, plugin_path)
        if spec is None or spec.loader is None:
            logger.error("PluginLoader: could not create spec for %s", plugin_path)
            return

        module = importlib.util.module_from_spec(spec)
        sys.modules[full_module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.error("PluginLoader: error loading %s: %s", entry_name, exc, exc_info=True)
            return

        if not hasattr(module, "register"):
            logger.warning("PluginLoader: %s has no register() function - skipping", entry_name)
            return

        try:
            module.register(aseco)
            logger.info("PluginLoader: loaded %s from %s", entry_name, plugin_path)
            self._loaded.append(entry_name)
        except Exception as exc:
            logger.error("PluginLoader: register() failed for %s: %s", entry_name, exc, exc_info=True)

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._loaded)
