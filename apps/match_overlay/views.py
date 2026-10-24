"""TMF-native Match Overlay using existing Classic/Modern presentation."""

import re
from xml.sax.saxutils import escape


ML_ID = 86203


def text(value):
    value = re.sub(r'\$[lhp](?:\[[^\]]*\])?', '', str(value), flags=re.I)
    value = ''.join(char for char in value if 32 <= ord(char) <= 0xFFFF and not 0xD800 <= ord(char) <= 0xDFFF)
    return escape(value[:120], {'"': '&quot;'})


def render(values, names, match_score, map_score, stale=False):
    width = values['display/width']
    scale = width / 85
    def x(value):
        return f'{value * scale:.4f}'
    def label(px, py, size, caption, color='FFFF', align='left', font_scale=.9):
        return (f'<label posn="{x(px)} {py} .06" sizen="{x(size)} 2" textsize="1" '
                f'scale="{font_scale * min(1, scale):.4f}" halign="{align}" textcolor="{color}" text="{text(caption)}"/>')
    scores = ['--' if map_score is None else str(map_score[index]) for index in (0, 1)]
    title = 'Match Overlay' + (' - scores unavailable' if stale else '')
    parts = [f'<manialink id="{ML_ID}"><frame posn="{values["display/pos_x"]} {values["display/pos_y"]} 0">',
             f'<quad posn="0 0 .001" sizen="{width:.4f} 11.3" style="BgsPlayerCard" substyle="BgCardSystem"/>',
             f'<quad posn=".4 -.36 .002" sizen="{width - .8:.4f} 2" style="BgsPlayerCard" substyle="BgCardSystem"/>',
             '<quad posn=".6 -.15 .004" sizen="2.3 2.3" style="Icons128x128_1" substyle="Rankings"/>',
             '<label posn="3.2 -.55 .06" sizen="' + f'{width - 3.8:.4f}' +
             ' 1.5" textsize="1" scale=".9" textcolor="FFFF" text="' + text(title) + '"/>',
             f'<quad posn="{x(.4)} -2.8 .003" sizen="{x(.18)} 5.4" bgcolor="39FF"/>',
             f'<quad posn="{x(84.4)} -2.8 .003" sizen="{x(.18)} 5.4" bgcolor="F55F"/>',
             label(1.5, -3.4, 27, names[0], '39FF'), label(83.5, -3.4, 27, names[1], 'F55F', 'right'),
             label(36.5, -3.1, 10, scores[0], align='right', font_scale=1.4),
             label(48.5, -3.1, 10, scores[1], font_scale=1.4),
             label(42.5, -6.5, 25, 'CURRENT MAP', align='center', font_scale=.65),
             label(42.5, -9, 80, f'MATCH: {match_score[0]} - {match_score[1]}', align='center', font_scale=.8),
             '</frame></manialink>']
    return ''.join(parts)
