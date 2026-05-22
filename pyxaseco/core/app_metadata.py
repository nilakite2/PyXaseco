from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppMetadata:
    app_id: str
    package_name: str
    display_name: str = ""
    description: str = ""
    category: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    modules: tuple[str, ...] = field(default_factory=tuple)
    entries: tuple[str, ...] = field(default_factory=tuple)
    provides: tuple[str, ...] = field(default_factory=tuple)
    loaded_modules: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_raw(
        cls,
        package_name: str,
        raw: dict[str, Any] | None,
        *,
        default_app_id: str = "",
        entry_name: str = "",
        loaded_module: str = "",
        category: str = "",
    ) -> "AppMetadata":
        data = raw if isinstance(raw, dict) else {}
        app_id = str(data.get("id") or data.get("app_id") or default_app_id or package_name.rsplit(".", 1)[-1]).strip()
        display_name = str(data.get("display_name", "") or "").strip()
        description = str(data.get("description", "") or "").strip()
        resolved_category = str(data.get("category", "") or category or "").strip()
        depends_on = tuple(str(item).strip() for item in (data.get("depends_on", []) or []) if str(item).strip())
        modules = tuple(str(item).strip() for item in (data.get("modules", []) or []) if str(item).strip())
        entries = tuple(
            str(item).strip()
            for item in (data.get("entries", []) or ([entry_name] if entry_name else []))
            if str(item).strip()
        )
        provides = tuple(str(item).strip() for item in (data.get("provides", []) or []) if str(item).strip())
        loaded_modules = tuple(
            str(item).strip()
            for item in ([loaded_module] if loaded_module else [])
            if str(item).strip()
        )
        return cls(
            app_id=app_id,
            package_name=package_name,
            display_name=display_name,
            description=description,
            category=resolved_category,
            depends_on=depends_on,
            modules=modules,
            entries=entries,
            provides=provides,
            loaded_modules=loaded_modules,
        )

    def merge(self, other: "AppMetadata") -> "AppMetadata":
        def _merge_tuple(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
            merged: list[str] = list(left)
            for item in right:
                if item not in merged:
                    merged.append(item)
            return tuple(merged)

        return AppMetadata(
            app_id=self.app_id,
            package_name=self.package_name,
            display_name=other.display_name or self.display_name,
            description=other.description or self.description,
            category=other.category or self.category,
            depends_on=_merge_tuple(self.depends_on, other.depends_on),
            modules=_merge_tuple(self.modules, other.modules),
            entries=_merge_tuple(self.entries, other.entries),
            provides=_merge_tuple(self.provides, other.provides),
            loaded_modules=_merge_tuple(self.loaded_modules, other.loaded_modules),
        )
