from __future__ import annotations

import copy
import logging
import sys
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_time, safe_manialink_text
from pyxaseco.models import Gameinfo

from ..config import _state, _effective_mode
from ..ui import append_window_start, append_window_end, append_four_player_columns
from ..utils import _handle_special_chars, _safe_ml_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

from .records_dedi import ML_DEDI, ML_SUBWIN, ML_WINDOW, _dedi_close_to_you, _digest_entries

logger = logging.getLogger(__name__)

STAR_MARKER = "$o$s$ff0*$z$fff"


def _pick_display_name(*candidates: object) -> str:
    values: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            values.append(text)
    if not values:
        return "?"
    for text in values:
        if "$" in text:
            return text
    return values[0]


async def _get_rpg_plugin():
    mod = (
        sys.modules.get("pyxaseco_plugins.plugin_records_rpg")
        or sys.modules.get("pyxaseco.plugins.plugin_records_rpg")
    )
    if mod is not None:
        return mod
    try:
        from pyxaseco.plugins import plugin_records_rpg as mod
        return mod
    except Exception:
        try:
            from pyxaseco_plugins import plugin_records_rpg as mod
            return mod
        except Exception:
            logger.debug("[Records-Eyepiece] RPG Records plugin module not available.")
            return None


def _stars_compact(stars: object | None) -> str:
    try:
        count = max(0, int(stars or 0))
    except Exception:
        count = 0
    if count <= 0:
        return ""
    return f"{count}{STAR_MARKER}"


def _stars_title_suffix(stars: object | None) -> str:
    compact = _stars_compact(stars)
    return f"Stars: {compact}" if compact else "Stars: ?"


def _rpg_title(stars: object | None = None) -> str:
    compact = _stars_compact(stars)
    return f"RPG Records ({compact})" if compact else "RPG Records"


def _normalise_rpg_record(rec: dict, rank: int) -> dict | None:
    if not isinstance(rec, dict):
        return None

    best = int(rec.get("best_score") or rec.get("Best") or rec.get("Score") or rec.get("score") or 0)
    if best <= 0:
        return None

    login = str(rec.get("login") or rec.get("Login") or "").strip()
    nickname = _pick_display_name(
        rec.get("nickname_raw"),
        rec.get("player_nickname_raw"),
        rec.get("nickname"),
        rec.get("player_nickname"),
        rec.get("NickName"),
        login,
    )
    nickname = _handle_special_chars(nickname)
    stars = rec.get("stars")

    return {
        "rank": int(rec.get("rank") or rec.get("Pos") or rank),
        "login": login,
        "nickname": nickname,
        "score": best,
        "score_text": format_time(best),
        "source": str(rec.get("source") or "tmrpg"),
        "stars": stars,
        "challenge_uid": str(rec.get("challenge_uid") or ""),
        "Login": login,
        "NickName": nickname,
        "Best": best,
        "Score": best,
        "Pos": int(rec.get("Pos") or rank),
    }


async def _is_rpg_track_active(aseco: "Aseco") -> bool:
    cached = getattr(aseco.server, "rpg_records_active", None)
    if cached is True:
        return True
    mod = await _get_rpg_plugin()
    if not mod:
        return False
    try:
        current = await mod.get_current_rpg_track(aseco)
    except Exception:
        return False
    return bool(current)


async def _get_rpg_track(aseco: "Aseco") -> dict | None:
    mod = await _get_rpg_plugin()
    if not mod:
        return None
    try:
        cached = mod.get_current_track_cache()
        if isinstance(cached, dict) and cached:
            return cached
    except Exception:
        pass
    try:
        current = await mod.get_current_rpg_track(aseco)
    except Exception:
        return None
    return current if isinstance(current, dict) else None


async def _get_rpg_records(aseco: "Aseco", limit: int | None = None) -> list[dict]:
    mod = await _get_rpg_plugin()
    if not mod:
        return []
    try:
        rows = await mod.get_current_rpg_records(aseco, limit)
    except Exception:
        return []

    result: list[dict] = []
    for idx, rec in enumerate(rows or [], start=1):
        row = _normalise_rpg_record(rec, idx)
        if row is not None:
            result.append(row)
    return result


async def _draw_rpg_player(aseco: "Aseco", login: str):
    from .common import _hide, _send
    from .records_common import _build_record_widget

    if not _state.player_visible.get(login, True):
        await _hide(aseco, login, ML_DEDI)
        return

    if _state.challenge_show_next:
        await _hide(aseco, login, ML_DEDI)
        return

    mode = _effective_mode(aseco)
    cfg = _state.dedi.get(mode)
    if not cfg or not cfg.enabled:
        await _hide(aseco, login, ML_DEDI)
        return

    raw_recs = await _get_rpg_records(aseco)
    if not raw_recs:
        _state.player_dedi_digest.pop(login, None)

    online = {p.login for p in aseco.server.players.all()} if _state.mark_online else set()
    player = aseco.server.players.get_player(login)
    player_nick = player.nickname if player and getattr(player, "nickname", "") else login

    entries = _dedi_close_to_you(raw_recs, login, cfg.entries, cfg.topcount, player_nick)
    if not entries:
        entries = [{
            "rank": "--",
            "login": login,
            "nickname": player_nick or login,
            "score": None,
            "self": 0,
            "highlitefull": False,
        }]

    track = await _get_rpg_track(aseco)
    title = safe_manialink_text(_rpg_title(track.get("stars") if isinstance(track, dict) else None), keep_colors=True)
    digest = str(hash((title, _digest_entries(entries, login))))
    if _state.player_dedi_digest.get(login) == digest:
        return
    _state.player_dedi_digest[login] = digest

    cfg_runtime = copy.copy(cfg)
    cfg_runtime.title = title

    xml = _build_record_widget(
        ml_id=ML_DEDI,
        cfg=cfg_runtime,
        login=login,
        entries=entries,
        online=online,
        mode=mode,
        click_action=91804,
    )
    await _send(aseco, login, xml)


