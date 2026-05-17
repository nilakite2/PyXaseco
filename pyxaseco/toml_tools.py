from __future__ import annotations

import json
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
