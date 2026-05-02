from __future__ import annotations

from typing import TYPE_CHECKING
from pyxaseco.helpers import format_time

from ..config import WidgetCfg, StyleCfg, _state
from ..utils import _handle_special_chars, _safe_ml_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


LINE_H = 1.8
ENTRY_OFFSET = 3.0


def _build_online_marker(
    line: int,
    self_flag: int,
    topcount: int,
    behind_player: bool,
    w: float,
    st: StyleCfg,
) -> str:
    """
    Port of re_getConnectedPlayerRecord().

    Adds a highlight background + side markers for an online player's record row.
    behind_player: True if this online player is ranked BELOW the viewing player.
    """
    yp = LINE_H * line + 2.7
    ypm = LINE_H * line + 2.8

    parts = []

    # Row background (only for non-top entries)
    if (line + 1) > topcount:
        parts.append(
            f'<quad posn="0.4 -{yp:.4f} 0.003"'
            f' sizen="{w - 0.8:.4f} 2"'
            f' style="{st.hi_other_style}" substyle="{st.hi_other_sub}"/>'
        )

    # Left side tab
    parts.append(
        f'<quad posn="-1.9 -{yp:.4f} 0.003"'
        f' sizen="2 2"'
        f' style="{st.hi_other_style}" substyle="{st.hi_other_sub}"/>'
    )

    # Right side tab
    parts.append(
        f'<quad posn="{w - 0.1:.4f} -{yp:.4f} 0.003"'
        f' sizen="2 2"'
        f' style="{st.hi_other_style}" substyle="{st.hi_other_sub}"/>'
    )

    # Marker icon: ChallengeAuthor if ABOVE player, Solo if BELOW
    icon_sub = 'Solo' if behind_player else 'ChallengeAuthor'

    # Left marker
    parts.append(
        f'<quad posn="-1.8 -{ypm:.4f} 0.004"'
        f' sizen="1.8 1.8"'
        f' style="Icons128x128_1" substyle="{icon_sub}"/>'
    )

    # Right marker
    parts.append(
        f'<quad posn="{w + 0.1:.4f} -{ypm:.4f} 0.004"'
        f' sizen="1.8 1.8"'
        f' style="Icons128x128_1" substyle="{icon_sub}"/>'
    )

    return ''.join(parts)


