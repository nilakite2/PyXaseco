"""
plugin_best_cp_times_v2.py - based on Trakman scroll style LiveCpsRanking
"""

from __future__ import annotations

import logging
import importlib
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player, Challenge

logger = logging.getLogger(__name__)

ML_PREFIX = "920"
ML_WIDGET = 92001
ML_INLAY = 92002
ACTION_PAGE_BASE = 9207000

PAGE_SIZE = 10

STATE_RACE = 1
STATE_SCORE = 6


@dataclass
class WidgetCfg:
    position_x: float = 49.7
    position_y: float = -20.0
    width: float = 15.0
    height: float = 18.2
    textsize: float = 1.0
    textscale: float = 0.9
    custom_ui: bool = True
    show_spectators: bool = True


@dataclass
class BctState:
    version: str = "1.0.2"
    current_state: int = STATE_RACE
    show_max_checkpoints: int = 2000
    widget: WidgetCfg = field(default_factory=WidgetCfg)
    challenge_num_cps: int = 20
    challenge_multilap: bool = False
    checkpoint_times: dict[int, dict[str, object]] = field(default_factory=dict)
    hidden_logins: set[str] = field(default_factory=set)
    eyepiece_prev_checkpoint_list: bool | None = None
    pages: dict[str, int] = field(default_factory=dict)


_state = BctState()


def register(aseco: "Aseco"):
    aseco.register_event("onSync", bct_onSync)
    aseco.register_event("onCheckpoint", bct_onCheckpoint)
    aseco.register_event("onNewChallenge2", bct_onNewChallenge2)
    aseco.register_event("onPlayerConnect", bct_onPlayerConnect)
    aseco.register_event("onPlayerInfoChanged", bct_onPlayerInfoChanged)
    aseco.register_event("onPlayerManialinkPageAnswer", bct_onPlayerManialinkPageAnswer)
    aseco.register_event("onEndRace1", bct_onEndRace1)
    aseco.register_event("onRestartChallenge", bct_onRestartChallenge)


def _load_cfg(aseco: "Aseco"):
    base_dir = Path(getattr(aseco, "_base_dir", Path.cwd()))
    candidates = [
        base_dir / "best_cp_times_v2.xml",
        Path.cwd() / "best_cp_times_v2.xml",
    ]
    for path in candidates:
        try:
            if not path.exists():
                continue
            root = ET.parse(path).getroot()
            pos = root.find("position")
            if pos is not None:
                x = pos.findtext("x")
                y = pos.findtext("y")
                if x is not None:
                    _state.widget.position_x = float(x)
                if y is not None:
                    _state.widget.position_y = float(y)
            ts = root.findtext("textsize")
            sc = root.findtext("textscale")
            mx = root.findtext("number")
            cu = root.findtext("custom_ui")
            ss = root.findtext("show_spectators")
            wd = root.findtext("width")
            ht = root.findtext("height")
            if ts is not None:
                _state.widget.textsize = float(ts)
            if sc is not None:
                _state.widget.textscale = float(sc)
            if mx is not None:
                _state.show_max_checkpoints = max(1, int(mx))
            if cu is not None:
                _state.widget.custom_ui = str(cu).strip().lower() in ("1", "true", "yes", "on")
            if ss is not None:
                _state.widget.show_spectators = str(ss).strip().lower() in ("1", "true", "yes", "on")
            if wd is not None:
                _state.widget.width = max(14.0, float(wd))
            if ht is not None:
                _state.widget.height = max(14.0, float(ht))
            logger.info("[BestCpTimesV2] Config loaded from %s", path)
            return
        except Exception as exc:
            logger.warning("[BestCpTimesV2] Failed loading %s: %s", path, exc)


