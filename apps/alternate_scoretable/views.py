"""Native TMF scoretable, shared Classic/Modern shell and bounded actions."""

import math
import re
from xml.sax.saxutils import escape

from pyxaseco.helpers import format_time
from apps.ui.hud import append_window_start, append_window_end
from apps.ui.config import BarWidgetCfg
from apps.ui.widgets.bar_widgets import (
    _bg_attrs, _bar_x, _bar_y, _bar_w, _bar_h, _bar_text_scale,
)
from .results import MODES


ML_WINDOW, ML_SUBWIN, ML_BUTTON = 86103, 86104, 86105
OPEN, CLOSE, PREVIOUS, NEXT, REFRESH, BACK = range(8610000, 8610006)
PLAYER_BASE = 8611000


def text(value):
    value = str(value).replace('\n', ' ').replace('\r', ' ')[:200]
    value = ''.join(char for char in value if 32 <= ord(char) <= 0xFFFF and not 0xD800 <= ord(char) <= 0xDFFF)
    value = re.sub(r'\$[lhp](?:\[[^\]]*\])?', '', value, flags=re.I)
    return escape(value, {'"': '&quot;'})


def label(x, y, width, caption, *, color='FFFF', scale=.8, action=None):
    link = '' if action is None else f' action="{action}"'
    return (f'<label posn="{x} {y} .06" sizen="{width} 1.7" textsize="1" scale="{scale}" '
            f'textcolor="{color}" text="{text(caption)}"{link}/>')


def metric(score, mode):
    return (str(score) if mode == 4 else format_time(score)) if score > 0 else '--'


def result(row, mode):
    if mode in (0, 4, 5):
        return str(row['score']) + ' pts' if row['score'] > 0 else '--'
    if mode == 3:
        return str(row['score']) + ' cps' if row['score'] > 0 else metric(row['time'], mode)
    return metric(row['time'], mode)


def elapsed(seconds):
    return f'{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}' if seconds else '--'


def shell(title):
    parts = []
    append_window_start(parts, ml_window=ML_WINDOW, ml_subwin=ML_SUBWIN, title=title,
                        icon_style='Icons128x128_1', icon_substyle='Rankings')
    return parts


def button(values):
    cfg = BarWidgetCfg(width=values['button/width'], height=values['button/height'],
                       bg_style=values['button/background_style'], bg_substyle=values['button/background_substyle'],
                       bg_color=values['button/background_color'], text_color=values['button/text_color'])
    width, height, center = cfg.width, cfg.height, cfg.width / 2
    return (f'<manialink id="{ML_BUTTON}"><frame posn="{values["button/pos_x"]} {values["button/pos_y"]} 0">'
            '<format textsize="1"/>'
            f'<quad posn="0 0 .001" sizen="{width:.4f} {height:.4f}"'
            f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, cfg.bg_color)} action="{OPEN}"/>'
            f'<quad posn="{_bar_x(cfg, .7):.4f} {_bar_y(cfg, -.3):.4f} .002"'
            f' sizen="{_bar_w(cfg, 3.35):.4f} {_bar_h(cfg, 3):.4f}" style="Icons128x128_1" substyle="Rankings"/>'
            f'<label posn="{center:.4f} {_bar_y(cfg, -3.4):.4f} .1"'
            f' sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center" scale=".9" text="VIEW"/>'
            f'<label posn="{center:.4f} {_bar_y(cfg, -4.9):.4f} .1"'
            f' sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
            f' textcolor="{text(cfg.text_color)}" scale="{_bar_text_scale(cfg, .6)}" text="SCORES"/>'
            f'<quad posn="0 0 .2" sizen="{width:.4f} {height:.4f}" bgcolor="0000" action="{OPEN}"/>'
            '</frame></manialink>')


