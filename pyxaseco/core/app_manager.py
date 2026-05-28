"""App manager for the app-native PyXaseco runtime."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

from pyxaseco.core.app_metadata import AppMetadata
from pyxaseco.core.config import display_path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppEntry:
    entry_name: str
    module_name: str
    app_package: str
    app_id: str
    category: str


class AppManager:
    """Loads app entry modules and tracks app lifecycle metadata."""

    def __init__(self, apps_dir: str | Path = "apps"):
        self.apps_dir = Path(apps_dir)
        self._loaded_entries: list[str] = []
        self._app_metadata: dict[str, AppMetadata] = {}
        self._app_instances: dict[str, Any] = {}
        self._app_contexts: dict[str, Any] = {}
        self._registered_apps: list[str] = []
        self._started_apps: list[str] = []

    def _resolve_entry(self, entry_name: str) -> AppEntry:
        normalized = (entry_name or "").replace("\\", "/").strip("/")
        if not normalized.startswith("app/"):
            raise RuntimeError(
                f"AppManager: loadout entry '{entry_name}' is not app-native. "
                "Use app/<name> entries in apps.toml."
            )

        app_name = normalized.split("/", 1)[1].strip()
        module_name = f"apps.{app_name}.app"
        app_package = f"apps.{app_name}"
        return AppEntry(
            entry_name=normalized,
            module_name=module_name,
            app_package=app_package,
            app_id=app_name,
            category="app",
        )

    def _context_for(self, aseco: "Aseco", metadata: AppMetadata):
        context = self._app_contexts.get(metadata.app_id)
        if context is None or context.app_metadata != metadata:
            context = aseco.context.with_app(metadata)
            self._app_contexts[metadata.app_id] = context
        return context

    def _load_app_metadata(self, plan: AppEntry, aseco: "Aseco") -> AppMetadata:
        package = importlib.import_module(plan.app_package)
        raw = getattr(package, "APP_METADATA", None)
        metadata = AppMetadata.from_raw(
            plan.app_package,
            raw,
            default_app_id=plan.app_id,
            entry_name=plan.entry_name,
            loaded_module=plan.module_name,
            category=plan.category,
        )
        existing = self._app_metadata.get(metadata.app_id)
        merged = existing.merge(metadata) if existing is not None else metadata
        self._app_metadata[metadata.app_id] = merged

        app_obj = self._app_instances.get(metadata.app_id)
        app_module = importlib.import_module(f"{plan.app_package}.app")
        if app_obj is None:
            app_obj = getattr(app_module, "APP_INSTANCE", None)
            if app_obj is None:
                app_class = getattr(app_module, "APP_CLASS", None)
                if app_class is not None:
                    app_obj = app_class()
            if app_obj is not None:
                self._app_instances[metadata.app_id] = app_obj
                try:
                    context = self._context_for(aseco, metadata)
                    app_obj.discover(context)
                    app_obj.load(context)
                except Exception:
                    logger.debug("AppManager: app lifecycle pre-load hook failed for %s", metadata.app_id, exc_info=True)

        aseco.register_app_metadata(self._app_metadata[metadata.app_id])
        return self._app_metadata[metadata.app_id]

    def load_all(self, app_entries: list[str], aseco: "Aseco") -> None:
        plans = [self._resolve_entry(entry) for entry in app_entries]
        for plan in plans:
            self._load_app_metadata(plan, aseco)
        self._validate_dependencies(plans)
        for plan in plans:
            self._load_entry(plan, aseco)

    def _available_dependency_names(self) -> set[str]:
        names: set[str] = set(self._app_metadata.keys())
        for app_id, metadata in self._app_metadata.items():
            names.add(f"app/{app_id}")
            names.add(metadata.package_name)
            names.update(metadata.entries)
            names.update(metadata.provides)
        return names

    def _validate_dependencies(self, plans: list[AppEntry]) -> None:
        available = self._available_dependency_names()
        issues: list[str] = []
        seen_apps: set[str] = set()
        for plan in plans:
            if plan.app_id in seen_apps:
                continue
            seen_apps.add(plan.app_id)
            metadata = self._app_metadata.get(plan.app_id)
            if metadata is None:
                continue
            missing = [dep for dep in metadata.depends_on if dep not in available]
            if missing:
                display = metadata.display_name or metadata.app_id
                issues.append(f"{display} ({plan.entry_name}) -> missing {', '.join(missing)}")
        if issues:
            raise RuntimeError(
                "AppManager: unmet app dependencies:\n- " + "\n- ".join(issues)
            )

    def _load_entry(self, plan: AppEntry, aseco: "Aseco") -> None:
        try:
            module = importlib.import_module(plan.module_name)
        except Exception as exc:
            logger.error("AppManager: error loading %s -> %s: %s", plan.entry_name, plan.module_name, exc, exc_info=True)
            return

        if not hasattr(module, "register"):
            logger.warning("AppManager: %s has no register() function - skipping", plan.entry_name)
            return

        try:
            module.register(aseco)
            metadata = self._app_metadata.get(plan.app_id)
            if metadata is not None:
                updated = metadata.merge(
                    AppMetadata.from_raw(
                        plan.app_package,
                        {},
                        default_app_id=plan.app_id,
                        entry_name=plan.entry_name,
                        loaded_module=getattr(module, "__name__", plan.module_name),
                        category=plan.category,
                    )
                )
                self._app_metadata[plan.app_id] = updated
                aseco.register_app_metadata(updated)
            logger.info(
                "AppManager: loaded %s via %s (%s)",
                plan.entry_name,
                plan.module_name,
                display_path(getattr(module, "__file__", "<alias>")),
            )
            self._loaded_entries.append(plan.entry_name)
            if plan.app_id not in self._registered_apps:
                self._registered_apps.append(plan.app_id)
            app_obj = self._app_instances.get(plan.app_id)
            if app_obj is not None:
                try:
                    app_obj.register(self._context_for(aseco, self._app_metadata[plan.app_id]))
                except Exception:
                    logger.debug("AppManager: app lifecycle register hook failed for %s", plan.app_id, exc_info=True)
        except Exception as exc:
            logger.error("AppManager: register() failed for %s: %s", plan.entry_name, exc, exc_info=True)

    async def startup_all(self, aseco: "Aseco") -> None:
        for app_id in self._registered_apps:
            if app_id in self._started_apps:
                continue
            app_obj = self._app_instances.get(app_id)
            metadata = self._app_metadata.get(app_id)
            if app_obj is None or metadata is None:
                continue
            try:
                await app_obj.startup(self._context_for(aseco, metadata))
                self._started_apps.append(app_id)
            except Exception:
                logger.error("AppManager: startup() failed for %s", app_id, exc_info=True)

    async def shutdown_all(self, aseco: "Aseco") -> None:
        for app_id in reversed(self._started_apps):
            app_obj = self._app_instances.get(app_id)
            metadata = self._app_metadata.get(app_id)
            if app_obj is None or metadata is None:
                continue
            try:
                await app_obj.shutdown(self._context_for(aseco, metadata))
            except Exception:
                logger.error("AppManager: shutdown() failed for %s", app_id, exc_info=True)
        self._started_apps.clear()

    @property
    def loaded_entries(self) -> list[str]:
        return list(self._loaded_entries)

    @property
    def fulfilled_entries(self) -> list[str]:
        fulfilled: list[str] = list(self._loaded_entries)
        for app_id, metadata in self._app_metadata.items():
            app_entry = f"app/{app_id}"
            if app_entry not in fulfilled:
                fulfilled.append(app_entry)
            for item in metadata.entries + metadata.provides:
                if item not in fulfilled:
                    fulfilled.append(item)
        return fulfilled

    @property
    def loaded_plugins(self) -> list[str]:
        return self.loaded_entries

    @property
    def loaded_apps(self) -> list[str]:
        return list(self._registered_apps)

    @property
    def app_metadata(self) -> dict[str, AppMetadata]:
        return dict(self._app_metadata)

    @property
    def app_contexts(self) -> dict[str, Any]:
        return dict(self._app_contexts)
