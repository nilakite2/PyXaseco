from __future__ import annotations

import logging
import pathlib
import tomllib
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

_app_defaults_cache: dict[
    pathlib.Path,
    tuple[dict[str, Any], dict[str, pathlib.Path], list[pathlib.Path]],
] = {}


def _runtime_root(base_dir=None) -> pathlib.Path:
    if base_dir:
        return pathlib.Path(base_dir).resolve()
    return pathlib.Path(".").resolve()


def _section_candidates(section: str) -> tuple[str, ...]:
    raw = str(section or "").strip()
    if not raw:
        return ()

    candidates: list[str] = [raw]
    if raw.startswith("plugin_"):
        trimmed = raw[len("plugin_"):]
        if trimmed:
            candidates.append(trimmed)
    else:
        candidates.append(f"plugin_{raw}")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item and item not in seen:
            ordered.append(item)
            seen.add(item)
    return tuple(ordered)


def _lookup_path(node: Any, path: str) -> Any:
    current = node
    for part in [p for p in str(path or "").split("/") if p]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def get_app_defaults_path(app_id: str, base_dir=None) -> pathlib.Path:
    return _runtime_root(base_dir) / "apps" / str(app_id).strip() / "app_defaults.toml"


def _merge_defaults(
    aggregate: dict[str, Any],
    sources: dict[str, pathlib.Path],
    path: pathlib.Path,
    data: dict[str, Any],
) -> None:
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if key in aggregate:
            logger.warning(
                "[app_config] Duplicate defaults section %s in %s overrides %s",
                key,
                path,
                sources[key],
            )
        aggregate[key] = value
        sources[key] = path


def load_app_defaults_catalog(
    base_dir=None,
) -> tuple[dict[str, Any], dict[str, pathlib.Path], list[pathlib.Path]]:
    root = _runtime_root(base_dir)
    cached = _app_defaults_cache.get(root)
    if cached is not None:
        return cached

    aggregate: dict[str, Any] = {}
    sources: dict[str, pathlib.Path] = {}
    loaded_paths: list[pathlib.Path] = []

    apps_dir = root / "apps"
    if apps_dir.is_dir():
        for path in sorted(apps_dir.glob("*/app_defaults.toml")):
            try:
                with path.open("rb") as fh:
                    data = tomllib.load(fh)
                if not isinstance(data, dict):
                    data = {}
                _merge_defaults(aggregate, sources, path, data)
                loaded_paths.append(path)
            except Exception as exc:
                logger.error("[app_config] Failed to parse %s: %s", path, exc)

    if not aggregate:
        legacy_path = root / "plugin_defaults.toml"
        if legacy_path.exists():
            try:
                with legacy_path.open("rb") as fh:
                    data = tomllib.load(fh)
                if not isinstance(data, dict):
                    data = {}
                _merge_defaults(aggregate, sources, legacy_path, data)
                loaded_paths.append(legacy_path)
            except Exception as exc:
                logger.error("[app_config] Failed to parse %s: %s", legacy_path, exc)

    _app_defaults_cache[root] = (aggregate, sources, loaded_paths)
    return _app_defaults_cache[root]


def load_app_defaults(base_dir=None) -> tuple[dict[str, Any], pathlib.Path | None]:
    data, _sources, loaded_paths = load_app_defaults_catalog(base_dir)
    if not loaded_paths:
        return {}, None
    if len(loaded_paths) == 1:
        return data, loaded_paths[0]
    return data, _runtime_root(base_dir) / "apps"


def load_app_defaults_file(app_id: str, base_dir=None) -> tuple[dict[str, Any], pathlib.Path]:
    path = get_app_defaults_path(app_id, base_dir)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        if not isinstance(data, dict):
            data = {}
        return data, path
    except Exception as exc:
        logger.error("[app_config] Failed to parse %s: %s", path, exc)
        return {}, path


def get_app_section(section: str, base_dir=None) -> tuple[dict[str, Any], pathlib.Path | None]:
    data, sources, loaded_paths = load_app_defaults_catalog(base_dir)
    anchor_path: pathlib.Path | None = None
    if len(loaded_paths) == 1:
        anchor_path = loaded_paths[0]
    elif loaded_paths:
        anchor_path = _runtime_root(base_dir) / "apps"

    for candidate in _section_candidates(section):
        value = data.get(candidate, {})
        if isinstance(value, dict):
            return value, sources.get(candidate, anchor_path)
    return {}, anchor_path


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        val = value.strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
        if val in ("0", "false", "no", "off"):
            return False
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text != "" else default


@dataclass(slots=True, frozen=True)
class AppSetting:
    key: str
    default: Any = None
    cast: Callable[[Any, Any], Any] | Callable[[Any], Any] | None = None
    description: str = ""
    category: str = "general"
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def read(self, section: dict[str, Any]) -> Any:
        for candidate in (self.key, *self.aliases):
            raw = _lookup_path(section, candidate)
            if raw is not None:
                break
        else:
            raw = self.default

        if self.cast is None:
            return raw

        try:
            return self.cast(raw, self.default)
        except TypeError:
            return self.cast(raw)
        except Exception:
            return self.default


@dataclass(slots=True, frozen=True)
class AppSettingsSchema:
    app_id: str
    settings: tuple[AppSetting, ...]
    section_name: str = ""
    description: str = ""

    def resolve_section_name(self) -> str:
        return self.section_name or self.app_id


@dataclass(slots=True)
class BoundAppSettings:
    schema: AppSettingsSchema
    section: dict[str, Any]
    source_path: pathlib.Path | None
    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)

    def describe(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for setting in self.schema.settings:
            out.append(
                {
                    "key": setting.key,
                    "value": self.values.get(setting.key),
                    "default": setting.default,
                    "category": setting.category,
                    "description": setting.description,
                }
            )
        return out

    def __getattr__(self, item: str) -> Any:
        try:
            return self.values[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


def bind_app_settings(schema: AppSettingsSchema, base_dir=None) -> BoundAppSettings:
    section, path = get_app_section(schema.resolve_section_name(), base_dir)
    values = {setting.key: setting.read(section) for setting in schema.settings}
    return BoundAppSettings(
        schema=schema,
        section=section if isinstance(section, dict) else {},
        source_path=path,
        values=values,
    )
