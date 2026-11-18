"""Bounded per-player HUD files and geometry for registered race pages."""

from hashlib import sha256
from math import isclose, isfinite
from dataclasses import dataclass, fields
import os
import re
import tempfile
import tomllib
import xml.etree.ElementTree as ET


# Stable preference keys; page IDs are the adapters, not the persisted identity.
PANELS = {
    'map': ('Current track', ('91805', '8585001')),
    'local_records': ('Local Records', ('91812',)),
    'external_records': ('External Records', ('91811',)),
    'live_rankings': ('Live Rankings', ('91813',)),
    'checkpoint_count': ('Checkpoint counter', ('91832',)),
    'splits': ('Checkpoint splits', ('91834', '8585004')),
    'clock': ('Clock', ('91806',)),
    'track_count': ('Track count', ('91809',)),
    'game_mode': ('Game mode', ('91807',)),
    'visitors': ('Visitors', ('91808',)),
    'players': ('Players / spectators', ('91837',)),
    'ladder_limit': ('Ladder limits', ('91838',)),
    'current_rank': ('Current ranking', ('91844',)),
    'tmx': ('TMX', ('91849',)),
    'toplist': ('Toplist', ('91810',)),
    'favorite': ('Add to favorites', ('91835',)),
    'discord': ('Discord', ('5834287',)),
    'force_play': ('Force play', ('5834288',)),
    'menu': ('Menu button', ('3830000', '8585000')),
    'admin_panel': ('Admin panel', ('3',)),
    'records_panel': ('Records panel', ('4',)),
    'vote_panel': ('Vote panel', ('5',)),
    'donate_panel': ('Donate panel', ('6',)),
    'stats_panel': ('Your Stats', ('9',)),
    'fast_records': ('FAST records', ('8585002',)),
    'team': ('FAST Team scores', ('8585005',)),
    'best_finishes': ('Best Finishes', ('342312',)),
    'best_cps': ('Best CPs', ('123123456',)),
    'best_runs': ('Best Runs', ('342313',)),
    'best_secs': ('Best Sectors', ('0815470000122',)),
    'best_cp_times': ('Best CP Times', ('92001', '92002')),
    'cp_live': ('CP Live', ('1928378', '1928379')),
    'karma': ('ManiaKarma', ('91103', '91104', '91105', '91106', '91107')),
    'ztrack': ('zTrack', ('19861111',)),
    'sponsor_banner': ('Sponsor banner', ('5834292',)),
    'server_neighborhood': ('Server neighborhood', ('86003',)),
    'cgps': ('Curated GPS', ('5834289',)),
    'alternate_scoretable': ('Alternate scoretable button', ('86105',)),
    'banner': ('Server banner', ('5834290',)),
    'allbutton': ('Quick-chat buttons', ('10', '11')),
    'round_score': ('Round score', ('91831',)),
    'donation_widget': ('Donation widget', ('91843',)),
    'winning_payout': ('Winning payout', ('91842',)),
}
VISIBILITY_ONLY = frozenset((
    'best_finishes', 'best_cps', 'best_runs', 'best_secs', 'best_cp_times',
    'cp_live', 'karma', 'ztrack', 'sponsor_banner', 'server_neighborhood',
    'cgps', 'alternate_scoretable', 'banner', 'allbutton', 'round_score',
    'donation_widget', 'winning_payout',
))
BY_PAGE = {page: key for key, (_title, pages) in PANELS.items() for page in pages}
LEGACY_PANEL_TYPES = {
    'admin_panel': 'admin', 'records_panel': 'records', 'donate_panel': 'donate',
    'vote_panel': 'vote', 'stats_panel': 'stats',
}
POSITION_STEPS = (.1, 1, 10)
MAX_BYTES = 64 * 1024
MAX_STYLES = 32
MIN_SCALE, MAX_SCALE = .6, 1.5
LIMITS = {'dx': (-160, 160), 'dy': (-120, 120), 'scale': (MIN_SCALE, MAX_SCALE)}
DEFAULTS = {'hidden': False, 'dx': 0, 'dy': 0, 'scale': 1}
DENSITIES = ('standard', 'compact', 'minimal')
_ESSENTIAL = frozenset(('menu', 'map', 'checkpoint_count', 'splits', 'ztrack'))
_COMPACT = frozenset((
    'map', 'local_records', 'external_records', 'fast_records', 'live_rankings',
    'checkpoint_count', 'splits', 'clock', 'track_count', 'game_mode', 'visitors',
    'players', 'ladder_limit', 'current_rank', 'tmx', 'toplist', 'favorite',
    'discord', 'force_play', 'admin_panel', 'records_panel', 'vote_panel',
    'donate_panel', 'stats_panel', 'team', 'best_finishes', 'best_cps', 'best_runs',
    'best_secs', 'best_cp_times', 'cp_live', 'karma', 'sponsor_banner',
))
_CENTER_ZONE = 16.0
_HUD_EDGE = 64.0
_LEFT_TILES = frozenset(('visitors', 'track_count', 'clock', 'force_play', 'discord',
                         'players', 'game_mode', 'ladder_limit', 'current_rank', 'tmx', 'toplist', 'favorite'))
