"""Per-recipient presentation for existing native ManiaLink surfaces."""

from collections import OrderedDict
import logging
import re
import xml.etree.ElementTree as ET

from .modern import heading_text


logger = logging.getLogger(__name__)
PAGES = re.compile(r'<manialink\b[^>]*(?:/>|>.*?</manialink>)', re.DOTALL)
DECLARATION = re.compile(r'<\?xml[^>]*\?>')
COMPACT_SCORE_IDS = {'91815', '91816', '91831', '91834', '91845', '91846', '91847', '91848'} | {str(i) for i in range(91818, 91827)}
DECORATIVE_SKINS = {('BgsPlayerCard', 'BgRacePlayerLine')}
OPEN_CORNER = re.compile(
    r'^https?://maniacdn\.net/undef\.de/xaseco1/(?:mania-karma|records-eyepiece)/'
    r'edge-open-(ld|rd)-(?:dark|light)\.png$', re.IGNORECASE)


def _numbers(value, default):
    try:
        return [float(part) for part in value.split()]
    except (ValueError, AttributeError):
        return default


def _content_depths(parent, offset=0):
    """Account for nested frames when placing a flat card behind its content."""
    for node in parent:
        pos = _numbers(node.get('posn'), [])
        legacy = _numbers(node.get('pos'), [])
        depth = offset + (pos[2] if len(pos) == 3 else -64 * legacy[2] if len(legacy) == 3 else 0)
        if node.tag == 'frame':
            yield from _content_depths(node, depth)
        elif node.tag in ('label', 'entry', 'quad'):
            if node.tag != 'quad' or not node.get('style', '').startswith('Bgs') or node.get('image'):
                yield depth


def _remove_open_indicators(root):
    """Modern cards need no decorative open-corner images or replacement arrows."""
    changed = False
    for parent in root.iter():
        for node in list(parent):
            if node.tag != 'quad' or not OPEN_CORNER.fullmatch(node.get('image', '')):
                continue
            if any(key in node.attrib for key in ('action', 'url', 'manialink')):
                node.attrib.pop('image')
                node.set('bgcolor', '0000')
            else:
                parent.remove(node)
            changed = True
    return changed


def _style_cplive(root, palette):
    """Keep clickable CP Live surfaces from becoming opaque selection buttons."""
    changed = False
    for page in root.iter('manialink'):
        if page.get('id') not in ('1928378', '1928379'):
            continue
        for node in page.iter('quad'):
            if not node.get('style', '').startswith('Bgs') or node.get('image'):
                continue
            node.attrib.pop('style', None)
            node.attrib.pop('substyle', None)
            node.set('bgcolor', palette['header'] if page.get('id') == '1928378' else '0000')
            changed = True
    return changed


def _normalise_headers(root, palette):
    changed = False
    for frame in root.iter('frame'):
        children = list(frame)
        for bar in children:
            size = _numbers(bar.get('sizen'), [])
            pos = _numbers(bar.get('posn'), [])
            if bar.tag != 'quad' or bar.get('bgcolor') != palette['header'] or len(size) != 2 or len(pos) != 3:
                continue
            large = size[0] > 40 and 2.8 <= size[1] <= 3.2 and -1.4 <= pos[1] <= -1.2
            small = size[0] >= 8 and 1.9 <= size[1] <= 2.6 and -.8 <= pos[1] <= 0
            if not (large or small):
                continue
            titles = [node for node in children if node.tag == 'label'
                      and len(_numbers(node.get('posn'), [])) == 3
                      and (-2.1 <= _numbers(node.get('posn'), [0, 0, 0])[1] <= -1.6 if large else
                           -.8 <= _numbers(node.get('posn'), [0, 0, 0])[1] <= -.35)
                      and (not large or node.get('halign', 'left') != 'right')]
            if not titles:
                continue
            title = titles[0]
            before = dict(title.attrib)
            title.set('text', heading_text(title.get('text', '')))
            title.set('textsize', '1')
            title.set('scale', '1' if large else '0.9')
            title.attrib.pop('style', None)
            if small:
                width = size[0] + (.8 if pos[0] > .1 else 0)
                icons = [node for node in children if node.tag == 'quad'
                         and (node.get('style') or node.get('image'))
                         and len(_numbers(node.get('sizen'), [])) == 2
                         and max(_numbers(node.get('sizen'), [99, 99])) <= 4
                         and len(_numbers(node.get('posn'), [])) == 3
                         and -.3 <= _numbers(node.get('posn'), [0, -99, 0])[1] <= .1]
                title_x = 3.2 if icons else .65
                title_pos = _numbers(title.get('posn'), [0, 0, 0])
                title.set('posn', f'{title_x:.4f} -0.6000 {title_pos[2]:.4f}')
                title.set('sizen', f'{max(0, width - title_x - .6):.4f} 1.5000')
                title.set('halign', 'left')
                old_bar = dict(bar.attrib)
                bar.set('posn', f'0.0000 0.0000 {pos[2]:.4f}')
                bar.set('sizen', f'{width:.4f} 2.5500')
                changed |= old_bar != bar.attrib
                if icons:
                    icon = icons[0]
                    old_icon = dict(icon.attrib)
                    icon_pos = _numbers(icon.get('posn'), [0, 0, 0])
                    icon.set('posn', f'0.6000 -0.1500 {icon_pos[2]:.4f}')
                    icon.set('sizen', '2.3000 2.3000')
                    changed |= old_icon != icon.attrib
            changed |= before != title.attrib
    return changed


