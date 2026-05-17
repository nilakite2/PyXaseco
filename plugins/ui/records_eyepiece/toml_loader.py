"""
records_eyepiece/toml_loader.py

Loads plugin_defaults.toml and converts the plugin_records_eyepiece section to
the nested-dict format that config.py expects.
"""

from __future__ import annotations

import logging
import pathlib
import tomllib
from typing import Any

logger = logging.getLogger(__name__)

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
    with path.open('rb') as fh:
        data = tomllib.load(fh)
    return _to_config_shape(data if isinstance(data, dict) else {})

def find_and_load(base_dir: pathlib.Path) -> tuple[dict, pathlib.Path | None]:
    import pathlib as _pl

    candidates_toml = [
        base_dir.resolve() / 'plugin_defaults.toml',
        _pl.Path('.').resolve() / 'plugin_defaults.toml',
        _pl.Path(__file__).resolve().parent.parent.parent / 'plugin_defaults.toml',
    ]
    for p in candidates_toml:
        if p.exists():
            try:
                with p.open('rb') as fh:
                    data = tomllib.load(fh)
                section = data.get('plugin_records_eyepiece', {})
                raw = _to_config_shape(section if isinstance(section, dict) else {})
                root = raw.get('RECORDS_EYEPIECE')
                if not root:
                    logger.info('[Records-Eyepiece] Ignoring empty TOML config at %s and falling back', p)
                    continue
                logger.info('[Records-Eyepiece] Loaded config from %s', p)
                return raw, p
            except Exception as e:
                logger.error('[Records-Eyepiece] Failed to parse %s: %s', p, e)

    return {}, None