def _resolve_eyepiece_state():
    module_names = (
        "records_eyepiece.state",
        "records_eyepiece.plugin",
        "pyxaseco_plugins.records_eyepiece.state",
        "pyxaseco_plugins.records_eyepiece.plugin",
        "pyxaseco.plugins.records_eyepiece.state",
        "pyxaseco.plugins.records_eyepiece.plugin",
        "plugins.records_eyepiece.state",
        "plugins.records_eyepiece.plugin",
    )
    for name in module_names:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        getter = getattr(mod, "get_state", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                continue
    return None


def _resolve_eyepiece_apply():
    module_names = (
        "records_eyepiece.handlers.events",
        "pyxaseco_plugins.records_eyepiece.handlers.events",
        "pyxaseco.plugins.records_eyepiece.handlers.events",
        "plugins.records_eyepiece.handlers.events",
    )
    for name in module_names:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        fn = getattr(mod, "_apply_custom_ui_all", None)
        if callable(fn):
            return fn
    return None


def _custom_ui_xml(checkpoint_visible: bool) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<manialinks>"
        '<manialink id="0"><line></line></manialink>'
        "<custom_ui>"
        f'<checkpoint_list visible="{"true" if checkpoint_visible else "false"}"/>'
        "</custom_ui>"
        "</manialinks>"
    )


async def bct_apply_custom_ui_all(aseco: "Aseco", checkpoint_visible: bool):
    xml = _custom_ui_xml(checkpoint_visible)
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def bct_apply_custom_ui_login(aseco: "Aseco", login: str, checkpoint_visible: bool):
    xml = _custom_ui_xml(checkpoint_visible)
    await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)


async def bct_set_checkpoint_list_visible(aseco: "Aseco", checkpoint_visible: bool):
    if not _state.widget.custom_ui:
        return
    ep_state = _resolve_eyepiece_state()
    ep_apply = _resolve_eyepiece_apply()
    if ep_state and ep_apply and getattr(ep_state, "custom_ui_enabled", False):
        if _state.eyepiece_prev_checkpoint_list is None:
            _state.eyepiece_prev_checkpoint_list = bool(getattr(ep_state, "custom_ui_checkpoint_list", True))
        ep_state.custom_ui_checkpoint_list = checkpoint_visible
        await ep_apply(aseco)
        return

    try:
        await aseco.client.query_ignore_result("SetForcedUi", {"checkpoint_list": checkpoint_visible})
    except Exception:
        pass
    await bct_apply_custom_ui_all(aseco, checkpoint_visible)


async def bct_set_checkpoint_list_visible_login(aseco: "Aseco", login: str, checkpoint_visible: bool):
    if not _state.widget.custom_ui:
        return
    ep_state = _resolve_eyepiece_state()
    ep_apply = _resolve_eyepiece_apply()
    if ep_state and ep_apply and getattr(ep_state, "custom_ui_enabled", False):
        if _state.eyepiece_prev_checkpoint_list is None:
            _state.eyepiece_prev_checkpoint_list = bool(getattr(ep_state, "custom_ui_checkpoint_list", True))
        ep_state.custom_ui_checkpoint_list = checkpoint_visible
        await ep_apply(aseco)
        return

    try:
        await aseco.client.query_ignore_result("SetForcedUi", {"checkpoint_list": checkpoint_visible})
    except Exception:
        pass
    await bct_apply_custom_ui_login(aseco, login, checkpoint_visible)


async def bct_onSync(aseco: "Aseco", _param=None):
    global _state
    _state = BctState()

    game = ""
    try:
        game = aseco.server.getGame()
    except Exception:
        game = getattr(aseco.server, "game", "")

    game_norm = str(game or "").strip().lower()
    tmf_aliases = {"tmf", "tmforever", "tm forever", "trackmania forever", "tmnforever"}
    if game_norm and game_norm not in tmf_aliases:
        raise RuntimeError(
            f"[plugin_best_checkpoint_times.py] This plugin supports only TMF/TmForever, cannot start with {game!r}."
        )

    try:
        versions = getattr(aseco, "plugin_versions", None)
        if isinstance(versions, list):
            versions.append(
                {
                    "plugin": "plugin_best_checkpoint_times.py",
                    "author": "undef.de",
                    "version": _state.version,
                }
            )
    except Exception:
        pass

    _load_cfg(aseco)
    await bct_set_checkpoint_list_visible(aseco, False)


