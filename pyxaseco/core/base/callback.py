from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Callback:
    event_name: str
    handler: Any = None
    owner: str | None = None

    def register(self, aseco, *, app: str = ""):
        if not callable(self.handler):
            raise ValueError(f"callback handler is not callable for {self.event_name}")
        aseco.register_event(self.event_name, self.handler)
        return self.handler
