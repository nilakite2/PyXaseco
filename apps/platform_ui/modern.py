"""TMF-native Modern renderers. No shared widget configuration is modified."""

from html import escape
import re

from pyxaseco.helpers import ML_ID_MAIN, clean_tm_text, format_time


LINK_TEXT_SCALE = 0.7


def heading_text(text):
    return clean_tm_text(str(text), keep_colors=True)


def external_link(text):
    """Keep inline link styling, with a native URL for reliable TMF activation."""
    protected = str(text).replace('$$', '\x00')
    matches = list(re.finditer(r'\$l\[([^\]\r\n]+)\](.*?)\$l', protected, re.IGNORECASE))
    if len(matches) != 1:
        return str(text), None
    match = matches[0]
    target = match[1]
    if target.lower().startswith('www.'):
        target = 'http://' + target
    if not target.lower().startswith(('http://', 'https://')) or any(ch.isspace() or ord(ch) < 32 for ch in target):
        return str(text), None
    return str(text), target


def _quad(x, y, z, width, height, color, action=None):
    click = '' if action is None else f' action="{int(action)}"'
    return (f'<quad posn="{x:.4f} {y:.4f} {z:.4f}" sizen="{max(0, width):.4f} {max(0, height):.4f}"'
            f' bgcolor="{escape(color, quote=True)}"{click}/>')


def _label(x, y, z, width, height, text, color, *, align='left', scale=1, textsize=1, url=None):
    if url is not None:
        scale = LINK_TEXT_SCALE
    # A URL without an explicit text style defaults to a button in TMF.
    link = '' if url is None else f' style="TextStaticSmall" url="{escape(url, quote=True)}"'
    return (f'<label posn="{x:.4f} {y:.4f} {z:.4f}" sizen="{max(0, width):.4f} {max(0, height):.4f}"'
            f' textsize="{textsize}" scale="{scale}" halign="{align}" autonewline="0"'
            f' textcolor="{escape(color, quote=True)}" text="{escape(str(text), quote=True)}"{link}/>')


def _icon(x, y, z, size, style, substyle):
    return (f'<quad posn="{x:.4f} {y:.4f} {z:.4f}" sizen="{size:.4f} {size:.4f}"'
            f' style="{escape(str(style), quote=True)}" substyle="{escape(str(substyle), quote=True)}"/>')


def record_widget(*, ml_id, cfg, entries, online, login, mode, palette, mark_online,
                  click_action=91805, is_live=False):
    """Fit actual records, retaining position, width, row spacing and panel action."""
    c = palette
    width = cfg.width
    line_h = max(1.0, cfg.row_height)
    visible = [entry for entry in entries if entry.get('score') is not None and entry.get('rank') != '--'][:cfg.entries]
    height = 2.65 + line_h * len(visible)
    parts = [f'<manialink id="{ml_id}"><frame posn="{cfg.pos_x:.4f} {cfg.pos_y:.4f} 0">',
             _quad(0, 0, .001, width, height, cfg.bg_color or c['background'], click_action),
             _quad(0, 0, .002, width, 2.55, c['header']),
             _quad(0, 0, .003, .16, height, c['accent'])]
    has_icon = bool(cfg.icon_style and cfg.icon_substyle)
    if has_icon:
        parts.append(_icon(.6, -.15, .004, 2.3, cfg.icon_style, cfg.icon_substyle))
    title_x = 3.2 if has_icon else .65
    parts.append(_label(title_x, -.6, .005, width - title_x - .6, 1.5, heading_text(cfg.title), c['text'], scale=.9))
    for line, entry in enumerate(visible):
        y = -(2.65 + line_h * line)
        is_self = entry.get('self') == 0
        rank = entry.get('rank')
        top = type(rank) is int and rank <= cfg.topcount
        background = c['self'] if is_self else c['row_alt' if line % 2 else 'row']
        parts.append(_quad(.35, y, .002, width - .7, line_h, background))
        if is_self:
            parts.append(_quad(.35, y, .003, .18, line_h, c['accent']))
        elif mark_online and entry.get('login') != login and entry.get('login') in online:
            parts.append(_quad(.42, y - line_h / 2 + .13, .003, .26, .26, c['online']))
        color = c['self_text'] if is_self else (c['top'] if top else c['text'])
        score = entry.get('score')
        score = '--' if score is None else (str(score) if is_live or mode == 4 or isinstance(score, str) else format_time(int(score)))
        rank_text = '--' if rank == '--' else ('' if rank is False else f'{rank}.')
        label_y = y - .28
        parts.extend((
            _label(2.2, label_y, .004, 1.45, line_h, rank_text, c['top'] if top else c['muted'], align='right', scale=.9),
            _label(6.0, label_y, .004, 5.4 if rank is False else 3.7, line_h, score, color, align='right', scale=.9),
            _label(6.35, label_y, .004, width - 6.9, line_h, entry.get('nickname', ''), c['text'], scale=.9),
        ))
    parts.append('</frame></manialink>')
    return ''.join(parts)


