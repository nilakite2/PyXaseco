from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.core.app_metadata import AppMetadata


@dataclass(slots=True)
class AppContext:
    """Structured runtime context for controller modules."""

    aseco: "Aseco"
    app_id: str = ""
    app_metadata: "AppMetadata | None" = None

    @property
    def base_dir(self):
        return self.aseco._base_dir

    @property
    def settings(self):
        return self.aseco.settings

    @property
    def events(self):
        return self.aseco.events

    @property
    def services(self):
        return self.aseco.services

    @property
    def commands(self):
        return self.aseco.commands

    @property
    def drivers(self):
        return self.aseco.drivers

    def get_service(self, name: str, default: Any = None) -> Any:
        return self.aseco.get_service(name, default)

    def require_service(self, name: str) -> Any:
        return self.aseco.require_service(name)

    def logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

    def with_app(self, metadata: "AppMetadata") -> "AppContext":
        return AppContext(self.aseco, app_id=metadata.app_id, app_metadata=metadata)
