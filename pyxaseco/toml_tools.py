from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any


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
    Path(path).write_text(dump_toml(data), encoding='utf-8')


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
    file_path = Path(path)
    lines = file_path.read_text(encoding='utf-8').splitlines()
    header = f"[{'.'.join(str(part) for part in table_path)}]"
    key_pattern = re.compile(rf'^\s*{re.escape(key)}\s*=')
    new_line = f'{key} = {_format_value(value)}'

    table_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == header:
            table_idx = idx
            break

    if table_idx is None:
        if lines and lines[-1].strip():
            lines.append('')
        lines.extend([header, new_line])
        file_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
        return

    insert_at = len(lines)
    for idx in range(table_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            insert_at = idx
            break
        if key_pattern.match(lines[idx]):
            lines[idx] = new_line
            file_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
            return

    lines.insert(insert_at, new_line)
    file_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')


def move_loadout_entry(path: str | Path, entry: str, enabled: bool) -> dict[str, Any]:
    data = read_toml(path)
    loadout = data.get('loadout')
    if not isinstance(loadout, dict):
        loadout = {}
        data['loadout'] = loadout

    enabled_list = loadout.get('enabled')
    disabled_list = loadout.get('disabled')
    if not isinstance(enabled_list, list):
        enabled_list = []
        loadout['enabled'] = enabled_list
    if not isinstance(disabled_list, list):
        disabled_list = []
        loadout['disabled'] = disabled_list

    enabled_list[:] = [item for item in enabled_list if item != entry]
    disabled_list[:] = [item for item in disabled_list if item != entry]

    target = enabled_list if enabled else disabled_list
    if entry not in target:
        target.append(entry)

    write_toml(path, data)
    return data