def command_window(header, rows, widths, page, total, palette, *, refresh_action=None,
                   subtitle=None, table_header=False, icon=None):
    """Native table windows using existing cell, navigation and refresh actions."""
    c = palette
    # The shared Classic pager pads short pages; this window fits its real rows.
    rows = [row for row in rows if row]
    width = min(116, max(60, widths[0] * 64))
    row_h = min(2.56, 75 / max(1, len(rows)))
    body_y = 8.5 if subtitle else 5.2
    height = body_y + len(rows) * row_h + 4.6
    parts = [f'<manialink id="{ML_ID_MAIN}"><frame posn="{-width / 2:.4f} {min(44, height / 2):.4f} 20">',
             _quad(0, 0, .01, width, height, c['background']),
             _quad(.8, -1.3, .02, width - 1.6, 3, c['header']),
             _quad(0, 0, .03, .3, height, c['accent'])]
    has_icon = isinstance(icon, (list, tuple)) and len(icon) >= 2 and icon[0] and icon[1]
    if has_icon:
        parts.append(_icon(1.8, -1, .04, 3.2, icon[0], icon[1]))
    title_x = 5.5 if has_icon else 1.8
    parts.extend((_label(title_x, -1.9, .04, width - title_x - 15, 3, heading_text(header), c['text']),
                  _label(width - 2, -1.9, .04, 12, 2, f'{page} / {total}', c['muted'], align='right')))
    if subtitle:
        parts.append(_label(2.2, -5.7, .04, width - 4.4, 2, subtitle, c['muted']))
    proportions = widths[1:] or [1]
    total_width = sum(proportions) or 1
    columns = [value / total_width * (width - 4.4) for value in proportions]
    for index, row in enumerate(rows):
        y = -(body_y + index * row_h)
        parts.append(_quad(1.5, y, .02, width - 3, row_h - .12,
                           c['header'] if table_header and index == 0 else c['row_alt' if index % 2 else 'row']))
        x = 2.2
        for col, cell in enumerate(row):
            col_width = width - 4.4 if len(row) == 1 else (columns[col] if col < len(columns) else width - x - 2.2)
            text = cell
            is_action = isinstance(cell, list)
            if is_action:
                text, action = cell
                parts.append(_quad(x - .3, y, .03, col_width - .3, row_h - .12, c['selection'], action))
            text, url = (str(text), None) if is_action else external_link(text)
            text = text.replace('{#black}', '$' + c['text'][:3])
            parts.append(_label(x, y - .45, .04, col_width - .6, row_h, text,
                                c['accent'] if table_header and col == 2 and text else c['text'],
                                scale=min(1, row_h / 2.56), url=url))
            x += col_width
    footer = -(height - 3.9)
    def nav(x, substyle, action):
        parts.append(f'<quad posn="{x:.4f} {footer:.4f} 0.04" sizen="2.8 2.8" halign="center"'
                     f' style="Icons64x64_1" substyle="{substyle}" action="{action}"/>')
    if page > 1:
        nav(3.3, 'ArrowFirst', -4)
        nav(width * .25, 'ArrowPrev', -2)
        if total > 5:
            nav(7, 'ArrowFastPrev', -3)
    nav(width / 2, 'Close', 0)
    if refresh_action is not None:
        nav(width / 2 + 4, 'Refresh', refresh_action)
    if page < total:
        nav(width * .75, 'ArrowNext', 2)
        nav(width - 3.3, 'ArrowLast', 4)
        if total > 5:
            nav(width - 7, 'ArrowFastNext', 3)
    parts.append('</frame></manialink>')
    return ''.join(parts)


def local_records(**kwargs):
    return record_widget(**kwargs)


def tracklist_controls(*, action, queue_position, palette):
    """Fit queue controls below the existing card details, inside its 17.75 x 9.2 area."""
    parts = []
    if queue_position:
        parts.append(_label(.8, -8, .07, 14, 1.6, f'Queued #{queue_position}',
                            palette['accent'], scale=.6))
    if action is not None:
        caption = '- Remove' if queue_position else '+ Queue'
        parts.extend((_quad(10.6, -7.8, .06, 6.4, 1.25, palette['selection'], action),
                      _label(13.8, -8, .07, 10, 1.6, caption, palette['text'], align='center', scale=.6)))
    return ''.join(parts)


def picker_window(header, rows, widths, page, total, palette):
    return command_window(header, rows, widths, page, total, palette,
                          subtitle='Select a style. /uistyle default follows the server.', table_header=True,
                          icon=['Icons64x64_1', 'Windowed'])