async def _build_rpg_records_window(aseco: "Aseco", page: int = 0, records: list | None = None) -> str:
    raw_records = records if records is not None else await _get_rpg_records(aseco)
    if not raw_records:
        return ""

    mode = _effective_mode(aseco)
    is_stnt = (mode == Gameinfo.STNT)
    track = await _get_rpg_track(aseco)
    stars = track.get("stars") if isinstance(track, dict) else None
    title = f'RPG Records  |  {_stars_title_suffix(stars)}'
    total = len(raw_records)
    max_pages = max(1, (total + 99) // 100)
    page = max(0, min(page, max_pages - 1))

    PAGE_BASE = 918200

    def page_buttons(cur_p: int, mx_p: int) -> str:
        b = '<frame posn="52.2 -53.2 0.04">'
        if cur_p > 0:
            b += (
                f'<quad posn="6.6 6.50 0.01" sizen="3.2 3.2" action="-{PAGE_BASE + 0}" style="Icons64x64_1" substyle="ArrowFirst"/>'
                f'<quad posn="9.9 6.50 0.01" sizen="3.2 3.2" action="-{max(PAGE_BASE, PAGE_BASE + cur_p - 5)}" style="Icons64x64_1" substyle="ArrowFastPrev"/>'
                f'<quad posn="13.2 6.50 0.01" sizen="3.2 3.2" action="-{PAGE_BASE + cur_p - 1}" style="Icons64x64_1" substyle="ArrowPrev"/>'
            )
        else:
            b += (
                '<quad posn="6.6 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="6.6 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="9.9 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="9.9 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="13.2 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="13.2 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            )

        if (cur_p < 50) and (total > 100) and ((cur_p + 1) < mx_p):
            b += (
                f'<quad posn="16.5 6.50 0.01" sizen="3.2 3.2" action="{PAGE_BASE + cur_p + 1}" style="Icons64x64_1" substyle="ArrowNext"/>'
                f'<quad posn="19.8 6.50 0.01" sizen="3.2 3.2" action="{min(PAGE_BASE + mx_p - 1, PAGE_BASE + cur_p + 5)}" style="Icons64x64_1" substyle="ArrowFastNext"/>'
                f'<quad posn="23.1 6.50 0.01" sizen="3.2 3.2" action="{PAGE_BASE + mx_p - 1}" style="Icons64x64_1" substyle="ArrowLast"/>'
            )
        else:
            b += (
                '<quad posn="16.5 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="16.5 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="19.8 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="19.8 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="23.1 6.50 0.01" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
                '<quad posn="23.1 6.50 0.02" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
            )
        b += "</frame>"
        return b

    p: list[str] = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title=f'{safe_manialink_text(title, keep_colors=True)}  |  Page {page + 1}/{max_pages}  |  {total} Records',
        icon_style="Icons128x128_1",
        icon_substyle="Rankings",
        content_frame_pos="2.5 -6.5 1",
    )

    p.append(page_buttons(page, max_pages))
    p.append(f'<format textsize="1" textcolor="{_state.style.col_default}"/>')
    append_four_player_columns(p)

    online = {pl.login for pl in aseco.server.players.all()}

    line = 0
    offset = 0.0
    page_slice = raw_records[page * 100:min(page * 100 + 100, total)]
    for idx, item in enumerate(page_slice, start=page * 100 + 1):
        if not isinstance(item, dict):
            continue

        rec_login = str(item.get("login") or item.get("Login") or "")
        nick = str(item.get("nickname") or item.get("NickName") or rec_login or "?")

        if is_stnt:
            try:
                score = str(int(item.get("Best") or item.get("Score") or item.get("score") or 0))
            except Exception:
                score = "--"
        else:
            score = item.get("score_text")
            if not score:
                try:
                    score = format_time(int(item.get("Best") or item.get("Score") or item.get("score") or 0))
                except Exception:
                    score = "--"

        rank = int(item.get("rank") or item.get("Pos") or idx)

        if rec_login in online:
            y_bg = max(0.2, 1.83 * line - 0.2)
            p.append(
                f'<quad posn="{offset + 0.4:.2f} -{y_bg:.2f} 0.03" sizen="16.95 1.83" '
                f'style="{_state.style.hi_other_style}" substyle="{_state.style.hi_other_sub}"/>'
            )

        y = 1.83 * line
        p.append(f'<label posn="{2.6 + offset:.2f} -{y:.2f} 0.04" sizen="2 1.7" halign="right" scale="0.9" text="{rank}."/>')
        p.append(f'<label posn="{6.4 + offset:.2f} -{y:.2f} 0.04" sizen="4 1.7" halign="right" scale="0.9" textcolor="{_state.style.col_scores}" text="{safe_manialink_text(score, keep_colors=False)}"/>')
        p.append(f'<label posn="{6.9 + offset:.2f} -{y:.2f} 0.04" sizen="11.2 1.7" scale="0.9" text="{_safe_ml_text(nick)}"/>')

        line += 1
        if line >= 25:
            offset += 19.05
            line = 0

    append_window_end(p)
    return "".join(p)
