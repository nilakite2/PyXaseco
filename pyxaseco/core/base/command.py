from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Command:
    name: str
    help_text: str = ""
    handler: Any = None
    is_admin: bool = False
    aliases: tuple[str, ...] = field(default_factory=tuple)
    usage: str = ""
    category: str = "chat"
    parent: str | None = None
    display_name: str = ""
    permission: str = ""
    role: str = ""
    owner: str | None = None
    public: bool = True
    hidden: bool = False
    order: int = 0

    def register(self, aseco, *, app: str = ""):
        registration = aseco.register_command(
            self.name,
            self.help_text,
            is_admin=self.is_admin,
            aliases=self.aliases,
            usage=self.usage,
            app=app or None,
            category=self.category,
            parent=self.parent,
            display_name=self.display_name,
            public=self.public,
            hidden=self.hidden,
            permission=self.permission,
            role=self.role,
            owner=self.owner,
            order=self.order,
        )
        if callable(self.handler):
            aseco.register_event(f"onChat_{registration.name}", self.handler)
            for alias in registration.aliases:
                aseco.register_event(f"onChat_{alias}", self.handler)
        return registration
