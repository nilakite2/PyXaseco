"""Cached, explicit-ID UI presets. Template files are not discovered as presets."""

from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib

from pyxaseco.helpers import strip_colors
from .style import _normalise_style_block


MAX_ID = 2147483647
MODERN_PALETTE = {
    'background': '1118', 'header': '123A', 'row': '2236',
    'row_alt': '1126', 'accent': '3CFF', 'text': 'EFFF',
    'muted': '89AF', 'self': '164E', 'self_text': '9FFF',
    'top': 'FD8F', 'online': '7DAF', 'selection': '245F',
}


@dataclass(frozen=True)
class Preset:
    id: int
    name: str
    description: str = ''
    base: int = 0
    window: dict | None = field(default=None, compare=False)
    palette: dict | None = field(default=None, compare=False)


CLASSIC = Preset(0, 'Classic', 'Existing PyXaseco HUD and personal window style.')


def valid_id(value):
    return type(value) is int and 0 <= value <= MAX_ID


@dataclass
class Catalog:
    presets: dict[int, Preset] = field(default_factory=lambda: {0: CLASSIC})
    warnings: list[str] = field(default_factory=list)

    def resolve(self, selection, default):
        if valid_id(selection) and selection in self.presets:
            return self.presets[selection]
        return self.presets.get(default, CLASSIC) if valid_id(default) else CLASSIC


def load_catalog(root: Path) -> Catalog:
    catalog = Catalog()
    folder = root / 'apps/platform_ui'
    style_file = folder / 'styles.toml'
    styles = {}
    try:
        if style_file.is_file():
            styles = tomllib.loads(style_file.read_text(encoding='utf-8-sig')).get('styles', {})
            if not isinstance(styles, dict):
                raise ValueError('styles must be a table')
    except (OSError, ValueError):
        styles = {}
        catalog.warnings.append('Window style catalog unavailable; presets needing it will be skipped')
    paths = sorted((folder / 'uistyles/builtin').glob('*.toml')) + sorted((folder / 'uistyles/custom').glob('*.toml'))
    candidates = {}
    for path in paths:
        try:
            if path.stat().st_size > 32768:
                raise ValueError('preset file exceeds 32 KiB')
            data = tomllib.loads(path.read_text(encoding='utf-8-sig'))
            preset = data['preset']
            if set(data) - {'preset', 'palette'} or set(preset) - {'id', 'name', 'description', 'base', 'window_style'}:
                raise ValueError('unknown preset field')
            identifier = preset['id']
            builtin = path.parent.name == 'builtin'
            if not valid_id(identifier) or (builtin and identifier not in (0, 1)) or (not builtin and identifier < 2):
                raise ValueError('ID 0 is Classic; ID 1 is reserved for Modern; custom IDs start at 2')
            base = preset.get('base', 1 if identifier == 1 else 0)
            if type(base) is not int or base not in (0, 1) or (builtin and base != identifier):
                raise ValueError('base must be 0 (Classic) or 1 (Modern); builtins retain their own base')
            palette = None
            if base == 1:
                colors = data.get('palette', {})
                if not isinstance(colors, dict) or set(colors) - MODERN_PALETTE.keys():
                    raise ValueError('unknown palette field')
                if any(not isinstance(color, str) or not re.fullmatch(r'[0-9a-fA-F]{3,4}', color)
                       for color in colors.values()):
                    raise ValueError('palette colors must be 3 or 4 hexadecimal digits (TMF RGBA)')
                palette = {**MODERN_PALETTE, **colors}
            elif 'palette' in data:
                raise ValueError('palette overrides require Modern base 1')
            name = preset['name']
            description = preset.get('description', '')
            if not isinstance(name, str) or not name.strip() or len(name) > 60 or not isinstance(description, str):
                raise ValueError('invalid display name or description')
            name = strip_colors(name).replace('\n', ' ').replace('\r', ' ').strip()
            if not name:
                raise ValueError('display name must contain visible text')
            window = None
            if 'window_style' in preset:
                if builtin:
                    raise ValueError('Classic must retain the existing window style')
                style = preset['window_style']
                if not isinstance(style, str) or style not in styles or not isinstance(styles[style], dict):
                    raise ValueError('unknown window_style')
                window = _normalise_style_block(styles[style])
            item = Preset(identifier, name, description[:200], base, window, palette)
            candidates.setdefault(identifier, []).append(item)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            catalog.warnings.append(f'{path.name}: {exc}')
    for identifier, items in candidates.items():
        if len(items) != 1:
            catalog.warnings.append(f'Duplicate UI preset ID {identifier}: all conflicting files rejected')
        else:
            catalog.presets[identifier] = items[0]
    return catalog
