from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Component:
    """Lightweight app-owned runtime surface.

    Components let an app compose command, callback, view, or model surfaces
    behind one orchestrating `app.py`, similar to how larger PyPlanet apps own
    multiple focused submodules.
    """

    component_id: str
    description: str = ""

    def register(self, _aseco) -> None:
        return None

    async def startup(self, _context) -> None:
        return None

    async def shutdown(self, _context) -> None:
        return None
