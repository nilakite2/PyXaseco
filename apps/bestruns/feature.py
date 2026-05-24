from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyxaseco.models import Gameinfo
from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_float, as_int, bind_app_settings

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Record, Challenge, Player

logger = logging.getLogger(__name__)

ML_ID = 342312


@dataclass
class BestRunsConfig:
    x: float = -52.0
    y: float = 48.0
    scale: float = 1.0
    nb_bestruns: int = 7
    nb_bestruns_with_cp: int = 2
    nb_max_checkpoints: int = 9


@dataclass
class BestRunsState:
    config: BestRunsConfig = field(default_factory=BestRunsConfig)
    bestruns: list[Any] = field(default_factory=list)
    count: int = 0
    cps: int = 0


_state = BestRunsState()

BESTRUNS_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id="bestruns",
    settings=(
        AppSetting("config/position/x", -52.0, cast=as_float, description="Widget X position.", category="layout"),
        AppSetting("config/position/y", 48.0, cast=as_float, description="Widget Y position.", category="layout"),
        AppSetting("config/scale", 1.0, cast=as_float, description="Widget scale.", category="layout"),
        AppSetting("config/nb_bestruns", 7, cast=as_int, aliases=("config/number",), description="Number of runs to display.", category="display"),
        AppSetting("config/nb_bestruns_with_cp", 2, cast=as_int, aliases=("config/number_with_cps",), description="Runs with checkpoint details.", category="display"),
        AppSetting("config/nb_max_checkpoints", 9, cast=as_int, aliases=("config/max_checkpoints",), description="Maximum checkpoints shown.", category="display"),
    ),
    description="Best runs widget settings.",
)


def register(aseco: "Aseco"):
    LoadConfig_bestruns(aseco)
    aseco.register_event("onStartup", OnStartup_bestruns)
    aseco.register_event("onNewChallenge", OnNewChallenge_bestruns)
    aseco.register_event("onBeginRound", OnBeginRound_bestruns)
    aseco.register_event("onEndRace", OnEndRace_bestruns)
    aseco.register_event("onPlayerFinish", OnPlayerFinish_bestruns)
    aseco.register_event("onPlayerConnect", OnPlayerConnect_bestruns)

    aseco.add_chat_command("bestruns", "Load config file of bestruns plugin")
    aseco.register_event("onChat_bestruns", chat_bestruns)


async def chat_bestruns(aseco: "Aseco", command: dict):
    author = command["author"]
    if aseco.is_master_admin(author) or aseco.is_admin(author):
        LoadConfig_bestruns(aseco)
        await aseco.client.query_ignore_result(
            "ChatSendServerMessage",
            aseco.format_colors("{#server}> {#message}Load Config BestRuns OK"),
        )
        await Display_bestruns(aseco)


async def OnStartup_bestruns(aseco: "Aseco", _empty):
    _state.bestruns = []
    _state.count = 0
    _state.cps = 0
    LoadConfig_bestruns(aseco)


async def OnPlayerConnect_bestruns(aseco: "Aseco", _player: "Player"):
    # Keep widget visible / initialized for newly connected players.
    await Display_bestruns(aseco)


async def OnBeginRound_bestruns(aseco: "Aseco", _param=None):
    await Display_bestruns(aseco)


async def OnEndRace_bestruns(aseco: "Aseco", _param=None):
    await Clear_bestruns(aseco, None)


async def OnNewChallenge_bestruns(aseco: "Aseco", challenge: "Challenge"):
    _state.cps = max(0, int(getattr(challenge, "nbchecks", 0) or 0) - 1)
    _state.count = 0
    _state.bestruns = []
    await Clear_bestruns(aseco, challenge)
    # Immediately redraw empty state so the widget area exists on the new map.
    await Display_bestruns(aseco)