def _compact_score(page, palette):
    if page.get('id') not in COMPACT_SCORE_IDS:
        return
    for frame in page.iter('frame'):
        labels = [node for node in frame if node.tag == 'label' and node.get('text')]
        rows = sorted({round(-_numbers(node.get('posn'), [0, 0, 0])[1], 4)
                       for node in labels if len(_numbers(node.get('posn'), [])) == 3
                       and _numbers(node.get('posn'), [0, 0, 0])[1] <= -2.9})
        if not rows:
            continue
        step = min((b - a for a, b in zip(rows, rows[1:]) if b - a > .5), default=1.8)
        bottom = rows[-1] + step
        for node in frame:
            size = _numbers(node.get('sizen'), [])
            pos = _numbers(node.get('posn', '0 0 0'), [])
            if (node.tag == 'quad' and len(size) == 2 and len(pos) == 3
                    and (size[0] >= 10 or (size[0] <= .2 and node.get('bgcolor') == palette['accent']))
                    and size[1] > bottom and pos[1] >= -.1):
                node.set('sizen', f'{size[0]:.4f} {bottom:.4f}')
        for index, y in enumerate(rows):
            backgrounds = [node for node in frame if node.tag == 'quad'
                           and len(_numbers(node.get('sizen'), [])) == 2
                           and _numbers(node.get('sizen'), [0, 0])[0] >= 10]
            if not backgrounds:
                break
            width = max(_numbers(node.get('sizen'), [0, 0])[0] for node in backgrounds)
            frame.append(ET.Element('quad', posn=f'0.35 {-y + .25:.4f} 0.0015',
                                    sizen=f'{max(0, width - .7):.4f} {step:.4f}',
                                    bgcolor=palette['row_alt' if index % 2 else 'row']))


def style_xml(xml, palette):
    """Replace backdrop skins only; preserve content, inputs, actions and semantics."""
    if '<quad' not in xml or '<!DOCTYPE' in xml.upper():
        return xml
    try:
        root = ET.fromstring('<ui>' + DECLARATION.sub('', xml) + '</ui>')
    except ET.ParseError:
        logger.warning('[UIStyle] Could not parse a UI page; preserving its original markup')
        return xml
    changed = _remove_open_indicators(root)
    changed |= _style_cplive(root, palette)
    for parent in root.iter():
        seen = set()
        accent_added = False
        backdrop_depth = None
        for node in list(parent):
            if node.tag in ('label', 'format', 'entry'):
                color = node.get('textcolor', '').upper()
                if color[:3] in ('000', '333', 'FFF') and len(color) in (3, 4):
                    node.set('textcolor', palette['text'])
                    changed = True
            if node.tag != 'quad' or node.get('image'):
                continue
            skin = node.get('style', '')
            if (skin, node.get('substyle')) in DECORATIVE_SKINS:
                continue
            size = _numbers(node.get('sizen'), [])
            pos = _numbers(node.get('posn', '0 0 0'), [0, 0, 0])
            if (node.get('bgcolor', '').upper() == '3336' and size == [78.4, 53.7]
                    and pos[:2] == [.8, -.8]):
                # The shared legacy window repeats this overlay above its card.
                parent.remove(node)
                changed = True
                continue
            if skin.startswith('Bgs'):
                role = 'background'
                if 'action' in node.attrib and (len(size) != 2 or size[1] <= 4):
                    role = 'selection'
                elif len(size) == 2 and size[1] <= 2.6:
                    role = 'header' if len(pos) == 3 and pos[1] > -2 else 'row'
                if (role == 'background' and len(size) == 2 and size[0] >= 10 and size[1] >= 3
                        and len(pos) == 3 and 'pos' not in node.attrib):
                    # Border skins can sit above icons; a filled replacement cannot.
                    if backdrop_depth is None:
                        backdrop_depth = min(_content_depths(parent), default=pos[2]) - .001
                    pos[2] = min(pos[2], backdrop_depth)
                    node.set('posn', ' '.join(f'{value:.4f}' for value in pos))
                node.attrib.pop('style', None)
                node.attrib.pop('substyle', None)
                node.set('bgcolor', palette[role])
                changed = True
                if not accent_added and len(size) == 2 and len(pos) == 3 and size[0] >= 10 and size[1] >= 3:
                    parent.append(ET.Element('quad', posn=f'{pos[0]:.4f} {pos[1]:.4f} {pos[2] + .0005:.4f}',
                                             sizen=f'0.14 {size[1]:.4f}', bgcolor=palette['accent']))
                    accent_added = True
                # Repeated legacy backdrop layers would otherwise compound opacity.
                identity = tuple(sorted(node.attrib.items()))
                if identity in seen:
                    parent.remove(node)
                seen.add(identity)
            elif (node.get('bgcolor', '').upper() in ('3336', '29F9')
                  and len(size) == 2 and size[0] > 70 and len(pos) == 3 and pos[0] == .8):
                role = 'header' if node.get('bgcolor', '').upper() == '29F9' else 'background'
                node.set('bgcolor', palette[role])
                changed = True
    changed |= _normalise_headers(root, palette)
    for page in root.iter('manialink'):
        if page.get('id') in COMPACT_SCORE_IDS:
            _compact_score(page, palette)
            changed = True
    return ''.join(ET.tostring(child, encoding='unicode') for child in root) if changed else xml