_RIGHT_RAIL = frozenset(('karma', 'local_records', 'external_records', 'live_rankings', 'fast_records', 'sponsor_banner'))
_LEFT_TILE_ORIGIN = (-63.9, 47.8)
_LEFT_TILE_SIZE = (4.6, 6.5)
_LEFT_TILE_PITCH = (4.3, 6.1)
_LEFT_TILE_GAP = .15
_RIGHT_RAIL_TOP = 33.2

# Stock anchor -> tested Compact anchor, before scaling and spacing the HUD.
# Match both coordinates so independently positioned widgets keep their anchors.
_COMPACT_ANCHORS = {
    '91805': ((49.05, 48), (49.45, 48)),        # Eyepiece challenge
    '91832': ((-7.9, -34.1), (-6.8, -34.1)),   # Checkpoint counter
    '91806': ((-54.5, 47.8), (-55.3, 47.8)),   # Clock
    '91809': ((-59.2, 47.8), (-59.6, 47.8)),   # Track count
    '91837': ((-54.5, 41.1), (-55.3, 41.7)),   # Players / spectators
    '5834287': ((-59.2, 41.1), (-59.6, 41.7)), # Discord
    '5834288': ((-63.9, 41.1), (-63.9, 41.7)), # Force Play
    '3830000': ((-50, 47.8), (-52.4, 47.8)),   # FuFi button and popup
    '5834290': ((-64.4, 22.7), (-64.5, 23.6)), # Server banner, when enabled
    '342312': ((35, 48), (37, 48)),            # Best Finishes
    '91812': ((49.2, 22.1), (49.4, 22.1)),     # TA local records
    '91811': ((49.2, .7), (49.4, .9)),         # TA external records
    **dict.fromkeys(PANELS['karma'][1], ((49.2, 32.86), (49.4, 32.76))),
    **dict.fromkeys(PANELS['best_cp_times'][1], ((49.7, -20), (50.3, -11.9))),
    **dict.fromkeys(PANELS['cp_live'][1], ((-64.4, 19), (-64.4, 20))),
}
PAGE = re.compile(r'<manialink\b[^>]*?(?:/>|>.*?</manialink>)', re.DOTALL)
PAGE_ID = re.compile(r'\bid=["\']([^"\']+)["\']')


@dataclass(frozen=True)
class CompactLayout:
    scale: float = .85
    edge_shift: float = 1.5
    tile_spacing: float = .90
    rail_spacing: float = .85

    @classmethod
    def from_config(cls, values):
        limits = {'scale': (.60, 1), 'edge_shift': (0, 4),
                  'tile_spacing': (.60, 1), 'rail_spacing': (.60, 1)}
        if not isinstance(values, dict):
            raise ValueError('Compact HUD settings must be a table.')
        defaults = cls()
        result = {}
        for item in fields(cls):
            value = values.get(item.name, getattr(defaults, item.name))
            low, high = limits[item.name]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f'{item.name} must be a number between {low:g} and {high:g}.')
            result[item.name] = float(value)
        return cls(**result)


COMPACT_DEFAULT = CompactLayout()


def text_geometry(size, scale=1.0):
    """Use the scale attribute for the fractional part of a native text size."""
    if not isfinite(size) or size <= 0:
        size = 1.0
    base = max(1, int(size))
    return base, scale * size / base


def panel_offsets_from_config(values):
    if not isinstance(values, dict):
        raise ValueError('Legacy panel positions must be a table.')
    offsets = {}
    for panel, name in LEGACY_PANEL_TYPES.items():
        table = values.get(name, {})
        if not isinstance(table, dict):
            raise ValueError(f'{name} panel positions must be a table.')
        position = {}
        for field, key in (('offset_x', 'dx'), ('offset_y', 'dy')):
            value = table.get(field, 0)
            low, high = LIMITS[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f'{name}.{field} must be between {low:g} and {high:g}.')
            if value:
                position[key] = value
        if position:
            offsets[panel] = position
    return offsets


def profile_path(root, login):
    return root / 'apps' / 'ui' / 'player_huds' / (sha256(login.encode('utf-8')).hexdigest() + '.toml')


