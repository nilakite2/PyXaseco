"""
pyxaseco/helpers.py — Shared utility functions for plugins.

Port of:
  - includes/basic.inc.php  (formatTime, formatTimeH, formatText, stripColors, isLANLogin)
  - includes/manialinks.inc.php (display_manialink, display_manialink_multi, event handler)

TMF-only.
"""

from __future__ import annotations
import re
import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


# ---------------------------------------------------------------------------
# Time formatting  (mirrors basic.inc.php)
# ---------------------------------------------------------------------------

def format_time(ms: int, hsec: bool = True) -> str:
    """
    Format milliseconds as a TM race time string.
      sub-minute :  SS.hh   (e.g. 23.50)
      < 1 hour   :  M:SS.hh (e.g. 1:26.14)
      >= 1 hour  :  H:MM:SS.hh (e.g. 1:26:14.23)

    PHP formatTime() collapses all times to total-minutes (showing 86:14.23 instead of
    1:26:14.23) and emits a leading colon for sub-minute (:23.50).  TM itself displays
    H:MM:SS.hh, so we use the more correct form here.
    """
    if ms == -1:
        return '???'

    hundredths = (ms % 1000) // 10
    total_s    = ms // 1000
    hours      = total_s // 3600
    minutes    = (total_s % 3600) // 60
    seconds    = total_s % 60

    if hours > 0:
        if hsec:
            return f'{hours}:{minutes:02d}:{seconds:02d}.{hundredths:02d}'
        return f'{hours}:{minutes:02d}:{seconds:02d}'

    if minutes > 0:
        if hsec:
            return f'{minutes}:{seconds:02d}.{hundredths:02d}'
        return f'{minutes}:{seconds:02d}'

    # sub-minute — no leading colon
    if hsec:
        return f'{seconds}.{hundredths:02d}'
    return f'{seconds}'


def format_time_h(ms: int, hsec: bool = True) -> str:
    """
    Port of PHP formatTimeH().
    Formats ms as HH:MM:SS.hh (or HH:MM:SS).
    """
    if ms == -1:
        return '???'

    s = str(ms)
    start = len(s) - 3
    if start >= 0:
        hseconds = s[start:start + 2]
    else:
        hseconds = s[:max(0, len(s) - 1)].zfill(2)[-2:]

    total_s = ms // 1000
    hours   = total_s // 3600
    rem     = total_s - hours * 3600
    minutes = rem // 60
    seconds = rem - minutes * 60

    if hsec:
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{hseconds}'
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------

def format_text(text: str, *args) -> str:
    """Replace {1}, {2}, … placeholders with args."""
    for i, arg in enumerate(args, 1):
        text = text.replace('{' + str(i) + '}', str(arg))
    return text


