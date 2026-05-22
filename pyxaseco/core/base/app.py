from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class App:
    app_id: str
    display_name: str = ""
    description: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    entry_modules: tuple[str, ...] = field(default_factory=tuple)

    def discover(self, _context) -> None:
        return None

    def load(self, _context) -> None:
        return None

    def register(self, _context) -> None:
        return None

    async def startup(self, _context) -> None:
        return None

    async def shutdown(self, _context) -> None:
        return None
