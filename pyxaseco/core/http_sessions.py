"""Runtime-owned HTTP pools for background services, not gameplay callbacks."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp


def request_timeout(seconds: float, *, connect_seconds: float = 5.0):
    total = max(0.1, min(300.0, float(seconds)))
    connect = max(0.1, min(total, float(connect_seconds)))
    return aiohttp.ClientTimeout(total=total, connect=connect,
                                 sock_connect=connect, sock_read=total)


@dataclass(frozen=True, slots=True)
class HttpPolicy:
    connections: int = 2
    connect_seconds: float = 5.0
    read_seconds: float = 15.0
    total_seconds: float = 30.0

    def __post_init__(self):
        if not 1 <= self.connections <= 16:
            raise ValueError('HTTP connection limit must be between 1 and 16')
        if not all(0 < value <= 300 for value in (
            self.connect_seconds, self.read_seconds, self.total_seconds,
        )):
            raise ValueError('HTTP deadlines must be between 0 and 300 seconds')


class HttpSessions:
    def __init__(self):
        self._sessions: dict[str, tuple[HttpPolicy, aiohttp.ClientSession]] = {}
        self._closed = False

    def get(self, owner: str, policy: HttpPolicy = HttpPolicy()) -> aiohttp.ClientSession:
        if self._closed:
            raise RuntimeError('HTTP sessions are closed')
        if not owner or len(owner) > 64:
            raise ValueError('HTTP owner must be a short service identifier')
        existing = self._sessions.get(owner)
        if existing is not None:
            if existing[0] != policy:
                raise ValueError('close the owner session before changing its policy')
            if not existing[1].closed:
                return existing[1]
        if existing is None and len(self._sessions) >= 32:
            raise RuntimeError('HTTP service limit reached')
        connector = aiohttp.TCPConnector(limit=policy.connections,
                                         limit_per_host=policy.connections)
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(
                total=policy.total_seconds, connect=policy.connect_seconds,
                sock_connect=policy.connect_seconds, sock_read=policy.read_seconds,
            ),
            # Do not inherit ambient proxies or share cookies across requests.
            trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
            # Use stdlib codecs; optional Brotli packages can have incompatible
            # decoder APIs even when aiohttp advertises them automatically.
            headers={'Accept-Encoding': 'gzip, deflate'},
        )
        self._sessions[owner] = policy, session
        return session

    async def close_owner(self, owner: str) -> None:
        existing = self._sessions.pop(owner, None)
        if existing is not None:
            await existing[1].close()

    async def close(self) -> None:
        self._closed = True
        for owner in list(self._sessions):
            await self.close_owner(owner)
