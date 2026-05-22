from __future__ import annotations

from typing import Any


class DatabaseDriver:
    """Infrastructure boundary for controller database access."""

    def __init__(self, aseco: Any):
        self._aseco = aseco

    def get_service(self):
        return self._aseco.get_service("localdb")

    async def get_pool(self):
        service = self.get_service()
        getter = getattr(service, "get_pool", None) if service is not None else None
        if callable(getter):
            return await getter()
        return None
