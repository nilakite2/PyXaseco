"""
ui/internal/toml_loader.py

Loads apps/ui/app_defaults.toml and converts the
ui or records_eyepiece defaults section to the nested-dict format that config.py expects.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from pyxaseco.app_config import get_app_defaults_path, load_app_defaults_file
from pyxaseco.core.config import display_path

logger = logging.getLogger(__name__)


def _records_eyepiece_section(base_dir: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path | None]:
    data, path = load_app_defaults_file('ui', base_dir)
    if not isinstance(data, dict):
        return {}, path
    for key in ('ui', 'records_eyepiece', 'plugin_records_eyepiece'):
        value = data.get(key, {})
        if isinstance(value, dict):
            return value, path
    return {}, path

def _uppercase_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k.upper(): _uppercase_keys(v) for k, v in obj.items()}
    return obj


def _wrap_scalars(obj: Any) -> Any:
    if isinstance(obj, dict):
        return [{k: _wrap_scalars(v) for k, v in obj.items()}]
    if isinstance(obj, list):
        return [_wrap_scalars(i) for i in obj]
    return [obj]


def _to_config_shape(data: dict) -> dict:
    data = _uppercase_keys(data)
    data = _wrap_scalars(data)
    return {'RECORDS_EYEPIECE': data}


def load_toml(path: pathlib.Path) -> dict:
    root_dir = path.parents[2] if len(path.parents) >= 3 else path.parent
    section, _ = _records_eyepiece_section(root_dir)
    return _to_config_shape(section if isinstance(section, dict) else {})

def find_and_load(base_dir: pathlib.Path) -> tuple[dict, pathlib.Path | None]:
    expected_path = get_app_defaults_path('ui', base_dir)
    section, path = _records_eyepiece_section(base_dir)
    raw = _to_config_shape(section if isinstance(section, dict) else {})
    root = raw.get('RECORDS_EYEPIECE')
    if not root:
        return {}, path or expected_path
    logger.info('[Records-Eyepiece] Loaded config from %s', display_path(path or expected_path))
    return raw, path or expected_path
