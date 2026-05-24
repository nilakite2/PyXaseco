from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .callback import Callback
from .command import Command


@dataclass(slots=True)
class Component:
    """Lightweight app-owned runtime surface."""

    component_id: str
    description: str = ""
    commands: tuple[Command, ...] = field(default_factory=tuple)
    callbacks: tuple[Callback, ...] = field(default_factory=tuple)
    services: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def register(self, aseco) -> None:
        app_id = self.component_id.split(".", 1)[0] if "." in self.component_id else ""
        for name, service in self.services:
            aseco.register_service(name, service, owner=app_id or None)
        for command in self.commands:
            command.register(aseco, app=app_id)
        for callback in self.callbacks:
            callback.register(aseco, app=app_id)

    async def startup(self, _context) -> None:
        return None

    async def shutdown(self, _context) -> None:
        return None