def validate_styles(styles):
    if not isinstance(styles, dict) or len(styles) > MAX_STYLES:
        raise ValueError('Too many saved HUD styles or invalid layout.')
    result = {}
    for preset, panels in styles.items():
        if (not isinstance(preset, str) or not re.fullmatch(r'0|[1-9][0-9]{0,9}', preset)
                or int(preset) > 2147483647 or not isinstance(panels, dict) or len(panels) > len(PANELS)):
            raise ValueError('Invalid HUD style ID or panel list.')
        clean = {}
        for name, values in panels.items():
            if name not in PANELS or not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
                raise ValueError('Unknown HUD panel or setting.')
            overrides = {}
            for key, value in values.items():
                if key == 'hidden':
                    if type(value) is not bool:
                        raise ValueError('HUD visibility must be true or false.')
                else:
                    low, high = LIMITS[key]
                    if type(value) not in (int, float) or not low <= value <= high:
                        raise ValueError('HUD position or size is out of range.')
                if key == 'hidden' or value != DEFAULTS[key] or key == 'scale':
                    overrides[key] = value
            if overrides:
                clean[name] = overrides
        if clean:
            result[preset] = clean
    return result


def read_profile(path, *, with_density=False):
    from pyxaseco.management.installation import safe_path

    path = safe_path(path)
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return ({}, 'standard') if with_density else {}
    if len(raw) > MAX_BYTES:
        raise ValueError('HUD profile is too large.')
    document = tomllib.loads(raw.decode('utf-8-sig'))
    if type(document.get('version')) is not int or document['version'] != 1 or document.keys() - {'version', 'styles', 'density'}:
        raise ValueError('Unsupported HUD profile format.')
    density = document.get('density', 'standard')
    if density not in DENSITIES:
        raise ValueError('Unknown HUD layout.')
    styles = validate_styles(document.get('styles', {}))
    return (styles, density) if with_density else styles


def write_profile(path, styles, density='standard'):
    from pyxaseco.management.installation import safe_path

    path = safe_path(path)
    styles = validate_styles(styles)
    if density not in DENSITIES:
        raise ValueError('Unknown HUD layout.')
    if not styles and density == 'standard':
        path.unlink(missing_ok=True)
        return styles
    lines = ['version = 1']
    if density != 'standard':
        lines.append(f'density = "{density}"')
    for preset, panels in sorted(styles.items(), key=lambda item: int(item[0])):
        for name, values in sorted(panels.items()):
            lines.extend(('', f'[styles."{preset}".{name}]'))
            lines.extend(f'{key} = {str(value).lower()}' for key, value in sorted(values.items()))
    raw = ('\n'.join(lines) + '\n').encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('HUD profile is too large.')
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.hud-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return styles


def page_id(fragment):
    match = PAGE_ID.search(fragment.partition('>')[0])
    return match[1] if match else ''


def numbers(value, count):
    parts = tuple(map(float, value.split()))
    if len(parts) != count or not all(isfinite(part) for part in parts):
        raise ValueError('Invalid ManiaLink geometry.')
    return parts


def position(node):
    value = node.get('posn', '0 0 0')
    count = 2 if len(value.split()) == 2 else 3
    parts = numbers(value, count)
    return (*parts, 0.0) if count == 2 else parts


def inspect(fragment, *, visibility_only=False):
    if '<!DOCTYPE' in fragment.upper():
        return None, False
    try:
        page = ET.fromstring(fragment)
        if not any(node.tag in ('quad', 'label') for node in page.iter()):
            return None, False
        if visibility_only:
            return page, False
        if page.attrib.keys() - {'id'}:
            return page, False
        for node in page.iter():
            if node is page:
                continue
            if node.tag not in ('frame', 'quad', 'label', 'format') or 'pos' in node.attrib or 'size' in node.attrib:
                return page, False
            position(node)
            if 'sizen' in node.attrib:
                numbers(node.attrib['sizen'], 2)
            if 'scale' in node.attrib:
                scale = numbers(node.attrib['scale'], 1)[0]
                if node.tag not in ('label', 'quad') or not 0 < scale <= 10:
                    return page, False
        return page, True
    except (ET.ParseError, ValueError):
        return None, False


def defaults(panel, density, compact=COMPACT_DEFAULT):
    if density == 'minimal' and panel not in _ESSENTIAL:
        return {'hidden': True}
    if density == 'compact' and panel in _COMPACT:
        return {'scale': compact.scale}
    return {}


def effective(panel, density, overrides, compact=COMPACT_DEFAULT):
    return defaults(panel, density, compact) | overrides


def _compact_x(x, shift):
    # Keep centered HUDs centered and respect layouts already at the edge.
    if x < -_CENTER_ZONE:
        return max(min(x, -_HUD_EDGE), x - shift)
    if x > _CENTER_ZONE:
        return min(max(x, _HUD_EDGE), x + shift)
    return x