def strip_colors(text: str, for_tm: bool = True) -> str:
    """
    Strip TM colour/style codes.
    for_tm=True  -> surviving $$ become $$ (for TM display)
    for_tm=False -> surviving $$ become $  (for log messages)
    """
    if not text:
        return text
    text = text.replace('$$', '\x00')
    text = re.sub(r'\$[hlp](.*?)(?:\[.*?\](.*?))*(?:\$[hlp]|$)',
                  r'\1\2', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\$(?:[0-9a-fA-F]{1,3}|[^][hlpHLP]|$)', '', text)
    text = re.sub(r'\$(?=[][])', '', text)
    text = text.replace('\x00', '$$' if for_tm else '$')
    return text


def strip_sizes(text: str, for_tm: bool = True) -> str:
    """Strip only $n, $w, $o size tags."""
    text = text.replace('$$', '\x00')
    text = re.sub(r'\$[nwoNWO]', '', text)
    return text.replace('\x00', '$$' if for_tm else '$')


def clean_tm_text(text: str, keep_colors: bool = True) -> str:
    """
    TMF-safe text cleanup for UI rendering.

    keep_colors=True:
      preserve color codes while removing links and unsafe style/control tags.

    keep_colors=False:
      strip color/style tags entirely via strip_colors(), but still keep the
      UTF-8 / control cleanup shared with the colored path.
    """
    if not text:
        return ''

    text = validate_utf8(str(text))
    text = ''.join(ch for ch in text if ord(ch) <= 0xFFFF)
    text = text.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    text = text.replace('$$', '\x00')

    # Remove h/l/p link wrappers while preserving their visible text.
    text = re.sub(
        r'\$[hlp](.*?)(?:\[.*?\](.*?))*(?:\$[hlp]|$)',
        r'\1\2',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if keep_colors:
        # preserve colors, remove link/control/style tags that can destabilize ML labels
        text = re.sub(r'\$[shwiplongtzSHWIPLONGTZ]', '', text)
    else:
        text = strip_colors(text, for_tm=True)

    text = text.replace('\x00', '$$')
    return ' '.join(text.split())


def safe_manialink_text(text: str, keep_colors: bool = True) -> str:
    """Clean TM text and escape it for ManiaLink XML attributes."""
    return html.escape(clean_tm_text(text, keep_colors=keep_colors), quote=True)


def is_lan_login(login: str) -> bool:
    """Detect LAN logins by their IP-style suffix."""
    n = r'(?:25[0-5]|2[0-4]\d|[01]?\d\d|\d)'
    pattern = rf'(?:/{n}\.{n}\.{n}\.{n}:\d+|_{n}\.{n}\.{n}\.{n}_\d+)$'
    return bool(re.search(pattern, login))


def validate_utf8(text: str) -> str:
    """Ensure valid UTF-8."""
    try:
        return text.encode('utf-8', errors='replace').decode('utf-8')
    except Exception:
        return text


# ---------------------------------------------------------------------------
# ManiaLink IDs
# ---------------------------------------------------------------------------

ML_ID_MAIN   = '1'   # Main pop-up window
ML_ID_CP     = '2'   # CheckPoints panel
ML_ID_ADMIN  = '3'   # Admin panel
ML_ID_RECS   = '4'   # Records panel
ML_ID_VOTE   = '5'   # Vote panel
ML_ID_DONATE = '6'   # Donate panel
ML_ID_MSG    = '7'   # Messages window


def _esc(text: str) -> str:
    """HTML-escape text for ManiaLink XML."""
    return html.escape(validate_utf8(str(text)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def display_manialink(aseco: 'Aseco', login: str, header: str,
                      icon: list, data: list, widths: list, button: str):
    """
    Display a single-page ManiaLink window to a player.

    icon:   [style, substyle] or [style, substyle, size_offset]
    data:   list of rows; each row is a list of column values
            (or [text, action_id] for clickable cells); [] = spacer row
    widths: [total_width, col1_width, col2_width, ...]
    button: label for the close button
    """
    import asyncio

    player = aseco.server.players.get_player(login)
    if not player:
        return
    style = player.style if player.style else {}

    if not style:
        xml = _build_plain_window(header, data, widths, button)
    else:
        xml = _build_styled_window(header, icon, data, widths, button, style)

    xml = aseco.format_colors(xml)
    # Send a single-page window with autoclose enabled.
    asyncio.ensure_future(
        aseco.client.query_ignore_result(
            'SendDisplayManialinkPageToLogin', login, xml, 0, True
        )
    )


def display_manialink_multi(aseco: 'Aseco', player: 'Player'):
    """
    Display the current page of a multi-page ManiaLink window.
    """
    import asyncio
    asyncio.ensure_future(_send_multipage(aseco, player))


def show_help(aseco: 'Aseco', player: 'Player', show_admin: bool = False,
              disp_all: bool = False, width: float = 0.3):
    """
    Display help for chat commands.
    """
    import asyncio

    cmds = {name: cmd for name, cmd in aseco._chat_commands.items()
            if cmd.isadmin == show_admin}

    if not disp_all:
        # Show the available command names in a single compact message.
        kind = 'admin' if show_admin else 'chat'
        head = aseco.format_colors(f'{{#interact}}Currently supported {kind} commands:\n')
        msg  = head + ', '.join(sorted(cmds.keys()))
        asyncio.ensure_future(
            aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', msg, player.login
            )
        )
        return

    head = f'Currently supported {"admin" if show_admin else "chat"} commands:'
    prefix = '$f00... ' if show_admin else '$f00/'
    rows = [[f'{prefix}{name}', cmd.help] for name, cmd in sorted(cmds.items())]

    pages_data = [rows[i:i + 15] for i in range(0, max(len(rows), 1), 15)]
    player.msgs = [[1, head, [1.3, width, 1.3 - width],
                    ['Icons64x64_1', 'TrackInfo', -0.01]]]
    player.msgs.extend(pages_data)
    display_manialink_multi(aseco, player)


# ---------------------------------------------------------------------------
# ManiaLink event handler
# ---------------------------------------------------------------------------

def setup_manialink_events(aseco: 'Aseco'):
    """
    Register the core ManiaLink page-answer handler and panel on/off hooks.
    """
    aseco.register_event('onPlayerManialinkPageAnswer', _event_manialink)
    # Reset key window layers at end of race.
    aseco.register_event('onEndRace', _allwindows_off)


async def _allwindows_off(aseco: 'Aseco', _data=None):
    """
    Clear the main window, records panel, and donate panel at end of race.
    """
    xml = (f'<manialinks>'
           f'<manialink id="{ML_ID_MAIN}"></manialink>'
           f'<manialink id="{ML_ID_RECS}"></manialink>'
           f'<manialink id="{ML_ID_DONATE}"></manialink>'
           f'</manialinks>')
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', xml, 0, False)


async def _event_manialink(aseco: 'Aseco', answer: list):
    """
    Handle ManiaLink page-answer events for the main popup window.

    Action routing:
      action  0          -> close main window
      action -4..-2, 1-4 -> page navigation for multi-page windows
      action -6..36      -> passed through; plugin_panels.py handles the rest
      action outside -6..36 -> ignored (left to other handlers)
    """
    if len(answer) < 3:
        return

    login  = answer[1]
    action = int(answer[2])

    # Leave actions outside -6..36 to other handlers.
    if action < -6 or action > 36:
        return

    # action 0 = close main window
    if action == 0:
        xml = f'<manialink id="{ML_ID_MAIN}"></manialink>'
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPageToLogin', login, xml, 0, False
        )
        return

    # Actions -4..-2 and 1-4 = multi-page navigation
    # Action 1 = "current page" (display_manialink_multi triggers this)
    if action not in (-4, -3, -2, 1, 2, 3, 4):
        # Actions -6..-5 and 5..36 handled by plugin_panels and other plugins
        return

    player = aseco.server.players.get_player(login)
    if not player or not player.msgs or len(player.msgs) < 2:
        return

    meta = player.msgs[0]
    if not isinstance(meta, list):
        return

    total   = len(player.msgs) - 1
    current = meta[0]

    if action == 1:
        pass                                    # stay on current page
    elif action == -2:
        current = max(1, current - 1)
    elif action == 2:
        current = min(total, current + 1)
    elif action == -3:
        current = max(1, current - 5)
    elif action == 3:
        current = min(total, current + 5)
    elif action == -4:
        current = 1
    elif action == 4:
        current = total

    player.msgs[0][0] = current
    await _send_multipage(aseco, player)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _send_multipage(aseco: 'Aseco', player: 'Player'):
    """
    Send the current page of player.msgs.
    PHP event_manialink sends with autoclose=false for multi-page.
    """
    if not player.msgs or len(player.msgs) < 2:
        return

    meta = player.msgs[0]
    if not isinstance(meta, list):
        return

    page_idx    = meta[0]           # 1-based
    total_pages = len(player.msgs) - 1

    if page_idx < 1 or page_idx > total_pages:
        return

    rows   = player.msgs[page_idx]
    header = meta[1] if len(meta) > 1 else ''
    widths = list(meta[2]) if len(meta) > 2 else [1.0]
    icon   = list(meta[3]) if len(meta) > 3 else ['Icons64x64_1', 'TrackInfo']

    # All pages use the height of page 1 so the window doesn't resize on navigation.
    page1_len = len(player.msgs[1]) if total_pages >= 1 else len(rows)
    if len(rows) < page1_len:
        # Pad current page rows to page1 length with empty spacer rows
        rows = list(rows) + [[] for _ in range(page1_len - len(rows))]

    style = player.style if player.style else {}
    xml   = _build_multi_page_window(header, icon, rows, widths,
                                     page_idx, total_pages, style)
    xml = aseco.format_colors(xml)

    # Keep autoclose disabled for multi-page windows.
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin', player.login, xml, 0, False
    )


def _build_multi_page_window(header, icon, rows, widths, page, total, style) -> str:
    if not style:
        return _build_plain_multi_page_window(header, rows, widths, page, total)
    return _build_styled_multi_page_window(header, icon, rows, widths, page, total, style)


# ---------------------------------------------------------------------------
# Plain window builder (no style)
# ---------------------------------------------------------------------------

def _build_plain_window(header, data, widths, button) -> str:
    """Build plain TMN-style window markup."""
    tsp = 'B'
    txt = '333' + tsp
    bgd = 'FFF' + tsp
    spc = 'DDD' + tsp
    w   = widths[0]

    xml = (f'<manialink id="{ML_ID_MAIN}" posx="{w / 2:.3f}" posy="0.47">'
           f'<background bgcolor="{bgd}" bgborderx="0.01" bgbordery="0.01"/>\n'
           f'<format textsize="3" textcolor="{txt}"/>\n')

    xml += (f'<line><cell bgcolor="{spc}" width="{w:.3f}">'
            f'<text> $o{_esc(header)}</text></cell></line>\n')
    xml += f'<format textsize="2" textcolor="{txt}"/>\n'
    xml += f'<line><cell bgcolor="{bgd}" width="{w:.3f}"><text>$</text></cell></line>\n'

    for row in data:
        xml += '<line height=".046">'
        if row:
            if len(row) > 1:
                for i in range(len(widths) - 1):
                    cw   = widths[i + 1]
                    cell = row[i] if i < len(row) else ''
                    if isinstance(cell, list):
                        xml += (f'<cell bgcolor="{bgd}" width="{cw:.3f}">'
                                f'<text action="{cell[1]}">  $o{_esc(cell[0])}</text></cell>')
                    else:
                        xml += (f'<cell bgcolor="{bgd}" width="{cw:.3f}">'
                                f'<text>  $o{_esc(cell)}</text></cell>')
            else:
                xml += (f'<cell bgcolor="{bgd}" width="{w:.3f}">'
                        f'<text>  $o{_esc(row[0])}</text></cell>')
        else:
            xml += f'<cell bgcolor="{bgd}" width="{w:.3f}"><text>$</text></cell>'
        xml += '</line>\n'

    xml += (f'<line><cell bgcolor="{bgd}" width="{w:.3f}"><text>$</text></cell></line>\n'
            f'<line height=".046"><cell bgcolor="{bgd}" width="{w:.3f}">'
            f'<text halign="center" action="0">$o{_esc(button)}</text></cell></line>'
            f'</manialink>')
    return xml


def _build_plain_multi_page_window(header, data, widths, page, total) -> str:
    """Build plain TMN-style multi-page window markup."""
    tsp = 'B'
    txt = '333' + tsp
    bgd = 'FFF' + tsp
    spc = 'DDD' + tsp
    w   = widths[0]

    xml = (f'<manialink id="{ML_ID_MAIN}" posx="{w / 2:.3f}" posy="0.47">'
           f'<background bgcolor="{bgd}" bgborderx="0.01" bgbordery="0.01"/>\n'
           f'<format textsize="3" textcolor="{txt}"/>\n')

    # Header with page counter
    xml += (f'<line><cell bgcolor="{spc}" width="{w - 0.12:.3f}">'
            f'<text> $o{_esc(header)}</text></cell>'
            f'<cell bgcolor="{spc}" width="0.12">'
            f'<text halign="right">$n({page}/{total})</text></cell></line>\n')
    xml += f'<format textsize="2" textcolor="{txt}"/>\n'
    xml += f'<line><cell bgcolor="{bgd}" width="{w:.3f}"><text>$</text></cell></line>\n'

    for row in data:
        xml += '<line height=".046">'
        if row:
            if len(row) > 1:
                for i in range(len(widths) - 1):
                    cw   = widths[i + 1]
                    cell = row[i] if i < len(row) else ''
                    if isinstance(cell, list):
                        xml += (f'<cell bgcolor="{bgd}" width="{cw:.3f}">'
                                f'<text action="{cell[1]}">  $o{_esc(cell[0])}</text></cell>')
                    else:
                        xml += (f'<cell bgcolor="{bgd}" width="{cw:.3f}">'
                                f'<text>  $o{_esc(cell)}</text></cell>')
            else:
                xml += (f'<cell bgcolor="{bgd}" width="{w:.3f}">'
                        f'<text>  $o{_esc(row[0])}</text></cell>')
        else:
            xml += f'<cell bgcolor="{bgd}" width="{w:.3f}"><text>$</text></cell>'
        xml += '</line>\n'

    xml += f'<line><cell bgcolor="{bgd}" width="{w:.3f}"><text>$</text></cell></line>\n'

    # Navigation buttons
    add5 = total > 5
    butw = (w - (0.22 if add5 else 0)) / 3
    xml += '<line height=".046">'

    if page > 1:
        if add5:
            xml += f'<cell bgcolor="{bgd}" width="0.11"><text halign="center" action="-3">$oPrev5</text></cell>'
        xml += f'<cell bgcolor="{bgd}" width="{butw:.3f}"><text halign="center" action="-2">$oPrev</text></cell>'
    else:
        if add5:
            xml += f'<cell bgcolor="{bgd}" width="0.11"><text>$</text></cell>'
        xml += f'<cell bgcolor="{bgd}" width="{butw:.3f}"><text>$</text></cell>'

    xml += f'<cell bgcolor="{bgd}" width="{butw:.3f}"><text halign="center" action="0">$oClose</text></cell>'

    if page < total:
        xml += f'<cell bgcolor="{bgd}" width="{butw:.3f}"><text halign="center" action="2">$oNext</text></cell>'
        if add5:
            xml += f'<cell bgcolor="{bgd}" width="0.11"><text halign="center" action="3">$oNext5</text></cell>'
    else:
        xml += f'<cell bgcolor="{bgd}" width="{butw:.3f}"><text>$</text></cell>'
        if add5:
            xml += f'<cell bgcolor="{bgd}" width="0.11"><text>$</text></cell>'

    xml += '</line></manialink>'
    return xml


# ---------------------------------------------------------------------------
# Styled window builder (TMF style)
# ---------------------------------------------------------------------------

def _s(style, path) -> str:
    """Safe nested style dict lookup: 'HEADER.TEXTSIZE' -> style[HEADER][0][TEXTSIZE][0]"""
    try:
        parts = path.split('.')
        v = style
        for p in parts:
            v = v[p.upper()][0] if isinstance(v, dict) else v[0]
        return str(v)
    except (KeyError, IndexError, TypeError):
        return ''


def _build_styled_window(header, icon, data, widths, button, style) -> str:
    """Build styled TMF-style window markup."""
    hsize = float(_s(style, 'HEADER.TEXTSIZE') or 0.06)
    bsize = float(_s(style, 'BODY.TEXTSIZE') or 0.04)
    w     = widths[0]
    lines = len(data)

    xml = (f'<manialink id="{ML_ID_MAIN}"><frame pos="{w / 2:.3f} 0.47 0">'
           f'<quad size="{w:.3f} {0.11 + hsize + lines * bsize:.3f}"'
           f' style="{_s(style, "WINDOW.STYLE")}" substyle="{_s(style, "WINDOW.SUBSTYLE")}"/>\n')

    # Header bar
    xml += (f'<quad pos="-{w / 2:.3f} -0.01 -0.1" size="{w - 0.02:.3f} {hsize:.3f}"'
            f' halign="center" style="{_s(style, "HEADER.STYLE")}"'
            f' substyle="{_s(style, "HEADER.SUBSTYLE")}"/>\n')

    if isinstance(icon, list) and len(icon) >= 2:
        isize = hsize + (icon[2] if len(icon) > 2 else 0)
        xml += (f'<quad pos="-0.055 -0.045 -0.2" size="{isize:.3f} {isize:.3f}"'
                f' halign="center" valign="center"'
                f' style="{icon[0]}" substyle="{icon[1]}"/>\n')
        xml += (f'<label pos="-0.10 -0.025 -0.2" size="{w - 0.12:.3f} {hsize:.3f}"'
                f' halign="left" style="{_s(style, "HEADER.TEXTSTYLE")}"'
                f' text="{_esc(header)}"/>\n')
    else:
        xml += (f'<label pos="-0.03 -0.025 -0.2" size="{w - 0.05:.3f} {hsize:.3f}"'
                f' halign="left" style="{_s(style, "HEADER.TEXTSTYLE")}"'
                f' text="{_esc(header)}"/>\n')

    # Body background
    xml += (f'<quad pos="-{w / 2:.3f} -{0.02 + hsize:.3f} -0.1"'
            f' size="{w - 0.02:.3f} {0.02 + lines * bsize:.3f}"'
            f' halign="center" style="{_s(style, "BODY.STYLE")}"'
            f' substyle="{_s(style, "BODY.SUBSTYLE")}"/>\n')
    xml += f'<format style="{_s(style, "BODY.TEXTSTYLE")}"/>\n'

    cnt = 0
    for row in data:
        cnt += 1
        if row:
            if len(row) > 1:
                for i in range(len(widths) - 1):
                    x_off = sum(widths[1:i + 1]) if i > 0 else 0
                    cw    = widths[i + 1] if i + 1 < len(widths) else widths[-1]
                    cell  = row[i] if i < len(row) else ''
                    y     = hsize - 0.013 + cnt * bsize
                    yl    = hsize - 0.008 + cnt * bsize
                    if isinstance(cell, list):
                        xml += (f'<quad pos="-{0.015 + x_off:.3f} -{y:.3f} -0.15"'
                                f' size="{cw - 0.03:.3f} {bsize + 0.005:.3f}"'
                                f' halign="left" style="{_s(style, "BUTTON.STYLE")}"'
                                f' substyle="{_s(style, "BUTTON.SUBSTYLE")}" action="{cell[1]}"/>\n')
                        xml += (f'<label pos="-{0.025 + x_off:.3f} -{yl:.3f} -0.2"'
                                f' size="{cw - 0.05:.3f} {0.02 + bsize:.3f}"'
                                f' halign="left" style="{_s(style, "BODY.TEXTSTYLE")}"'
                                f' text="{_esc(cell[0])}"/>\n')
                    else:
                        xml += (f'<label pos="-{0.025 + x_off:.3f} -{yl:.3f} -0.2"'
                                f' size="{cw - 0.05:.3f} {0.02 + bsize:.3f}"'
                                f' halign="left" style="{_s(style, "BODY.TEXTSTYLE")}"'
                                f' text="{_esc(cell)}"/>\n')
            else:
                yl = hsize - 0.008 + cnt * bsize
                xml += (f'<label pos="-0.025 -{yl:.3f} -0.2"'
                        f' size="{w - 0.04:.3f} {0.02 + bsize:.3f}"'
                        f' halign="left" style="{_s(style, "BODY.TEXTSTYLE")}"'
                        f' text="{_esc(row[0])}"/>\n')

    # Anchor the close button below the window body.
    xml += (f'<quad pos="-{w / 2:.3f} -{0.04 + hsize + lines * bsize:.3f} -0.2"'
            f' size="0.06 0.06" halign="center"'
            f' style="Icons64x64_1" substyle="Close" action="0"/>\n')
    xml += '</frame></manialink>'

    black = _s(style, 'WINDOW.BLACKCOLOR')
    if black:
        xml = xml.replace('{#black}', black)
    return xml


def _build_styled_multi_page_window(header, icon, data, widths, page, total, style) -> str:
    """Build styled TMF-style multi-page window markup."""
    hsize = float(_s(style, 'HEADER.TEXTSIZE') or 0.06)
    bsize = float(_s(style, 'BODY.TEXTSIZE') or 0.04)
    w     = widths[0]

    # All pages must have the same window height (page 1 height is the reference)
    lines = len(data)
    # Note: caller (_send_multipage) passes page1_lines via widths tuple if needed;
    # we normalise here using the data length directly since _send_multipage passes page1
    # row count separately through a closure — see _send_multipage for details.
    # The max() is applied in _send_multipage before calling this function.

    xml = (f'<manialink id="{ML_ID_MAIN}"><frame pos="{w / 2:.3f} 0.47 0">'
           f'<quad size="{w:.3f} {0.11 + hsize + lines * bsize:.3f}"'
           f' style="{_s(style, "WINDOW.STYLE")}" substyle="{_s(style, "WINDOW.SUBSTYLE")}"/>\n')

    # Header
    xml += (f'<quad pos="-{w / 2:.3f} -0.01 -0.1" size="{w - 0.02:.3f} {hsize:.3f}"'
            f' halign="center" style="{_s(style, "HEADER.STYLE")}"'
            f' substyle="{_s(style, "HEADER.SUBSTYLE")}"/>\n')

    if isinstance(icon, list) and len(icon) >= 2:
        isize = hsize + (icon[2] if len(icon) > 2 else 0)
        xml += (f'<quad pos="-0.055 -0.045 -0.2" size="{isize:.3f} {isize:.3f}"'
                f' halign="center" valign="center"'
                f' style="{icon[0]}" substyle="{icon[1]}"/>\n')
        xml += (f'<label pos="-0.10 -0.025 -0.2" size="{w - 0.25:.3f} {hsize:.3f}"'
                f' halign="left" style="{_s(style, "HEADER.TEXTSTYLE")}"'
                f' text="{_esc(header)}"/>\n')
    else:
        xml += (f'<label pos="-0.03 -0.025 -0.2" size="{w - 0.18:.3f} {hsize:.3f}"'
                f' halign="left" style="{_s(style, "HEADER.TEXTSTYLE")}"'
                f' text="{_esc(header)}"/>\n')

    # Page counter label.
    xml += (f'<label pos="-{w - 0.02:.3f} -0.025 -0.2" size="0.12 {hsize:.3f}"'
            f' halign="right" style="{_s(style, "HEADER.TEXTSTYLE")}"'
            f' text="$n({page}/{total})"/>\n')

    # Body background
    xml += (f'<quad pos="-{w / 2:.3f} -{0.02 + hsize:.3f} -0.1"'
            f' size="{w - 0.02:.3f} {0.02 + lines * bsize:.3f}"'
            f' halign="center" style="{_s(style, "BODY.STYLE")}"'
            f' substyle="{_s(style, "BODY.SUBSTYLE")}"/>\n')
    xml += f'<format style="{_s(style, "BODY.TEXTSTYLE")}"/>\n'

    cnt = 0
    for row in data:
        cnt += 1
        if row:
            if len(row) > 1:
                for i in range(len(widths) - 1):
                    if i >= len(row):
                        continue
                    x_off = sum(widths[1:i + 1]) if i > 0 else 0
                    cw    = widths[i + 1]
                    cell  = row[i]
                    if isinstance(cell, list):
                        xml += (f'<quad pos="-{0.015 + x_off:.3f}'
                                f' -{hsize - 0.013 + cnt * bsize:.3f} -0.15"'
                                f' size="{cw - 0.03:.3f} {bsize + 0.005:.3f}"'
                                f' halign="left" style="{_s(style, "BUTTON.STYLE")}"'
                                f' substyle="{_s(style, "BUTTON.SUBSTYLE")}" action="{cell[1]}"/>\n')
                        xml += (f'<label pos="-{0.025 + x_off:.3f}'
                                f' -{hsize - 0.008 + cnt * bsize:.3f} -0.2"'
                                f' size="{cw - 0.05:.3f} {0.02 + bsize:.3f}"'
                                f' halign="left" style="{_s(style, "BODY.TEXTSTYLE")}"'
                                f' text="{_esc(cell[0])}"/>\n')
                    else:
                        xml += (f'<label pos="-{0.025 + x_off:.3f}'
                                f' -{hsize - 0.008 + cnt * bsize:.3f} -0.2"'
                                f' size="{cw - 0.05:.3f} {0.02 + bsize:.3f}"'
                                f' halign="left" style="{_s(style, "BODY.TEXTSTYLE")}"'
                                f' text="{_esc(cell)}"/>\n')
            else:
                xml += (f'<label pos="-0.025 -{hsize - 0.008 + cnt * bsize:.3f} -0.2"'
                        f' size="{w - 0.04:.3f} {0.02 + bsize:.3f}"'
                        f' halign="left" style="{_s(style, "BODY.TEXTSTYLE")}"'
                        f' text="{_esc(row[0])}"/>\n')

    # Navigation buttons.
    add5     = total > 5
    footer_y = 0.045 + hsize + lines * bsize   # nav buttons y
    close_y  = 0.04  + hsize + lines * bsize   # close button y (0.005 higher)

    def _nav(x: float, substyle: str, action: int | None) -> str:
        act = f' action="{action}"' if action is not None else ''
        return (f'<quad pos="-{x:.3f} -{footer_y:.3f} -0.2"'
                f' size="0.055 0.055" halign="center"'
                f' style="Icons64x64_1" substyle="{substyle}"{act}/>\n')

    # Left side: First, Prev5, Prev
    if page > 1:
        xml += _nav(0.04,      'ArrowFirst',    -4)
        if add5:
            xml += _nav(0.095,     'ArrowFastPrev', -3)
        xml += _nav(w * 0.25,  'ArrowPrev',     -2)
    else:
        xml += _nav(0.04,     'StarGold', None)
        if add5:
            xml += _nav(0.095,    'StarGold', None)
        xml += _nav(w * 0.25, 'StarGold', None)

    # Close button.
    xml += (f'<quad pos="-{w / 2:.3f} -{close_y:.3f} -0.2"'
            f' size="0.06 0.06" halign="center"'
            f' style="Icons64x64_1" substyle="Close" action="0"/>\n')

    # Right side: Next, Next5, Last
    if page < total:
        xml += _nav(w * 0.75,    'ArrowNext',     2)
        if add5:
            xml += _nav(w - 0.095,   'ArrowFastNext', 3)
        xml += _nav(w - 0.04,    'ArrowLast',     4)
    else:
        xml += _nav(w * 0.75,   'StarGold', None)
        if add5:
            xml += _nav(w - 0.095,  'StarGold', None)
        xml += _nav(w - 0.04,   'StarGold', None)

    xml += '</frame></manialink>'

    black = _s(style, 'WINDOW.BLACKCOLOR')
    if black:
        xml = xml.replace('{#black}', black)
    return xml