def _build_record_widget(
    *,
    ml_id: int,
    cfg: WidgetCfg,
    login: str,
    entries: list,
    online: set,
    mode: int,
    is_live: bool = False,
    click_action: int | None = None,
) -> str:
    """
    Builds the full ManiaLink XML for a record widget.
    """
    st = _state.style
    w = cfg.width

    widget_h = LINE_H * cfg.entries + 3.3
    col_h = widget_h - 3.1
    col_name_w = w - 6.45

    side = 'right' if cfg.pos_x < 0 else 'left'
    w_off = w - 15.5
    if side == 'right':
        icon_x = 12.5 + w_off
        title_x = 12.4 + w_off
        halign = 'right'
    else:
        icon_x = 0.6
        title_x = 3.2
        halign = 'left'
    icon_y = 0.0
    title_y = -0.55

    p: list[str] = []

    panel_action = click_action if click_action is not None else 382009003

    # HEADER
    p.append(f'<manialink id="{ml_id}">')
    p.append(f'<frame posn="{cfg.pos_x:.4f} {cfg.pos_y:.4f} 0">')

    # Main background quad
    p.append(
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {widget_h:.4f}"'
        f' action="{panel_action}"'
        f' style="{st.bg_style}" substyle="{st.bg_substyle}"/>'
    )

    # Column backgrounds
    p.append(
        f'<quad posn="0.4 -2.6 0.002" sizen="2 {col_h:.4f}"'
        f' bgcolor="{st.col_bg_rank}"/>'
    )
    p.append(
        f'<quad posn="2.4 -2.6 0.002" sizen="3.65 {col_h:.4f}"'
        f' bgcolor="{st.col_bg_score}"/>'
    )
    p.append(
        f'<quad posn="6.05 -2.6 0.002" sizen="{col_name_w:.4f} {col_h:.4f}"'
        f' bgcolor="{st.col_bg_name}"/>'
    )

    # Title bar
    p.append(
        f'<quad posn="0.4 -0.36 0.002" sizen="{w - 0.8:.4f} 2"'
        f' style="{st.title_style}" substyle="{st.title_sub}"/>'
    )

    # Icon
    p.append(
        f'<quad posn="{icon_x:.4f} {icon_y:.4f} 0.004" sizen="2.5 2.5"'
        f' style="{cfg.icon_style}" substyle="{cfg.icon_substyle}"/>'
    )

    # Title label
    p.append(
        f'<label posn="{title_x:.4f} {title_y:.4f} 0.004"'
        f' sizen="10.2 0" halign="{halign}" textsize="1"'
        f' text="{cfg.title}"/>'
    )

    # Format tag
    p.append(f'<format textsize="1" textcolor="{st.col_default}"/>')

    # Top-N background quad
    if cfg.topcount > 0:
        top_bg_h = cfg.topcount * LINE_H + 0.3
        p.append(
            f'<quad posn="0.4 -2.6 0.003" sizen="{w - 0.8:.4f} {top_bg_h:.4f}"'
            f' style="{st.top_style}" substyle="{st.top_sub}"/>'
        )

    behind_player = False

    for line, entry in enumerate(entries):
        rank = entry.get('rank')
        display_rank = entry.get('display_rank', rank)
        nick = entry.get('nickname', '')
        score_raw = entry.get('score')
        self_flag = entry.get('self', -1)
        hi_full = entry.get('highlitefull', False)
        ent_login = entry.get('login', '')

        if self_flag == 0:
            behind_player = True

        # Format score string
        if is_live or isinstance(score_raw, str):
            score_str = str(score_raw) if score_raw is not None else '--'
        elif score_raw is None:
            score_str = '--'
        elif mode == 4:  # STNT
            score_str = str(score_raw)
        else:
            score_str = format_time(int(score_raw))

        nick_clean = _handle_special_chars(nick)

        # Online marker for OTHER players
        if (_state.mark_online and ent_login and ent_login != login
                and ent_login in online and not is_live):
            p.append(_build_online_marker(
                line=line,
                self_flag=self_flag,
                topcount=cfg.topcount,
                behind_player=behind_player,
                w=w,
                st=st,
            ))

        # Colors / highlight
        if self_flag == -1:
            if isinstance(rank, int) and rank < cfg.topcount + 1:
                textcolor = st.col_top
            else:
                textcolor = st.col_better
        elif self_flag == 1:
            if isinstance(rank, int) and rank < cfg.topcount + 1:
                textcolor = st.col_top
            else:
                textcolor = st.col_worse
        else:
            textcolor = st.col_self

            # Full-row highlight if self is in topcount
            if hi_full:
                yp = LINE_H * line + ENTRY_OFFSET - 0.3
                p.append(
                    f'<quad posn="0.4 -{yp:.4f} 0.003"'
                    f' sizen="{w - 0.8:.4f} 2"'
                    f' style="{st.hi_style}" substyle="{st.hi_sub}"/>'
                )

            # Side-tab highlights + arrows
            if rank is not False and rank != '--':
                yp = LINE_H * line + ENTRY_OFFSET - 0.3
                ypa = LINE_H * line + ENTRY_OFFSET - 0.1

                p.append(
                    f'<quad posn="-1.9 -{yp:.4f} 0.003"'
                    f' sizen="2 2"'
                    f' style="{st.hi_style}" substyle="{st.hi_sub}"/>'
                )
                p.append(
                    f'<quad posn="-1.7 -{ypa:.4f} 0.004"'
                    f' sizen="1.6 1.6"'
                    f' style="Icons64x64_1" substyle="ArrowNext"/>'
                )
                p.append(
                    f'<quad posn="{w - 0.1:.4f} -{yp:.4f} 0.003"'
                    f' sizen="2 2"'
                    f' style="{st.hi_style}" substyle="{st.hi_sub}"/>'
                )
                p.append(
                    f'<quad posn="{w + 0.1:.4f} -{ypa:.4f} 0.004"'
                    f' sizen="1.6 1.6"'
                    f' style="Icons64x64_1" substyle="ArrowPrev"/>'
                )

        y = LINE_H * line + ENTRY_OFFSET

        # Rank + score labels
        if rank is not False:
            rank_str = f'{display_rank}.' if display_rank != '--' else '--'
            p.append(
                f'<label posn="2.3 -{y:.4f} 0.004"'
                f' sizen="1.7 1.7" halign="right" scale="0.9"'
                f' text="{st.fmt_codes}{rank_str}"/>'
            )
            p.append(
                f'<label posn="5.9 -{y:.4f} 0.004"'
                f' sizen="3.8 1.7" halign="right" scale="0.9"'
                f' textcolor="{textcolor}"'
                f' text="{st.fmt_codes}{score_str}"/>'
            )
        else:
            # Team mode: no rank
            p.append(
                f'<label posn="5.9 -{y:.4f} 0.004"'
                f' sizen="5.3 1.7" halign="right" scale="0.9"'
                f' textcolor="{st.col_default}"'
                f' text="{st.fmt_codes}{score_str}"/>'
            )

        # Name label
        p.append(
            f'<label posn="6.1 -{y:.4f} 0.004"'
            f' sizen="{w - 5.7:.4f} 1.7" scale="0.9"'
            f' text="{_safe_ml_text(st.fmt_codes + nick_clean)}"/>'
        )

    p.append('</frame></manialink>')
    return ''.join(p)
