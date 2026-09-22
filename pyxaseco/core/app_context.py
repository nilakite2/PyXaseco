from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyxaseco.app_config import AppSettingsSchema, bind_app_settings, get_app_defaults_path, get_app_section
from pyxaseco.core.base.callback import Callback
from pyxaseco.core.base.command import Command

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.core.app_metadata import AppMetadata


class AppSettingsManager:
    def __init__(self, context: "AppContext"):
        self._context = context
        self._bound: dict[str, Any] = {}

    @property
    def controller(self):
        return self._context.aseco.settings

    @property
    def source_path(self):
        _section, path = self.section()
        return path

    @property
    def defaults_path(self):
        app_id = self._context.app_id or (self._context.app_metadata.app_id if self._context.app_metadata else "")
        return get_app_defaults_path(app_id, self._context.base_dir) if app_id else None

    def section(self, section_name: str | None = None) -> tuple[dict[str, Any], Any]:
        resolved = section_name or self._context.app_id
        return get_app_section(resolved, self._context.base_dir)

    def get(self, key: str, default: Any = None, *, section_name: str | None = None) -> Any:
        section, _path = self.section(section_name)
        return section.get(key, default) if isinstance(section, dict) else default

    def bind(self, schema: AppSettingsSchema):
        cache_key = schema.resolve_section_name()
        bound = self._bound.get(cache_key)
        if bound is None:
            bound = bind_app_settings(schema, self._context.base_dir)
            self._bound[cache_key] = bound
        return bound


class AppEventManager:
    def __init__(self, context: "AppContext"):
        self._context = context

    def register(self, event_or_callback: str | Callback, handler=None):
        if isinstance(event_or_callback, Callback):
            return event_or_callback.register(self._context.aseco, app=self._context.app_id)
        self._context.aseco.register_event(str(event_or_callback), handler)
        return handler

    def subscribe(self, event_name: str, handler):
        return self.register(event_name, handler)

    def emit(self, event_name: str, param: Any = None):
        return self._context.aseco.release_event(event_name, param)

    def has_handlers(self, event_name: str) -> bool:
        return self._context.aseco.events.has_handlers(event_name)


class AppCommandManager:
    def __init__(self, context: "AppContext"):
        self._context = context

    def register(self, command_or_name: Command | str, help_text: str = "", **kwargs):
        if isinstance(command_or_name, Command):
            return command_or_name.register(self._context.aseco, app=self._context.app_id)
        return self._context.aseco.register_command(
            command_or_name,
            help_text,
            app=self._context.app_id,
            **kwargs,
        )

    def add(self, name: str, help_text: str, **kwargs):
        return self.register(name, help_text, **kwargs)

    def bind_chat(self, name: str, help_text: str, handler, **kwargs):
        registration = self.register(name, help_text, **kwargs)
        self._context.aseco.register_event(f"onChat_{registration.name}", handler)
        return registration

    def get(self, name: str):
        return self._context.aseco.get_command(name)


class AppServiceManager:
    def __init__(self, context: "AppContext"):
        self._context = context

    def register(self, name: str, service: Any, **kwargs):
        kwargs.setdefault("owner", self._context.app_id or None)
        return self._context.aseco.register_service(name, service, **kwargs)

    def get(self, name: str, default: Any = None) -> Any:
        return self._context.aseco.get_service(name, default)

    def require(self, name: str) -> Any:
        return self._context.aseco.require_service(name)

    def has(self, name: str) -> bool:
        return self._context.aseco.has_service(name)


class AppUiManager:
    def __init__(self, context: "AppContext"):
        self._context = context

    async def show(self, login: str, xml: str, timeout: int = 0, hide_click: bool = False) -> None:
        await self._context.aseco.client.query_ignore_result(
            "SendDisplayManialinkPageToLogin",
            login,
            xml,
            timeout,
            hide_click,
        )

    async def broadcast(self, xml: str, timeout: int = 0, hide_click: bool = False) -> None:
        await self._context.aseco.client.query_ignore_result(
            "SendDisplayManialinkPage",
            xml,
            timeout,
            hide_click,
        )

    async def hide(self, login: str, manialink_id: int | str) -> None:
        await self.show(login, f'<manialink id="{manialink_id}"></manialink>', 0, False)


class AppDriverManager:
    def __init__(self, context: "AppContext"):
        self._context = context

    def get(self, name: str, default: Any = None) -> Any:
        return self._context.aseco.drivers.get(name, default)

    def require(self, name: str) -> Any:
        if name not in self._context.aseco.drivers:
            raise KeyError(f"driver not registered: {name}")
        return self._context.aseco.drivers[name]


@dataclass(slots=True)
class AppContext:
    """Structured runtime context for one active app."""

    aseco: "Aseco"
    app_id: str = ""
    app_metadata: "AppMetadata | None" = None
    _settings_manager: AppSettingsManager = field(init=False, repr=False)
    _event_manager: AppEventManager = field(init=False, repr=False)
    _command_manager: AppCommandManager = field(init=False, repr=False)
    _service_manager: AppServiceManager = field(init=False, repr=False)
    _ui_manager: AppUiManager = field(init=False, repr=False)
    _driver_manager: AppDriverManager = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._settings_manager = AppSettingsManager(self)
        self._event_manager = AppEventManager(self)
        self._command_manager = AppCommandManager(self)
        self._service_manager = AppServiceManager(self)
        self._ui_manager = AppUiManager(self)
        self._driver_manager = AppDriverManager(self)

    @property
    def base_dir(self):
        return self.aseco._base_dir

    @property
    def controller_settings(self):
        return self.aseco.settings

    @property
    def settings(self) -> AppSettingsManager:
        return self._settings_manager

    @property
    def events(self) -> AppEventManager:
        return self._event_manager

    @property
    def signals(self) -> AppEventManager:
        return self._event_manager

    @property
    def services(self) -> AppServiceManager:
        return self._service_manager

    @property
    def commands(self) -> AppCommandManager:
        return self._command_manager

    @property
    def ui(self) -> AppUiManager:
        return self._ui_manager

    @property
    def drivers(self) -> AppDriverManager:
        return self._driver_manager

    def get_service(self, name: str, default: Any = None) -> Any:
        return self.aseco.get_service(name, default)

    def require_service(self, name: str) -> Any:
        return self.aseco.require_service(name)

    def logger(self, name: str = "") -> logging.Logger:
        if name:
            return logging.getLogger(name)
        if self.app_metadata is not None and self.app_metadata.package_name:
            return logging.getLogger(self.app_metadata.package_name)
        if self.app_id:
            return logging.getLogger(f"apps.{self.app_id}")
        return logging.getLogger("pyxaseco")

    def with_app(self, metadata: "AppMetadata") -> "AppContext":
        return AppContext(self.aseco, app_id=metadata.app_id, app_metadata=metadata)
