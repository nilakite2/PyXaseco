from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class App:
    app_id: str
    display_name: str = ""
    description: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    entry_modules: tuple[str, ...] = field(default_factory=tuple)
    settings_schema: Any = None
    runtime_context: Any = field(default=None, init=False, repr=False)
    runtime_settings: Any = field(default=None, init=False, repr=False)

    def discover(self, _context) -> None:
        return None

    def load(self, _context) -> None:
        return None

    def register_runtime(self, _aseco) -> None:
        return None

    def register(self, context) -> None:
        self.runtime_context = context
        if self.settings_schema is not None:
            self.runtime_settings = context.settings.bind(self.settings_schema)
        return None

    async def startup(self, _context) -> None:
        return None

    async def shutdown(self, _context) -> None:
        return None
