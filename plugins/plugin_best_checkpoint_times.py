"""
plugin_best_checkpoint_times.py — Python port of plugin.best_checkpoint_times.php (v1.0.2)
by undef.de

Tracks the best absolute checkpoint times on the current map and displays them
in a compact race widget.

Port notes:
- TMF only
- no DB dependency; state is per-map / in-memory only
- hides itself on score and for spectators
- includes the original help window and clickable help button

Manialink ids/actions:
  92001  widget frame
  92002  checkpoint times inlay
  92003  help window
  92004  open help
  92005  close help
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player, Challenge

logger = logging.getLogger(__name__)

ML_PREFIX = "920"
ML_WIDGET = 92001
ML_INLAY = 92002
ML_HELP = 92003
ACTION_HELP = 92004
ACTION_CLOSE_HELP = 92005

STATE_RACE = 1
STATE_SCORE = 6


@dataclass
class WidgetCfg:
    position_x: float = 13.0
    position_y: float = -32.5
    textsize: float = 1.0
    textscale: float = 0.9


@dataclass
class BctState:
    version: str = "1.0.2"
    current_state: int = STATE_RACE
    show_max_checkpoints: int = 20
    widget: WidgetCfg = field(default_factory=WidgetCfg)
    challenge_num_cps: int = 20
    challenge_multilap: bool = False
    checkpoint_times: dict[int, dict[str, object]] = field(default_factory=dict)
    hidden_logins: set[str] = field(default_factory=set)


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
                    "author": "undef.de / OpenAI port",
                    "version": _state.version,
                }
            )
    except Exception:
        pass

    try:
        await aseco.client.query_ignore_result("SetForcedUi", {"checkpoint_list": False})
    except Exception:
        pass


async def bct_onPlayerConnect(aseco: "Aseco", player: "Player"):
    if not getattr(_state, "challenge_num_cps", 0):
        _state.challenge_num_cps = _state.show_max_checkpoints
    _state.hidden_logins.discard(player.login)
    await bct_buildWidget(aseco, player.login)


async def bct_onPlayerInfoChanged(aseco: "Aseco", info: dict):
    if _state.current_state == STATE_SCORE:
        return

    login = str(info.get("Login", "") or "")
    if not login:
        return

    player = aseco.server.players.get_player(login)
    if not player:
        return

    spectator_status = int(info.get("SpectatorStatus", 0) or 0)
    if spectator_status > 0:
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
        await bct_buildWidget(aseco, login)
        await bct_buildCheckpointsTimeInlay(aseco)


async def bct_onPlayerManialinkPageAnswer(aseco: "Aseco", answer: list):
    if len(answer) < 3:
        return
    action = int(answer[2] or 0)
    if action == 0:
        return

    login = answer[1]
    if action == ACTION_HELP:
        await bct_buildHelpWindow(aseco, login, True)
    elif action == ACTION_CLOSE_HELP:
        await bct_buildHelpWindow(aseco, login, False)


async def bct_onNewChallenge2(aseco: "Aseco", challenge_item):
    _state.current_state = STATE_RACE
    await bct_buildWidget(aseco, None)

    _state.challenge_num_cps = int(getattr(challenge_item, "nbchecks", 0) or _state.show_max_checkpoints)
    _state.challenge_multilap = bool(getattr(challenge_item, "laprace", False))
    _state.checkpoint_times = {
        cp: {"Score": 0, "Nickname": "---"} for cp in range(_state.challenge_num_cps)
    }
    await bct_buildCheckpointsTimeInlay(aseco)


async def bct_onRestartChallenge(aseco: "Aseco", _challenge_item):
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
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def bct_buildWidget(aseco: "Aseco", login: str | None = None):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<manialinks>"
        f'<manialink id="{ML_INLAY}">'
        f'<frame posn="{_state.widget.position_x} {_state.widget.position_y} 3">'
        f'<label posn="35.2 -0.5 0.12" sizen="2.85 19" action="{ACTION_HELP}" '
        'focusareacolor1="FFF9" focusareacolor2="FFFF" text=" "/>'
        "</frame>"
        "</manialink>"
        f'<manialink id="{ML_WIDGET}">'
        f'<frame posn="{_state.widget.position_x} {_state.widget.position_y} 3">'
        '<quad posn="-0.5 -0.5 0.11" sizen="38.6 18" style="BgsPlayerCard" substyle="ProgressBar"/>'
        '<quad posn="17.5 -0.65 0.13" sizen="0.1 18" bgcolor="FFF5"/>'
        f'<quad posn="35 1 0.13" sizen="3.3 3.3" action="{ACTION_HELP}" style="BgRaceScore2" substyle="ScoreLink"/>'
        f'<quad posn="35.6 -12.8 0.13" sizen="2 2" action="{ACTION_HELP}" style="Icons64x64_1" substyle="TrackInfo"/>'
        "</frame>"
        "</manialink>"
        "</manialinks>"
    )

    if login:
        await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)
    else:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def bct_buildHelpWindow(aseco: "Aseco", login: str, display: bool = True):
    message = [
        "With this Widget you can see who has the fastest Time/Score at the related Checkpoint. The last fastest Time/Score blinks,",
        "so you can easy find the latest beaten Checkpoint.",
        "",
        "If nobody has a fastest Time/Score at some Checkpoint, then the Widget displays empty times. After someone drives through",
        "a Checkpoint, this time is indicated in the Widget.",
    ]

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<manialinks>",
        f'<manialink id="{ML_HELP}">',
    ]

    if display:
        parts.extend(
            [
                '<frame posn="-40.1 30.45 -3">',
                '<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="000B"/>',
                '<quad posn="-0.2 0.2 0.09" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>',
                '<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="09FC"/>',
                '<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>',
                '<quad posn="1.8 -1.4 0.10" sizen="2.8 2.8" style="BgRaceScore2" substyle="ScoreLink"/>',
                '<label posn="5.5 -1.8 0.10" sizen="74 0" halign="left" textsize="2" scale="0.9" textcolor="FFFF" text="Help for Best Checkpoint Times"/>',
                '<quad posn="2.7 -54.1 0.12" sizen="16 1" url="http://www.undef.de/Trackmania/Plugins/" bgcolor="0000"/>',
                f'<label posn="2.7 -54.1 0.12" sizen="30 1" halign="left" textsize="1" scale="0.7" textcolor="000F" text="BEST-CHECKPOINT-TIMES/{_state.version}"/>',
                '<frame posn="77.4 1.3 0">',
                '<quad posn="0 0 0.10" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>',
                '<quad posn="1.1 -1.35 0.11" sizen="1.8 1.75" bgcolor="EEEF"/>',
                f'<quad posn="0.65 -0.7 0.12" sizen="2.6 2.6" action="{ACTION_CLOSE_HELP}" style="Icons64x64_1" substyle="Close"/>',
                "</frame>",
                '<frame posn="3 -6 0">',
            ]
        )

        position = 0.0
        line_height = 1.65
        width = 75.0
        for msg in message:
            if msg:
                parts.append(
                    f'<label posn="0 {position:.2f} 0.05" sizen="{width - 2.6:.2f} 0" '
                    f'halign="left" textsize="1" textcolor="FFFF" text="{escape(msg)}"/>'
                )
            position -= line_height

        parts.extend(["</frame>", "</frame>"])

    parts.extend(["</manialink>", "</manialinks>"])
    await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, "".join(parts), 0, False)


async def bct_buildCheckpointsTimeInlay(aseco: "Aseco", cpid: int = -1):
    checkpoint_id = cpid if cpid != -1 else 0

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<manialinks>",
        f'<manialink id="{ML_INLAY}">',
        f'<frame posn="{_state.widget.position_x} {_state.widget.position_y} 3">',
        f'<label posn="35.2 -0.5 0.12" sizen="2.85 19" action="{ACTION_HELP}" focusareacolor1="FFF9" focusareacolor2="FFFF" text=" "/>',
    ]

    lines = 1
    posx = 0.0
    offsety = 1.37
    checkpoint_count = 0
    mode = getattr(getattr(aseco.server, "gameinfo", None), "mode", -1)

    for cp in range(_state.challenge_num_cps):
        if (cp + 1) > _state.show_max_checkpoints:
            break
        if (checkpoint_count + 1) == _state.challenge_num_cps:
            break
        if cp not in _state.checkpoint_times:
            break

        if lines == 11:
            lines = 1
        posy = -(offsety * lines)

        if checkpoint_count in (10, 20):
            posx += 18

        if checkpoint_count == checkpoint_id and cpid != -1:
            parts.append('<format style="TextTitle2Blink"/>')
        else:
            parts.append('<format style="TextStaticMedium"/>')

        entry = _state.checkpoint_times[cp]
        score_val = int(entry.get("Score", 0) or 0)
        nick = str(entry.get("Nickname", "---"))

        score_txt = str(score_val) if mode == 4 else bct_formatTime(score_val)
        parts.append(
            f'<label posn="{posx + 1.85:.2f} {posy:.2f} 0.14" sizen="1.5 0" halign="right" '
            f'textsize="{_state.widget.textsize}" scale="{_state.widget.textscale}" text="$FFF{cp + 1}."/>'
        )
        parts.append(
            f'<label posn="{posx + 6.3:.2f} {posy:.2f} 0.14" sizen="4.3 0" halign="right" '
            f'textsize="{_state.widget.textsize}" scale="{_state.widget.textscale}" text="$FFF{escape(score_txt)}"/>'
        )
        parts.append(
            f'<label posn="{posx + 6.8:.2f} {posy:.2f} 0.14" sizen="11 0" '
            f'textsize="{_state.widget.textsize}" scale="{_state.widget.textscale}" text="$FFF{nick}"/>'
        )

        checkpoint_count += 1
        lines += 1

    parts.extend(["</frame>", "</manialink>", "</manialinks>"])
    xml = "".join(parts)

    logins = []
    for player in aseco.server.players.all():
        if player.login not in _state.hidden_logins:
            logins.append(player.login)

    if not logins:
        return

    login_list = ",".join(logins)
    await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login_list, xml, 0, False)


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