def _extract_record_from_finish(aseco: "Aseco", payload: Any) -> Any | None:
    """
    Accept either:
      - a Record-like object with .score/.player/.checks
      - raw onPlayerFinish params list: [uid, login, score]
    Returns an object with:
      .score
      .player.nickname
      .player.login
      .checks
    """
    # Record-like object path
    if hasattr(payload, "score") and hasattr(payload, "player"):
        try:
            score = int(getattr(payload, "score", 0) or 0)
        except Exception:
            score = 0
        if score > 0:
            return payload
        return None

    # Raw params path
    if isinstance(payload, (list, tuple)) and len(payload) >= 3:
        try:
            login = str(payload[1] or "")
            score = int(payload[2] or 0)
        except Exception:
            return None

        if not login or score <= 0:
            return None

        player = aseco.server.players.get_player(login)
        if not player:
            return None

        checks: list[int] = []
        try:
            from apps.platform_core.checkpoints import checkpoints
            cp = checkpoints.get(login)
            if cp and getattr(cp, "curr_cps", None):
                checks = [int(x) for x in cp.curr_cps]
        except Exception:
            checks = []

        class _Run:
            pass

        run = _Run()
        run.score = score
        run.player = player
        run.checks = checks
        return run

    return None


async def OnPlayerFinish_bestruns(aseco: "Aseco", payload):
    record = _extract_record_from_finish(aseco, payload)
    if not record:
        return

    score = int(getattr(record, "score", 0) or 0)
    max_runs = max(1, int(_state.config.nb_bestruns))

    if _state.count == 0:
        _state.bestruns = [record]
        _state.count = 1

    elif _state.count < max_runs:
        pos = 0
        while pos < _state.count:
            if score < int(getattr(_state.bestruns[pos], "score", 0) or 0):
                break
            pos += 1
        _state.bestruns.insert(pos, record)
        _state.count += 1

    else:
        worst_score = int(getattr(_state.bestruns[max_runs - 1], "score", 0) or 0)
        if score < worst_score:
            pos = 0
            while pos < _state.count:
                if score < int(getattr(_state.bestruns[pos], "score", 0) or 0):
                    break
                pos += 1
            _state.bestruns.insert(pos, record)
            _state.bestruns = _state.bestruns[:max_runs]
            _state.count = len(_state.bestruns)

    await Display_bestruns(aseco)


def LoadConfig_bestruns(aseco: "Aseco"):
    bound = bind_app_settings(BESTRUNS_SETTINGS_SCHEMA, getattr(aseco, "_base_dir", None))
    path = bound.source_path
    if path is None:
        return
    _state.config.x = bound.values["config/position/x"]
    _state.config.y = bound.values["config/position/y"]
    _state.config.scale = bound.values["config/scale"]
    _state.config.nb_bestruns = max(1, bound.values["config/nb_bestruns"])
    _state.config.nb_bestruns_with_cp = max(1, bound.values["config/nb_bestruns_with_cp"])
    _state.config.nb_max_checkpoints = max(1, bound.values["config/nb_max_checkpoints"])
    logger.info("[BestRuns] Config loaded from %s", path)


def _format_score(ms: int) -> str:
    minutes = ms // 60000
    seconds = (ms - minutes * 60000) // 1000
    centis = (ms - minutes * 60000 - seconds * 1000) // 10
    return f"{minutes}:{seconds:02d}.{centis:02d}"


def _is_score_mode(aseco: "Aseco") -> bool:
    return getattr(getattr(aseco.server, "gameinfo", None), "mode", -1) == getattr(Gameinfo, "SCOR", 7)