async def bct_onPlayerConnect(aseco: "Aseco", player: "Player"):
    if not getattr(_state, "challenge_num_cps", 0):
        _state.challenge_num_cps = _state.show_max_checkpoints
    _state.pages[player.login] = 0
    if bool(getattr(player, "isspectator", False)) and not _state.widget.show_spectators:
        _state.hidden_logins.add(player.login)
    else:
        _state.hidden_logins.discard(player.login)
    await bct_set_checkpoint_list_visible_login(aseco, player.login, False)
    await bct_buildWidget(aseco, player.login)
    if player.login not in _state.hidden_logins:
        await bct_buildCheckpointsTimeInlay(aseco, login=player.login)


async def bct_onPlayerInfoChanged(aseco: "Aseco", info):
    if _state.current_state == STATE_SCORE:
        return

    if isinstance(info, dict):
        login = str(info.get("Login", "") or "")
        spectator_status = int(info.get("SpectatorStatus", 0) or 0)
    else:
        login = str(getattr(info, "login", "") or "")
        spectator_status = int(getattr(info, "spectatorstatus", 0) or 0)

    if not login:
        return

    player = aseco.server.players.get_player(login)
    if not player:
        return

    is_spectator = spectator_status > 0

    if is_spectator and not _state.widget.show_spectators:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<manialinks>"
            f'<manialink id="{ML_WIDGET}"></manialink>'
            f'<manialink id="{ML_INLAY}"></manialink>'
            "</manialinks>"
        )
        _state.hidden_logins.add(login)
        await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)
    else:
        _state.hidden_logins.discard(login)
        _state.pages.setdefault(login, 0)
        await bct_buildWidget(aseco, login)
        await bct_buildCheckpointsTimeInlay(aseco)


async def bct_onPlayerManialinkPageAnswer(aseco: "Aseco", answer: list):
    if len(answer) < 3:
        return
    action = int(answer[2] or 0)
    if action == 0:
        return

    login = answer[1]
    if action <= -ACTION_PAGE_BASE:
        page = abs(action) - ACTION_PAGE_BASE
        _state.pages[login] = _clamp_page(page)
        await bct_buildWidget(aseco, login)
        await bct_buildCheckpointsTimeInlay(aseco, login=login)
    elif action >= ACTION_PAGE_BASE:
        page = action - ACTION_PAGE_BASE
        _state.pages[login] = _clamp_page(page)
        await bct_buildWidget(aseco, login)
        await bct_buildCheckpointsTimeInlay(aseco, login=login)


async def bct_onNewChallenge2(aseco: "Aseco", challenge_item):
    _state.current_state = STATE_RACE
    await bct_set_checkpoint_list_visible(aseco, False)
    _state.pages.clear()
    await bct_buildWidget(aseco, None)

    _state.challenge_num_cps = int(getattr(challenge_item, "nbchecks", 0) or _state.show_max_checkpoints)
    _state.challenge_multilap = bool(getattr(challenge_item, "laprace", False))
    _state.checkpoint_times = {
        cp: {"Score": 0, "Nickname": "---"} for cp in range(_state.challenge_num_cps)
    }
    await bct_buildCheckpointsTimeInlay(aseco)


async def bct_onRestartChallenge(aseco: "Aseco", _challenge_item):
    _state.current_state = STATE_RACE


async def bct_onBeginRound(aseco: "Aseco", _param=None):
    _state.current_state = STATE_RACE


async def bct_onCheckpoint(aseco: "Aseco", checkpt: list):
    if len(checkpt) < 5:
        return

    player = aseco.server.players.get_player(checkpt[1])
    if not player:
        return

    score = int(checkpt[2] or 0)
    round_no = int(checkpt[3] or 0)
    checkpoint_id = int(checkpt[4] or 0)

    if checkpoint_id not in _state.checkpoint_times:
        return

    # Multilap correction for Laps mode + multilap maps.
    mode = getattr(getattr(aseco.server, "gameinfo", None), "mode", -1)
    if mode == 3 and _state.challenge_multilap:
        if (checkpoint_id + 1) == (_state.challenge_num_cps * round_no):
            round_no -= 1
        if round_no > 0:
            cp = checkpoint_id - (_state.challenge_num_cps * round_no)
            if cp >= 0:
                checkpoint_id = cp

    _state.pages[player.login] = _page_for_checkpoint(checkpoint_id)

    refresh = False
    current = _state.checkpoint_times.get(checkpoint_id, {"Score": 0, "Nickname": "---"})
    current_score = int(current.get("Score", 0) or 0)

    better = False
    if current_score > 0:
        if mode == 4:
            better = score > current_score
        else:
            better = score < current_score
    else:
        better = True

    if better:
        _state.checkpoint_times[checkpoint_id] = {
            "Score": score,
            "Nickname": bct_handleSpecialChars(getattr(player, "nickname", player.login)),
        }
        refresh = True

    if refresh:
        await bct_buildCheckpointsTimeInlay(aseco, checkpoint_id)
    else:
        await bct_buildCheckpointsTimeInlay(aseco)


