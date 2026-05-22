from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ServiceRegistration:
    name: str
    service: Any
    owner: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


class ServiceRegistry:
    """Runtime registry for controller services."""

    def __init__(self):
        self._services: dict[str, ServiceRegistration] = {}

    def register(self, name: str, service: Any, *, owner: str | None = None, aliases: list[str] | tuple[str, ...] | None = None) -> ServiceRegistration:
        key = (name or "").strip()
        if not key:
            raise ValueError("service name must not be empty")

        alias_list = tuple(a.strip() for a in (aliases or []) if str(a).strip())
        registration = ServiceRegistration(
            name=key,
            service=service,
            owner=owner,
            aliases=alias_list,
        )

        self._services[key] = registration
        for alias in alias_list:
            self._services[alias] = registration
        return registration

    def unregister(self, name: str) -> bool:
        key = (name or "").strip()
        registration = self._services.get(key)
        if registration is None:
            return False

        to_remove = [service_name for service_name, value in self._services.items() if value is registration]
        for service_name in to_remove:
            self._services.pop(service_name, None)
        return True

    def get(self, name: str, default: Any = None) -> Any:
        registration = self._services.get((name or "").strip())
        if registration is None:
            return default
        return registration.service

    def require(self, name: str) -> Any:
        registration = self._services.get((name or "").strip())
        if registration is None:
            raise KeyError(f"service not registered: {name}")
        return registration.service

    def has(self, name: str) -> bool:
        return (name or "").strip() in self._services

    def registration(self, name: str) -> ServiceRegistration | None:
        return self._services.get((name or "").strip())

    def registrations(self) -> dict[str, ServiceRegistration]:
        result: dict[str, ServiceRegistration] = {}
        for name, registration in self._services.items():
            if registration.name == name:
                result[name] = registration
        return result

    def names(self) -> list[str]:
        return sorted(self.registrations().keys())
