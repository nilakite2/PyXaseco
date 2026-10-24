"""Native TMF join/spectate links and existing Classic/Modern window shells."""

import math
import re
from xml.sax.saxutils import escape

from . import storage


ML_WIDGET = 86003
ML_WINDOW = 91800
ML_SUBWIN = 91801
OPEN, REFRESH, PREVIOUS, NEXT = range(8600000, 8600004)
PAGE_SIZE = 12
MODES = {0: 'Rounds', 1: 'TimeAttack', 2: 'Team', 3: 'Laps', 4: 'Stunts', 5: 'Cup'}


def text(value):
    value = str(value).replace('\n', ' ').replace('\r', ' ')[:160]
    value = re.sub(r'\$[lhp](?:\[[^\]]*\])?', '', value, flags=re.I)
    return escape(value, {'"': '&quot;'})


def label(x, y, width, caption, scale=.85, target=None):
    link = '' if target is None else f' manialink="{text(target)}" style="TextStaticSmall"'
    return (f'<label posn="{x} {y} .06" sizen="{width} 1.5" scale="{scale}" textsize="1" '
            f'text="{text(caption)}"{link}/>')


def counts(current, maximum):
    return f'{current}/{maximum or "?"}'


def widget(rows, values, own_login, rotation):
    peers = list(rows)
    if not peers:
        return f'<manialink id="{ML_WIDGET}"></manialink>'
    count = min(values['widget/entries'], len(peers))
    offset = rotation * count % len(peers)
    peers = (peers[offset:] + peers[:offset])[:count]
    width, height = values['widget/width'], 2.8 + 3.2 * count
    parts = [f'<manialink id="{ML_WIDGET}"><frame posn="{values["widget/pos_x"]} {values["widget/pos_y"]} 0">',
             f'<quad posn="0 0 .001" sizen="{width} {height}" style="BgsPlayerCard" substyle="BgCardSystem" action="{OPEN}"/>',
             f'<quad posn=".4 -.36 .002" sizen="{width - .8} 2" style="BgsPlayerCard" substyle="BgCardSystem"/>',
             '<quad posn=".6 -.15 .004" sizen="2.5 2.5" style="Icons128x128_1" substyle="United"/>',
             label(3.2, -.55, width - 3.7, 'Servers')]
    for i, row in enumerate(peers):
        y = -(3 + i * 3.2)
        state = storage.status(row, values['stale_seconds'])
        name = row['name'] + (' (here)' if row['login'] == own_login else '')
        parts.append(label(.6, y, width - 1, name))
        parts.append(label(.6, y - 1.3, width - 1,
            f'{counts(row["players"], row["maxplayers"])} players / {row["spectators"]} spec - {state}', .65))
    parts.extend(('<quad posn="0 0 .08" sizen="' + str(width) + ' ' + str(height) +
                  f'" bgcolor="0000" action="{OPEN}"/>', '</frame></manialink>'))
    return ''.join(parts)


def window(rows, values, own_login, page):
    from apps.ui.hud import append_window_start, append_window_end
    total = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = min(max(0, page), total - 1)
    parts = []
    append_window_start(parts, ml_window=ML_WINDOW, ml_subwin=ML_SUBWIN,
        title=f'Server Neighborhood | Page {page + 1}/{total}', icon_style='Icons128x128_1', icon_substyle='United')
    parts.append('<format textsize="1" textcolor="FFFF"/>')
    for x, width, caption in ((.6, 23, 'Server / Current Track'), (25, 10, 'Players'), (35, 10, 'Spectators'),
                               (46, 12, 'Mode / State'), (60, 7, 'Join'), (68, 8, 'Spectate')):
        parts.append(label(x, 0, width, caption))
    for i, row in enumerate(rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]):
        y = -(3 + i * 3.2)
        state = storage.status(row, values['stale_seconds'])
        parts.append(f'<quad posn=".3 {y + .25} .01" sizen="75.5 3.1" style="BgsPlayerCard" substyle="BgCardSystem"/>')
        parts.extend((label(.6, y, 23, row['name']), label(.6, y - 1.35, 23, row['map'] or '-', .65),
                      label(25, y, 9, counts(row['players'], row['maxplayers'])),
                      label(35, y, 10, counts(row['spectators'], row['maxspectators'])),
                      label(46, y, 12, MODES.get(row['mode'], '?'), .75), label(46, y - 1.35, 12, state, .65)))
        if row['login'] == own_login:
            parts.append(label(60, y, 15, 'You are here', .75))
        elif state in ('online', 'full'):
            storage.valid_login(row['login'])
            if state != 'full':
                parts.append(label(60, y, 7, 'Join', target='tmtp://#join=' + row['login']))
            parts.append(label(68, y, 8, 'Spectate', target='tmtp://#spectate=' + row['login']))
    if not rows:
        parts.append(label(.6, -4, 74, 'No server statuses found. Configure the same shared folder on linked instances.'))
    for x, icon, action in ((61, 'ArrowPrev', PREVIOUS if page else None),
                            (65, 'Refresh', REFRESH), (69, 'ArrowNext', NEXT if page + 1 < total else None)):
        if action is not None:
            parts.append(f'<quad posn="{x} -44 .07" sizen="2.8 2.8" style="Icons64x64_1" substyle="{icon}" action="{action}"/>')
    append_window_end(parts)
    return ''.join(parts), page