def _compact_position(panel, x, y, settings):
    if panel in _LEFT_TILES and -66 <= x <= -44 and 34 <= y <= 48:
        # Move all tile anchors around a shared corner, not toward separate edges.
        origin_x, origin_y = _LEFT_TILE_ORIGIN
        spacing_x, spacing_y = (max(settings.tile_spacing, (size * settings.scale + _LEFT_TILE_GAP) / pitch)
                                for size, pitch in zip(_LEFT_TILE_SIZE, _LEFT_TILE_PITCH))
        return (origin_x + (x - origin_x) * spacing_x,
                origin_y + (y - origin_y) * spacing_y)
    if panel in _RIGHT_RAIL and x >= 40 and -38 <= y <= _RIGHT_RAIL_TOP:
        # The native Prev/Best display sits above this rail and is not moved.
        y = _RIGHT_RAIL_TOP + (y - _RIGHT_RAIL_TOP) * max(settings.scale, settings.rail_spacing)
    return _compact_x(x, settings.edge_shift), y


def panel_geometry(identifier, x, y, overrides, density, compact=COMPACT_DEFAULT, *, server_offset=None):
    panel = BY_PAGE.get(identifier)
    fitted = density == 'compact' and (panel in _COMPACT or identifier in _COMPACT_ANCHORS)
    if panel in VISIBILITY_ONLY:
        overrides = {}
    values = effective(panel, density, overrides, compact)
    dx, dy, scale = (values.get(key, DEFAULTS[key]) for key in ('dx', 'dy', 'scale'))
    if fitted:
        anchors = _COMPACT_ANCHORS.get(identifier)
        if anchors and all(isclose(a, b, rel_tol=0, abs_tol=.0001) for a, b in zip((x, y), anchors[0])):
            x, y = anchors[1]
        if panel in _COMPACT:
            x, y = _compact_position(panel, x, y, compact)
    server_offset = server_offset or {}
    return x + dx + server_offset.get('dx', 0), y + dy + server_offset.get('dy', 0), scale


def _anchor(identifier, node):
    x, y, z = position(node)
    if identifier == '3830000' and node.tag == 'frame':
        # FuFi wraps its screen-positioned button in a template frame at (0, 0).
        button = node.find(f'quad[@action="{identifier}"]')
        if button is not None:
            bx, by, _ = position(button)
            x, y = x + bx, y + by
    return x, y, z


def transform(xml, overrides, density='standard', *, compact=COMPACT_DEFAULT, server_offsets=None):
    server_offsets = server_offsets or {}
    if (not overrides and not server_offsets and density == 'standard') or '<!DOCTYPE' in xml.upper():
        return xml

    def replace(match):
        fragment = match[0]
        identifier = page_id(fragment)
        panel = BY_PAGE.get(identifier)
        if panel is None:
            return fragment
        personal = (overrides or {}).get(panel, {})
        values = effective(panel, density, personal, compact)
        fitted = density == 'compact' and (panel in _COMPACT or identifier in _COMPACT_ANCHORS)
        server_offset = server_offsets.get(panel)
        if not values and not fitted and not server_offset:
            return fragment
        if values.get('hidden'):
            return f'<manialink id="{identifier}"></manialink>'
        if panel in VISIBILITY_ONLY and not fitted:
            return fragment
        page, adjustable = inspect(fragment)
        if not adjustable:
            return fragment
        top_level = [node for node in page if node.tag != 'format']
        if not top_level:
            return fragment
        anchor_x, anchor_y, _ = _anchor(identifier, top_level[0])
        x, y, scale = panel_geometry(identifier, anchor_x, anchor_y, personal, density, compact,
                                    server_offset=server_offset)
        if x == anchor_x and y == anchor_y and scale == 1:
            return fragment
        for node in top_level:
            px, py, pz = position(node)
            node.set('posn', f'{x + (px - anchor_x) * scale:.4f} {y + (py - anchor_y) * scale:.4f} {pz:.4f}')
        if scale != 1:
            top_level = set(top_level)
            for node in page.iter():
                if node is page:
                    continue
                if node not in top_level and 'posn' in node.attrib:
                    px, py, pz = position(node)
                    node.set('posn', f'{px * scale:.4f} {py * scale:.4f} {pz:.4f}')
                if 'sizen' in node.attrib:
                    width, height = numbers(node.attrib['sizen'], 2)
                    node.set('sizen', f'{width * scale:.4f} {height * scale:.4f}')
                if node.tag == 'label':
                    node.set('scale', f'{float(node.get("scale", 1)) * scale:.4f}')
        return ET.tostring(page, encoding='unicode')

    return PAGE.sub(replace, xml)
