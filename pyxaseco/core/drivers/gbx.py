from __future__ import annotations

from typing import Any


class GbxDriver:
    """Infrastructure boundary around the dedicated server GBX client."""

    def __init__(self, client: Any):
        self._client = client

    async def connect(self, host: str, port: int, *, timeout: float = 10.0) -> None:
        await self._client.connect(host, port, timeout=timeout)

    async def authenticate(self, login: str, password: str) -> None:
        await self._client.authenticate(login, password)

    async def query(self, method: str, *params):
        return await self._client.query(method, *params)

    async def query_ignore_result(self, method: str, *params):
        return await self._client.query_ignore_result(method, *params)

    async def disconnect(self) -> None:
        await self._client.disconnect()
