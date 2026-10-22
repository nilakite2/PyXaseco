from __future__ import annotations

import json
import tomllib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pyxaseco.management.config_store import edit_toml, revision, update_file

_edit_revisions = ContextVar('toml_edit_revisions', default=None)


@contextmanager
def revision_guard(path):
    file = Path(path).resolve()
    token = _edit_revisions.set({file: revision(file.read_bytes())})
    try:
        yield
    finally:
        _edit_revisions.reset(token)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f'Unsupported TOML scalar type: {type(value)!r}')


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return '[' + ', '.join(_format_value(item) for item in value) + ']'
    return _format_scalar(value)


def dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []

    def emit_table(table: dict[str, Any], prefix: str | None = None) -> None:
        scalar_items: list[tuple[str, Any]] = []
        table_items: list[tuple[str, dict[str, Any]]] = []

        for key, value in table.items():
            if isinstance(value, dict):
                table_items.append((key, value))
            else:
                scalar_items.append((key, value))

        if prefix is not None:
            if lines:
                lines.append('')
            lines.append(f'[{prefix}]')

        for key, value in scalar_items:
            lines.append(f'{key} = {_format_value(value)}')

        for key, value in table_items:
            new_prefix = f'{prefix}.{key}' if prefix else key
            emit_table(value, new_prefix)

    emit_table(data)
    return '\n'.join(lines).strip() + '\n'


def write_toml(path: str | Path, data: dict[str, Any]) -> None:
    update_file(Path(path), lambda _text: dump_toml(data), validator=tomllib.loads)


def read_toml(path: str | Path) -> dict[str, Any]:
    with Path(path).open('rb') as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


def update_toml_table_scalar(
    path: str | Path,
    table_path: list[str] | tuple[str, ...],
    key: str,
    value: Any,
) -> None:
    revisions = _edit_revisions.get()
    file = Path(path).resolve()
    saved = update_file(file, lambda text: edit_toml(text, (*table_path, key), value),
                        expected=revisions.get(file) if revisions else None, validator=tomllib.loads)
    if revisions is not None:
        revisions[file] = saved.revision


def move_loadout_entry(path: str | Path, entry: str, enabled: bool) -> dict[str, Any]:
    result = {}
    def change(text):
        data = tomllib.loads(text)
        loadout = data.get('loadout', {})
        active = [item for item in loadout.get('enabled', []) if item != entry]
        inactive = [item for item in loadout.get('disabled', []) if item != entry]
        (active if enabled else inactive).append(entry)
        updated = edit_toml(text, ('loadout', 'enabled'), active)
        updated = edit_toml(updated, ('loadout', 'disabled'), inactive)
        result.update(tomllib.loads(updated))
        return updated
    update_file(Path(path), change, validator=tomllib.loads)
    return result