async def Display_bestruns(aseco: "Aseco"):
    if _is_score_mode(aseco):
        await Clear_bestruns(aseco, None)
        return

    cfg = _state.config
    x_frame_widget = cfg.x
    y_frame_widget = cfg.y

    textsize = 0.8
    textsize_cp = 0.9
    nb_col = 3

    width_bestrun = 14.3
    height_main = 2.2

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<manialink id="{ML_ID}">',
        f'<frame posn="{x_frame_widget} {y_frame_widget}">',
        f'<format textsize="{textsize}"/>',
    ]

    # Even with no runs, keep an empty anchor frame so the plugin is visibly active.
    if _state.count == 0:
        xml_parts.extend(
            [
                f'<frame posn="0 0">',
                #f'<quad scale="{cfg.scale}" posn="0 0" sizen="{width_bestrun} {height_main}" '
                #'halign="left" valign="top" style="Bgs1InRace" substyle="NavButton" />',
                #f'<label scale="{cfg.scale}" posn="0.6 -1.0" sizen="13 2" '
                #'halign="left" valign="center" text="$z$fffBestRuns"/>',
                "</frame>",
            ]
        )
    else:
        for i in range(_state.count):
            rec = _state.bestruns[i]
            x_frame_bestrun = i * width_bestrun * cfg.scale
            y_frame_bestrun = 0

            x_frame_main = 0
            y_frame_main = 0

            width_quad_main = width_bestrun
            height_quad_main = height_main

            x_offset_label_time = 0.6
            y_offset_label_time = -1.0
            x_label_time = (0 + x_offset_label_time) * cfg.scale
            y_label_time = (0 + y_offset_label_time) * cfg.scale
            width_label_time = 5.8
            height_label_time = 2

            x_offset_label_nickname = 0.6
            y_offset_label_nickname = -1.0
            x_label_nickname = (width_label_time + x_offset_label_nickname) * cfg.scale
            y_label_nickname = (0 + y_offset_label_nickname) * cfg.scale
            width_label_nickname = 6.9
            height_label_nickname = 2

            x_frame_cps = 0
            y_frame_cps = (-height_main) * cfg.scale

            score_val = int(getattr(rec, "score", 0) or 0)
            player = getattr(rec, "player", None)
            nickname = getattr(player, "nickname", "") if player else ""
            if not nickname and player:
                nickname = getattr(player, "login", "")
            time_txt = f"$z{i + 1}. $fff{_format_score(score_val)}"

            xml_parts.extend(
                [
                    f'<frame posn="{x_frame_bestrun} {y_frame_bestrun}">',
                    f'<frame posn="{x_frame_main} {y_frame_main}">',
                    f'<quad scale="{cfg.scale}" posn="0 0" sizen="{width_quad_main} {height_quad_main}" '
                    'halign="left" valign="top" style="Bgs1InRace" substyle="NavButton" />',
                    f'<label scale="{cfg.scale}" posn="{x_label_time} {y_label_time}" '
                    f'sizen="{width_label_time} {height_label_time}" halign="left" valign="center" text="{time_txt}"/>',
                    f'<label scale="{cfg.scale}" posn="{x_label_nickname} {y_label_nickname}" '
                    f'sizen="{width_label_nickname} {height_label_nickname}" halign="left" valign="center" text="{nickname}"/>',
                    "</frame>",
                ]
            )

            if i < cfg.nb_bestruns_with_cp:
                xml_parts.extend(
                    [
                        f'<frame posn="{x_frame_cps} {y_frame_cps}">',
                        f'<format textsize="{textsize_cp}"/>',
                    ]
                )
                checks = list(getattr(rec, "checks", []) or [])
                max_cps = min(_state.cps, cfg.nb_max_checkpoints)
                for j in range(max_cps):
                    if j >= len(checks):
                        break

                    cp = int(checks[j] or 0)
                    textee = f"$z$fff{_format_score(cp)}"

                    width_quad_cp = width_bestrun / nb_col
                    height_quad_cp = 1.6
                    x_quad_cp = (j % nb_col) * width_quad_cp * cfg.scale
                    y_quad_cp = (-((j // nb_col) * height_quad_cp)) * cfg.scale

                    y_offset_label_cp = -0.3
                    x_label_cp = (((j % nb_col) * width_quad_cp) + width_quad_cp / 2) * cfg.scale
                    y_label_cp = ((-((j // nb_col) * height_quad_cp)) + y_offset_label_cp) * cfg.scale
                    width_label_cp = width_quad_cp
                    height_label_cp = height_quad_cp

                    xml_parts.extend(
                        [
                            f'<quad scale="{cfg.scale}" posn="{x_quad_cp} {y_quad_cp}" '
                            f'sizen="{width_quad_cp} {height_quad_cp}" halign="left" valign="top" '
                            'style="Bgs1InRace" substyle="NavButton" />',
                            f'<label scale="{cfg.scale}" posn="{x_label_cp} {y_label_cp}" '
                            f'sizen="{width_label_cp} {height_label_cp}" halign="center" valign="top" text="{textee}"/>',
                        ]
                    )

                xml_parts.append("</frame>")

            xml_parts.append("</frame>")

    xml_parts.extend(["</frame>", "</manialink>"])
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", "".join(xml_parts), 0, False)


async def Clear_bestruns(aseco: "Aseco", _challenge):
    xml = f'<manialink id="{ML_ID}"></manialink>'
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 1, False)
