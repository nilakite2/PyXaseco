from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class View:
    name: str
    template_name: str = ""