def window(data, values, login, page=0, detail=None):
    rows, mode = data['rows'], data['mode']
    pages = max(1, math.ceil(len(rows) / values['entries']))
    page = max(0, min(page, pages - 1))
    parts = shell('Alternate Scoretable' + (f' | Page {page + 1}/{pages}' if detail is None else ' | Player'))
    # Own page ID: closing does not dismiss unrelated UI windows.
    parts = [part.replace(f'action="{ML_WINDOW}"', f'action="{CLOSE}"') for part in parts]
    if detail is not None and 0 <= detail < len(rows):
        row = rows[detail]
        fields = [('Player', row['name']), ('Login', row['login']),
                  ('Status', ('Spectator' if row['spectator'] else 'Player') if row['connected'] else 'Disconnected'),
                  ('Team', {0: 'Blue', 1: 'Red'}.get(row['team'], '-')),
                  ('Nation', row['nation']), ('Result', result(row, mode)),
                  ('Best This Map', metric(row['time'] if mode != 4 else row['score'], mode)),
                  ('Personal Best', metric(row['pb'], mode)), ('Finishes This Map', str(row['finishes'])),
                  ('Ladder Rank', str(row['ladder']) if row['ladder'] > 0 else '--'),
                  ('Online', elapsed(row['online']))]
        for index, (key, value) in enumerate(fields):
            parts.extend((label(.5, -index * 3, 23, key), label(24, -index * 3, 50, value)))
        parts.append(f'<quad posn="61 -44 .07" sizen="2.8 2.8" style="Icons64x64_1" substyle="ArrowPrev" action="{BACK}"/>')
    else:
        caption = f'{data["map"]} - {MODES.get(mode, "?")} | {data["players"]} players / {data["spectators"]} spectators'
        if mode == 2:
            caption = f'Blue: {data["teams"].get(0, "--")} | Red: {data["teams"].get(1, "--")} | ' + caption
        parts.append(label(.5, 0, 74, caption, scale=.75))
        columns = [('rank', '#', 3), ('name', 'Player', 24), ('result', 'Result', 10)]
        for key, caption, width in (('pb', 'Personal Best', 10), ('finishes', 'Finishes', 5),
                                    ('ladder', 'Ladder Rank', 9), ('online', 'Online', 9)):
            if values['columns/' + key]:
                columns.append((key, caption, width))
        columns[1] = ('name', 'Player', 24 + max(0, 75 - sum(col[2] for col in columns)))
        x = .5
        for _key, caption, width in columns:
            parts.append(label(x, -3, width - .3, caption, scale=.7))
            x += width
        start = page * values['entries']
        for index, row in enumerate(rows[start:start + values['entries']]):
            y, action = -5 - index * 1.85, PLAYER_BASE + start + index
            parts.append(f'<quad posn=".3 {y + .2} .01" sizen="75.5 1.8" style="BgsPlayerCard" substyle="BgCardSystem"/>')
            if row['login'] == login:
                parts.append(f'<quad posn=".3 {y + .2} .02" sizen="75.5 1.8" style="BgsPlayerCard" substyle="BgMediaTracker" action="{action}"/>')
            fields = {'rank': str(row['rank']) if row['rank'] > 0 else '-',
                'name': row['name'] + (' [spec]' if row['spectator'] else '') + (' [left]' if not row['connected'] else ''),
                'result': result(row, mode), 'pb': metric(row['pb'], mode), 'finishes': str(row['finishes']),
                'ladder': str(row['ladder']) if row['ladder'] > 0 else '--', 'online': elapsed(row['online'])}
            x = .5
            for key, _caption, width in columns:
                color = 'AAA9' if not row['connected'] else 'FFAF' if key == 'result' else 'FFFF'
                if mode == 2 and key == 'rank':
                    fields[key] = {0: 'B', 1: 'R'}.get(row['team'], '-')
                    color = {0: '39FF', 1: 'F55F'}.get(row['team'], color)
                parts.append(label(x, y, width - .3, fields[key], color=color, action=action if key == 'name' else None))
                x += width
        if not rows:
            parts.append(label(.5, -6, 74, 'No players or results available.'))
        if values['columns/pb'] and not data['pb_available']:
            parts.append(label(.5, -44, 57, 'PB database unavailable; showing cached/session PBs only.', scale=.65))
        for x, icon, action in ((61, 'ArrowPrev', PREVIOUS if page else None),
                                (65, 'Refresh', REFRESH), (69, 'ArrowNext', NEXT if page + 1 < pages else None)):
            if action is not None:
                parts.append(f'<quad posn="{x} -44 .07" sizen="2.8 2.8" style="Icons64x64_1" substyle="{icon}" action="{action}"/>')
    append_window_end(parts)
    return ''.join(parts), page
