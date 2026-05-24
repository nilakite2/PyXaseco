from __future__ import annotations

import logging
import pathlib
import tomllib
from typing import Any

logger = logging.getLogger(__name__)

_app_defaults_cache: dict[
    pathlib.Path,
    tuple[dict[str, Any], dict[str, pathlib.Path], list[pathlib.Path]],
] = {}


def _runtime_root(base_dir=None) -> pathlib.Path:
    if base_dir:
        return pathlib.Path(base_dir).resolve()
    return pathlib.Path(".").resolve()


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
    candidates = []
    raw = str(section or "").strip()
    if raw:
        candidates.append(raw)
        if raw.startswith("plugin_"):
            candidates.append(raw[len("plugin_"):])
        else:
            candidates.append(f"plugin_{raw}")

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
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
