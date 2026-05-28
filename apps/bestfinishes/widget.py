from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from pyxaseco.models import Gameinfo
from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_float, as_int, bind_app_settings
from pyxaseco.core.config import display_path

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Record, Challenge, Player

logger = logging.getLogger(__name__)

ML_ID = 342312


@dataclass
class BestFinishesConfig:
    x: float = -52.0
    y: float = 48.0
    scale: float = 1.0
    nb_bestfinishes: int = 7


@dataclass
class BestFinishesState:
    config: BestFinishesConfig = field(default_factory=BestFinishesConfig)
    bestfinishes: list[Any] = field(default_factory=list)
    count: int = 0


_state = BestFinishesState()

BESTFINISHES_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id="bestfinishes",
    settings=(
        AppSetting("config/x", 35.0, cast=as_float, description="Widget X position.", category="layout"),
        AppSetting("config/y", 48.0, cast=as_float, description="Widget Y position.", category="layout"),
        AppSetting("config/scale", 1.0, cast=as_float, description="Widget scale.", category="layout"),
        AppSetting("config/nb_bestfinishes", 5, cast=as_int, description="Number of finish times to display.", category="display"),
    ),
    description="Best finishes widget settings.",
)


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", OnStartup_bestfinishes)
    aseco.register_event("onNewChallenge", OnNewChallenge_bestfinishes)
    aseco.register_event("onEndRace", OnEndRace_bestfinishes)
    aseco.register_event("onPlayerFinish", OnPlayerFinish_bestfinishes)
    aseco.register_event("onPlayerConnect", OnPlayerConnect_bestfinishes)

    aseco.add_chat_command("bestfinishes", "Load config file of bestfinishes plugin")
    aseco.register_event("onChat_bestfinishes", chat_bestfinishes)


async def chat_bestfinishes(aseco: "Aseco", command: dict):
    author = command["author"]
    if aseco.is_master_admin(author) or aseco.is_admin(author):
        LoadConfig_bestfinishes(aseco)
        await aseco.client.query_ignore_result(
            "ChatSendServerMessage",
            aseco.format_colors("{#server}> {#message}Load Config BestFinishes OK"),
        )
        await Display_bestfinishes(aseco)


async def OnStartup_bestfinishes(aseco: "Aseco", _empty):
    _state.bestfinishes = []
    _state.count = 0
    LoadConfig_bestfinishes(aseco)


async def OnPlayerConnect_bestfinishes(aseco: "Aseco", _player: "Player"):
    if getattr(getattr(aseco.server, "gameinfo", None), "mode", -1) == getattr(Gameinfo, "SCOR", 7):
        return
    # Keep widget visible / initialized for newly connected players.
    await Display_bestfinishes(aseco)


async def OnNewChallenge_bestfinishes(aseco: "Aseco", challenge: "Challenge"):
    _state.count = 0
    _state.bestfinishes = []
    await Clear_bestfinishes(aseco, challenge)
    # Immediately redraw empty state so the widget area exists on the new map.
    await Display_bestfinishes(aseco)


async def OnEndRace_bestfinishes(aseco: "Aseco", _race):
    await Clear_bestfinishes(aseco, None)


def _extract_record_from_finish(aseco: "Aseco", payload: Any) -> Any | None:
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


async def OnPlayerFinish_bestfinishes(aseco: "Aseco", payload):
    record = _extract_record_from_finish(aseco, payload)
    if not record:
        return

    score = int(getattr(record, "score", 0) or 0)
    max_runs = max(1, int(_state.config.nb_bestfinishes))

    if _state.count == 0:
        _state.bestfinishes = [record]
        _state.count = 1

    elif _state.count < max_runs:
        pos = 0
        while pos < _state.count:
            if score < int(getattr(_state.bestfinishes[pos], "score", 0) or 0):
                break
            pos += 1
        _state.bestfinishes.insert(pos, record)
        _state.count += 1

    else:
        worst_score = int(getattr(_state.bestfinishes[max_runs - 1], "score", 0) or 0)
        if score < worst_score:
            pos = 0
            while pos < _state.count:
                if score < int(getattr(_state.bestfinishes[pos], "score", 0) or 0):
                    break
                pos += 1
            _state.bestfinishes.insert(pos, record)
            _state.bestfinishes = _state.bestfinishes[:max_runs]
            _state.count = len(_state.bestfinishes)

    await Display_bestfinishes(aseco)


def LoadConfig_bestfinishes(aseco: "Aseco"):
    bound = bind_app_settings(BESTFINISHES_SETTINGS_SCHEMA, getattr(aseco, "_base_dir", None))
    path = bound.source_path
    if path is None:
        return
    _state.config.x = bound.values["config/x"]
    _state.config.y = bound.values["config/y"]
    _state.config.scale = bound.values["config/scale"]
    _state.config.nb_bestfinishes = max(1, bound.values["config/nb_bestfinishes"])
    logger.info("[BestFinishes] Config loaded from %s", display_path(path))


def _format_score(ms: int) -> str:
    minutes = ms // 60000
    seconds = (ms - minutes * 60000) // 1000
    centis = (ms - minutes * 60000 - seconds * 1000) // 10
    return f"{minutes}:{seconds:02d}.{centis:02d}"


async def Display_bestfinishes(aseco: "Aseco"):
    cfg = _state.config
    x_frame_widget = cfg.x
    y_frame_widget = cfg.y

    textsize = 1

    width_bestrun = 14
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
                f'<quad scale="{cfg.scale}" posn="0 0" sizen="{width_bestrun} {height_main}" '
                'halign="left" valign="top" style="Bgs1InRace" substyle="NavButton" />',
                f'<label scale="{cfg.scale}" posn="0.6 -0.3" sizen="13 2" '
                'halign="left" valign="top" text="$z$s$fffBest Finishes"/>',
                "</frame>",
            ]
        )
    else:
        y_cursor = 0.0
        for i in range(_state.count):
            rec = _state.bestfinishes[i]
            x_frame_bestrun = 0
            y_frame_bestrun = y_cursor

            x_frame_main = 0
            y_frame_main = 0

            width_quad_main = width_bestrun
            height_quad_main = height_main

            x_offset_label_time = 0.6
            y_offset_label_time = -0.3
            x_label_time = (0 + x_offset_label_time) * cfg.scale
            y_label_time = (0 + y_offset_label_time) * cfg.scale
            width_label_time = 5.8
            height_label_time = 2

            x_offset_label_nickname = 0.6
            y_offset_label_nickname = -0.3
            x_label_nickname = (width_label_time + x_offset_label_nickname) * cfg.scale
            y_label_nickname = (0 + y_offset_label_nickname) * cfg.scale
            width_label_nickname = 6.9
            height_label_nickname = 2

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
                    f'sizen="{width_label_time} {height_label_time}" halign="left" valign="top" text="{time_txt}"/>',
                    f'<label scale="{cfg.scale}" posn="{x_label_nickname} {y_label_nickname}" '
                    f'sizen="{width_label_nickname} {height_label_nickname}" halign="left" valign="top" text="{nickname}"/>',
                    "</frame>",
                ]
            )

            xml_parts.append("</frame>")
            y_cursor -= height_main * cfg.scale

    xml_parts.extend(["</frame>", "</manialink>"])
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", "".join(xml_parts), 0, False)


async def Clear_bestfinishes(aseco: "Aseco", _challenge):
    xml = f'<manialink id="{ML_ID}"></manialink>'
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 1, False)
