from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Command:
    name: str
    help_text: str = ""
    usage: str = ""
    category: str = "chat"
    permission: str = ""
    public: bool = True
    hidden: bool = False
