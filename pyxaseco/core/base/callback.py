from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Callback:
    event_name: str
    handler_name: str = ""