async def bct_onEndRace1(aseco: "Aseco", _race):
    _state.current_state = STATE_SCORE
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<manialinks>"
        f'<manialink id="{ML_WIDGET}"></manialink>'
        f'<manialink id="{ML_INLAY}"></manialink>'
        "</manialinks>"
    )
    _state.checkpoint_times = {}
    _state.pages.clear()
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def bct_buildWidget(aseco: "Aseco", login: str | None = None):
    width = _state.widget.width
    height = _state.widget.height

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<manialinks>"
        f'<manialink id="{ML_WIDGET}">'
        f'<frame posn="{_state.widget.position_x} {_state.widget.position_y} 3">'
        f'<quad posn="-0.5 -0.5 0.11" sizen="{width:.2f} {height:.2f}" style="BgsPlayerCard" substyle="ProgressBar"/>'
        "</frame>"
        "</manialink>"
        "</manialinks>"
    )

    if login:
        await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)
    else:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def bct_buildCheckpointsTimeInlay(aseco: "Aseco", cpid: int = -1, login: str | None = None):
    checkpoint_id = cpid if cpid != -1 else 0
    logins: list[str] = []
    if login:
        if login not in _state.hidden_logins:
            logins = [login]
    else:
        logins = [player.login for player in aseco.server.players.all() if player.login not in _state.hidden_logins]

    if not logins:
        return

    for target_login in logins:
        xml = _build_inlay_xml(
            aseco,
            target_login,
            checkpoint_id,
            cpid != -1,
            getattr(getattr(aseco.server, "gameinfo", None), "mode", -1),
        )
        await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", target_login, xml, 0, False)


def _visible_checkpoint_ids() -> list[int]:
    ids: list[int] = []
    for cp in range(_state.challenge_num_cps):
        if (cp + 1) > _state.show_max_checkpoints:
            break
        if (len(ids) + 1) == _state.challenge_num_cps:
            break
        if cp not in _state.checkpoint_times:
            break
        ids.append(cp)
    return ids


def _page_count() -> int:
    total = len(_visible_checkpoint_ids())
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def _clamp_page(page: int) -> int:
    return max(0, min(max(0, _page_count() - 1), int(page or 0)))


