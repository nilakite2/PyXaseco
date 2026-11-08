"""Bounded per-player HUD files and geometry for registered race pages."""

from hashlib import sha256
from math import isfinite
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
    'stats_panel': ('Stats panel', ('9',)),
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
MAX_BYTES = 64 * 1024
MAX_STYLES = 32
MIN_SCALE, MAX_SCALE = .6, 1.5
LIMITS = {'dx': (-126, 126), 'dy': (-94, 94), 'scale': (MIN_SCALE, MAX_SCALE)}
DEFAULTS = {'hidden': False, 'dx': 0, 'dy': 0, 'scale': 1}
PAGE = re.compile(r'<manialink\b[^>]*?(?:/>|>.*?</manialink>)', re.DOTALL)
PAGE_ID = re.compile(r'\bid=["\']([^"\']+)["\']')


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
                if value != DEFAULTS[key]:
                    overrides[key] = value
            if overrides:
                clean[name] = overrides
        if clean:
            result[preset] = clean
    return result


def read_profile(path):
    from pyxaseco.management.installation import safe_path

    path = safe_path(path)
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}
    if len(raw) > MAX_BYTES:
        raise ValueError('HUD profile is too large.')
    document = tomllib.loads(raw.decode('utf-8-sig'))
    if type(document.get('version')) is not int or document['version'] != 1 or document.keys() - {'version', 'styles'}:
        raise ValueError('Unsupported HUD profile format.')
    return validate_styles(document.get('styles', {}))


def write_profile(path, styles):
    from pyxaseco.management.installation import safe_path

    path = safe_path(path)
    styles = validate_styles(styles)
    if not styles:
        path.unlink(missing_ok=True)
        return styles
    lines = ['version = 1']
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
            numbers(node.get('posn', '0 0 0'), 3)
            if 'sizen' in node.attrib:
                numbers(node.attrib['sizen'], 2)
            if 'scale' in node.attrib:
                scale = numbers(node.attrib['scale'], 1)[0]
                if node.tag != 'label' or not 0 < scale <= 10:
                    return page, False
        return page, True
    except (ET.ParseError, ValueError):
        return None, False


def transform(xml, overrides):
    if not overrides or '<!DOCTYPE' in xml.upper():
        return xml

    def replace(match):
        fragment = match[0]
        identifier = page_id(fragment)
        panel = BY_PAGE.get(identifier)
        values = overrides.get(panel)
        if not values:
            return fragment
        if values.get('hidden'):
            return f'<manialink id="{identifier}"></manialink>'
        if panel in VISIBILITY_ONLY:
            return fragment
        page, adjustable = inspect(fragment)
        if not adjustable:
            return fragment
        dx, dy, scale = (values.get(key, DEFAULTS[key]) for key in ('dx', 'dy', 'scale'))
        top_level = [node for node in page if node.tag != 'format']
        anchor_x, anchor_y, _ = numbers(top_level[0].get('posn', '0 0 0'), 3)
        x = min(62, max(-62, anchor_x + dx)) if dx else anchor_x
        y = min(46, max(-46, anchor_y + dy)) if dy else anchor_y
        for node in top_level:
            px, py, pz = numbers(node.get('posn', '0 0 0'), 3)
            node.set('posn', f'{x + (px - anchor_x) * scale:.4f} {y + (py - anchor_y) * scale:.4f} {pz:.4f}')
        if scale != 1:
            top_level = set(top_level)
            for node in page.iter():
                if node is page:
                    continue
                if node not in top_level and 'posn' in node.attrib:
                    px, py, pz = numbers(node.attrib['posn'], 3)
                    node.set('posn', f'{px * scale:.4f} {py * scale:.4f} {pz:.4f}')
                if 'sizen' in node.attrib:
                    width, height = numbers(node.attrib['sizen'], 2)
                    node.set('sizen', f'{width * scale:.4f} {height * scale:.4f}')
                if node.tag == 'label':
                    node.set('scale', f'{float(node.get("scale", 1)) * scale:.4f}')
        return ET.tostring(page, encoding='unicode')

    return PAGE.sub(replace, xml)