class Presentation:
    def __init__(self, service):
        self.service = service
        self.sources = OrderedDict()
        self.source_bytes = 0
        self.cache = OrderedDict()
        self.cache_bytes = 0

    def groups(self, method, *args):
        if method not in ('SendDisplayManialinkPage', 'SendDisplayManialinkPageToLogin'):
            return None
        targeted = method.endswith('ToLogin')
        xml, lifetime, hide = args[1:] if targeted else args
        players = self.service.aseco.server.players
        recipients = args[0].split(',') if targeted else [p.login for p in players.all()]
        groups = {}
        for login in recipients:
            player = players.get_player(login)
            preset = self.service.resolve(player) if player is not None else None
            output = xml
            if preset is not None and preset.base == 1 and not (preset.window is not None and re.search(r'<manialink\s+id=["\']1["\']', xml)):
                key = (preset.id, tuple(sorted(preset.palette.items())), xml)
                output = self.cache.get(key)
                if output is None:
                    output = style_xml(xml, preset.palette)
                    cost = len(xml.encode('utf-8')) + len(output.encode('utf-8'))
                    if cost <= 2_000_000:
                        self.cache[key] = output
                        self.cache_bytes += cost
                        while len(self.cache) > 128 or self.cache_bytes > 2_000_000:
                            old_key, old_xml = self.cache.popitem(last=False)
                            self.cache_bytes -= len(old_key[2].encode('utf-8')) + len(old_xml.encode('utf-8'))
                else:
                    self.cache.move_to_end(key)
            groups.setdefault(output, []).append(login)
        if not groups or (len(groups) == 1 and next(iter(groups)) == xml):
            return None
        return [('SendDisplayManialinkPageToLogin', (','.join(logins[start:start + 100]), output, lifetime, hide))
                for output, logins in groups.items() for start in range(0, len(logins), 100)]

    def remember(self, method, *args):
        targeted = method.endswith('ToLogin')
        xml, lifetime, hide = args[1:] if targeted else args
        players = self.service.aseco.server.players
        recipients = args[0].split(',') if targeted else [p.login for p in players.all()]
        if lifetime or hide:
            for fragment in PAGES.findall(xml):
                match = re.search(r'\bid=["\']([^"\']+)["\']', fragment)
                if match:
                    for login in recipients:
                        self._forget((login, match[1]))
        if lifetime or hide:
            return
        for fragment in PAGES.findall(xml):
            match = re.search(r'\bid=["\']([^"\']+)["\']', fragment)
            if not match or match[1] in ('0', '1', '91800', '91801', '91811', '91812', '91813'):
                continue  # Modal windows are not reopened; record widgets rebuild from data.
            for login in recipients:
                self._forget((login, match[1]))
                self.sources[(login, match[1])] = fragment
                self.source_bytes += len(fragment.encode('utf-8'))
                self.sources.move_to_end((login, match[1]))
        while len(self.sources) > 4096 or self.source_bytes > 4_000_000:
            _key, fragment = self.sources.popitem(last=False)
            self.source_bytes -= len(fragment.encode('utf-8'))

    def _forget(self, key):
        fragment = self.sources.pop(key, None)
        if fragment is not None:
            self.source_bytes -= len(fragment.encode('utf-8'))

    def discard(self, login):
        for key in list(self.sources):
            if key[0] == login:
                self._forget(key)

    async def refresh(self, player):
        from pyxaseco.core.widget_delivery import deliver_ui
        fragments = [xml for (login, _page), xml in self.sources.items() if login == player.login]
        for xml in fragments:
            if not self.service.connected(player):
                break
            await deliver_ui(self.service.aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)