def _page_for_checkpoint(checkpoint_id: int) -> int:
    ids = _visible_checkpoint_ids()
    try:
        idx = ids.index(int(checkpoint_id))
    except ValueError:
        return 0
    return _clamp_page(idx // PAGE_SIZE)


def _find_login_by_pid(aseco: "Aseco", pid: int) -> str | None:
    if not pid:
        return None
    for player in aseco.server.players.all():
        try:
            if int(getattr(player, "pid", 0) or 0) == int(pid):
                return player.login
        except Exception:
            continue
    return None


def _effective_page_for_login(aseco: "Aseco", login: str) -> int:
    player = aseco.server.players.get_player(login)
    if not player:
        return _clamp_page(_state.pages.get(login, 0))

    spectator_status = int(getattr(player, "spectatorstatus", 0) or 0)
    if spectator_status and (spectator_status % 10) != 0:
        target_pid = spectator_status // 10000
        target_login = _find_login_by_pid(aseco, target_pid)
        if target_login:
            return _clamp_page(_state.pages.get(target_login, 0))

    return _clamp_page(_state.pages.get(login, 0))


def _build_inlay_xml(aseco: "Aseco", login: str, checkpoint_id: int, highlight: bool, mode: int) -> str:
    page = _effective_page_for_login(aseco, login)
    ids = _visible_checkpoint_ids()
    start = page * PAGE_SIZE
    page_ids = ids[start:start + PAGE_SIZE]
    width = _state.widget.width

    rank_x = 1.65
    time_x = 5.2
    name_x = 5.75
    name_w = max(7.5, width - name_x - 0.9)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<manialinks>",
        f'<manialink id="{ML_INLAY}">',
        f'<frame posn="{_state.widget.position_x} {_state.widget.position_y} 3">',
    ]

    row_offset = 1.52
    for idx, cp in enumerate(page_ids, start=1):
        posy = -(row_offset * idx)
        if highlight and cp == checkpoint_id:
            parts.append('<format style="TextTitle2Blink"/>')
        else:
            parts.append('<format style="TextStaticMedium"/>')

        entry = _state.checkpoint_times[cp]
        score_val = int(entry.get("Score", 0) or 0)
        nick = str(entry.get("Nickname", "---"))
        score_txt = str(score_val) if mode == 4 else bct_formatTime(score_val)

        parts.append(
            f'<label posn="{rank_x:.2f} {posy:.2f} 0.14" sizen="1.8 0" halign="right" '
            f'textsize="{_state.widget.textsize}" scale="{_state.widget.textscale}" text="$FFF{cp + 1}."/>'
        )
        parts.append(
            f'<label posn="{time_x:.2f} {posy:.2f} 0.14" sizen="3.8 0" halign="right" '
            f'textsize="{_state.widget.textsize}" scale="{_state.widget.textscale}" text="$FFF{escape(score_txt)}"/>'
        )
        parts.append(
            f'<label posn="{name_x:.2f} {posy:.2f} 0.14" sizen="{name_w:.2f} 0" '
            f'textsize="{_state.widget.textsize}" scale="{_state.widget.textscale}" text="$FFF{nick}"/>'
        )

    footer_y = -(row_offset * (PAGE_SIZE + 0.55)) - 0.45
    page = _clamp_page(_state.pages.get(login, 0))
    total_pages = _page_count()
    prev_action = -(ACTION_PAGE_BASE + max(0, page - 1))
    next_action = ACTION_PAGE_BASE + min(max(0, total_pages - 1), page + 1)
    prev_x = 0.55
    page_x = 3.6
    next_x = 5.15
    parts.append(
        f'<quad posn="{prev_x:.2f} {footer_y:.2f} 0.12" sizen="2.0 2.0" action="{prev_action}" style="Icons64x64_1" substyle="ArrowPrev"/>'
    )
    parts.append(
        f'<label posn="{page_x:.2f} {footer_y - 0.10:.2f} 0.14" sizen="3.8 0" halign="center" textsize="1.2" scale="0.85" text="$FFF{page + 1}/{max(1, total_pages)}"/>'
    )
    parts.append(
        f'<quad posn="{next_x:.2f} {footer_y:.2f} 0.12" sizen="2.0 2.0" action="{next_action}" style="Icons64x64_1" substyle="ArrowNext"/>'
    )

    parts.extend(["</frame>", "</manialink>", "</manialinks>"])
    return "".join(parts)


def bct_formatTime(mw_time: int, hsec: bool = True) -> str:
    if mw_time == -1:
        return "???"

    hseconds = (mw_time - ((mw_time // 1000) * 1000)) // 10
    mw_time = mw_time // 1000
    hours = mw_time // 3600
    mw_time -= hours * 3600
    minutes = mw_time // 60
    mw_time -= minutes * 60
    seconds = mw_time

    if hsec:
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}.{hseconds:02d}"
        return f"{minutes}:{seconds:02d}.{hseconds:02d}"
    else:
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


def bct_handleSpecialChars(string: str) -> str:
    text = str(string or "")

    # Remove links/manialinks while keeping visible text.
    text = re.sub(r'\$(L|H|P)\[.*?\](.*?)\$(L|H|P)', r'\2', text, flags=re.I)
    text = re.sub(r'\$(L|H|P)\[.*?\](.*)', r'\2', text, flags=re.I)
    text = re.sub(r'\$(L|H|P)(.*)', r'\2', text, flags=re.I)

    # Remove style flags stripped here, but keep color codes.
    text = re.sub(r'\$[SHWILON]', '', text, flags=re.I)

    text = text.replace("\r", "").replace("\n", " ")
    return escape(text, quote=True)
