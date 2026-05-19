from __future__ import annotations

import logging
import pathlib
import tomllib
from typing import Any

logger = logging.getLogger(__name__)

_plugin_defaults_cache: dict[pathlib.Path, dict[str, Any]] = {}


def _candidate_paths(base_dir=None) -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    if base_dir:
        paths.append(pathlib.Path(base_dir).resolve() / "plugin_defaults.toml")
    paths.append(pathlib.Path("plugin_defaults.toml").resolve())
    return paths


def load_plugin_defaults(base_dir=None) -> tuple[dict[str, Any], pathlib.Path | None]:
    for path in _candidate_paths(base_dir):
        if not path.exists():
            continue
        cached = _plugin_defaults_cache.get(path)
        if cached is not None:
            return cached, path
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            if not isinstance(data, dict):
                data = {}
            _plugin_defaults_cache[path] = data
            return data, path
        except Exception as exc:
            logger.error("[plugin_config] Failed to parse %s: %s", path, exc)
            return {}, path
    return {}, None


def get_plugin_section(section: str, base_dir=None) -> tuple[dict[str, Any], pathlib.Path | None]:
    data, path = load_plugin_defaults(base_dir)
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
            return value, path
    return {}, path


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
