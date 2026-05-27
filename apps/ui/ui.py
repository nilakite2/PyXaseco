from __future__ import annotations

from xml.sax.saxutils import escape as _esc

DEFAULT_BACKDROP = ''
DEFAULT_FRAME_OPEN = '<frame posn="-40.1 30.45 18.50">'
DEFAULT_INNER_BG = '<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>'
DEFAULT_CARD_BG = '<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>'
DEFAULT_TITLE_BG = '<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>'
DEFAULT_SEPARATOR = '<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>'
DEFAULT_CLOSE_FRAME = '<frame posn="77.4 1.3 0.05">'
DEFAULT_CLOSE_BG = '<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>'
DEFAULT_CLOSE_ARROW = '<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>'

COL_X = (0, 19.05, 38.1, 57.15)
PLAYER_COL_QUAD = '<quad posn="{x} 0.8 0.02" sizen="17.75 46.88" style="BgsPlayerCard" substyle="BgRacePlayerName"/>'


def _escape(text: str) -> str:
    return _esc(str(text or ''))


def append_window_start(p: list[str], *, ml_window: int, ml_subwin: int, title: str,
                        icon_style: str, icon_substyle: str,
                        footer_text: str | None = None,
                        content_frame_pos: str = '2.5 -6.5 1',
                        title_pos: str = '5.5 -1.9 0.04',
                        title_size: str = '74 0',
                        title_scale: str = '0.9',
                        title_textsize: str = '2') -> None:
    p.append(f'<manialink id="{ml_subwin}"></manialink>')
    p.append(f'<manialink id="{ml_window}">')
    p.append(DEFAULT_BACKDROP)
    p.append(DEFAULT_FRAME_OPEN)
    p.append(DEFAULT_INNER_BG)
    p.append(DEFAULT_INNER_BG)
    p.append(DEFAULT_CARD_BG)
    p.append(DEFAULT_TITLE_BG)
    p.append(DEFAULT_SEPARATOR)
    p.append(f'<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="{_escape(icon_style)}" substyle="{_escape(icon_substyle)}"/>')
    p.append(
        f'<label posn="{title_pos}" sizen="{title_size}" textsize="{title_textsize}" scale="{title_scale}" textcolor="FFFF" text="{_escape(title)}"/>'
    )
    if footer_text:
        p.append(f'<label posn="2.7 -54.1 0.04" sizen="30 1" textsize="1" scale="0.7" textcolor="000F" text="{_escape(footer_text)}"/>')
    p.append(DEFAULT_CLOSE_FRAME)
    p.append(DEFAULT_CLOSE_ARROW)
    p.append(DEFAULT_CLOSE_BG)
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ml_window}" style="Icons64x64_1" substyle="Close"/>')
    p.append('</frame>')
    p.append(f'<frame posn="{content_frame_pos}">')


def append_window_end(p: list[str]) -> None:
    p.append('</frame>')
    p.append('</frame>')
    p.append('</manialink>')


def append_four_player_columns(p: list[str]) -> None:
    for x in COL_X:
        p.append(PLAYER_COL_QUAD.format(x=x))


def build_option_tile(*, card_w: float, card_h: float, title: str, icon: str,
                      desc: str, action_id: int | None, enabled: bool = True) -> str:
    if action_id is not None and enabled:
        action_quad = f'<quad posn="14.15 -5.65 0.03" sizen="4 4" action="{action_id}" style="Icons64x64_1" substyle="Add"/>'
    else:
        action_quad = '<quad posn="14.15 -5.65 0.03" sizen="4 4" style="Icons64x64_1" substyle="LvlLocked"/>'
    return (
        '<format textsize="1" textcolor="FFFF"/>'
        f'<quad posn="0 0 0.02" sizen="{card_w} {card_h}" style="BgsPlayerCard" substyle="BgRacePlayerName"/>'
        f'{action_quad}'
        '<quad posn="0.4 -0.36 0.04" sizen="16.95 2" style="BgsPlayerCard" substyle="ProgressBar"/>'
        f'<quad posn="0.6 0 0.05" sizen="2.5 2.5" style="Icons128x128_1" substyle="{_escape(icon)}"/>'
        f'<label posn="3.2 -0.55 0.05" sizen="17.3 0" textsize="1" text="{_escape(title)}"/>'
        f'<label posn="1 -2.7 0.04" sizen="16 2" scale="0.9" autonewline="1" text="{_escape(desc)}"/>'
    )
