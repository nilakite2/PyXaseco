"""
bestcps.py — Python base port of the legacy bestcps PHP module

Displays best checkpoint times on the current challenge in a compact widget,
with a per-player toggle via `/bestcps`.
"""

from __future__ import annotations

from pyxaseco.core.widget_delivery import deliver_ui

import html
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyxaseco.models import Gameinfo
from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_float, as_int, bind_app_settings
from pyxaseco.core.config import display_path

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

WIDGET_ID = 123123456


@dataclass
class CpTime:
    time: int
    nickname: str


@dataclass
class BestCpsConfig:
    pos_x: float = -58.0
    pos_y: float = 44.8
    number: int = 30
    newline: int = 10
    rows: int = 0
    orientation: int = 0
    pos_x_counter: float = 0.0
    pos_y_counter: float = -35.0


_tab_cp_time: dict[int, CpTime] = {}
_hidden_for: set[str] = set()
_config = BestCpsConfig()
_last_widget_xml: dict[str, str] = {}
_widget_dirty = False

BESTCPS_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id="bestcps",
    settings=(
        AppSetting("config/position/x", -58.0, cast=as_float, description="Widget X position.", category="layout"),
        AppSetting("config/position/y", 44.8, cast=as_float, description="Widget Y position.", category="layout"),
        AppSetting("config/number", 30, cast=as_int, description="Number of entries to display.", category="display"),
        AppSetting("config/newline", 10, cast=as_int, description="Entries per line.", category="display"),
        AppSetting("config/rows", 0, cast=as_int, description="Number of rows to show.", category="display"),
        AppSetting("config/orientation", 0, cast=as_int, description="Widget orientation mode.", category="display"),
        AppSetting("config/position/x_counter", 0.0, cast=as_float, description="Counter X position.", category="layout"),
        AppSetting("config/position/y_counter", -35.0, cast=as_float, description="Counter Y position.", category="layout"),
    ),
    description="Best checkpoint widget settings.",
)


def register(aseco: 'Aseco'):
    _load_config(aseco)
    aseco.register_event('onSync', _bestcps_sync)
    aseco.register_event('onPlayerConnect', _bestcps_player_connect)
    aseco.register_event('onPlayerDisconnect', _bestcps_player_disconnect)
    aseco.register_event('onCheckpoint', _bestcps_checkpoint)
    aseco.register_event('onCheckpoint', _bestcps_refresh)
    aseco.register_event('onBeginRound', _bestcps_begin_round)
    aseco.register_event('onRestartChallenge', _bestcps_begin_round)
    aseco.register_event('onEndRace', _bestcps_end_race)
    aseco.register_event('onNewChallenge', _bestcps_new_challenge)
    aseco.register_event('onPlayerFinish', _bestcps_player_finish)

    aseco.add_chat_command('bestcps', 'Toggle show/hide bestcps')
    aseco.register_event('onChat_bestcps', chat_bestcps)


def _parse_int(text: str, default: int) -> int:
    try:
        return int(str(text).strip())
    except Exception:
        return default


def _parse_float(text: str, default: float) -> float:
    try:
        return float(str(text).strip())
    except Exception:
        return default


def _load_config(aseco: 'Aseco'):
    global _config
    bound = bind_app_settings(BESTCPS_SETTINGS_SCHEMA, getattr(aseco, '_base_dir', None))
    path = bound.source_path
    if path is None:
        return
    _config = BestCpsConfig(
        pos_x=bound.values["config/position/x"],
        pos_y=bound.values["config/position/y"],
        number=max(1, bound.values["config/number"]),
        newline=max(1, bound.values["config/newline"]),
        rows=max(0, bound.values["config/rows"]),
        orientation=bound.values["config/orientation"],
        pos_x_counter=bound.values["config/position/x_counter"],
        pos_y_counter=bound.values["config/position/y_counter"],
    )
    logger.info(
        '[BestCps] Config loaded from %s (x=%s, y=%s, number=%s, newline=%s, rows=%s, orientation=%s)',
        display_path(path),
        _config.pos_x,
        _config.pos_y,
        _config.number,
        _config.newline,
        _config.rows,
        _config.orientation,
    )


def _format_cp_time(ms: int) -> str:
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    centis = (ms % 1000) // 10
    return f'{minutes}:{seconds:02d}.{centis:02d}'


def _esc(value: str) -> str:
    return html.escape(str(value or ''), quote=True)


def _is_score_mode(aseco: 'Aseco') -> bool:
    from pyxaseco.core.widget_delivery import is_score_phase
    return is_score_phase(aseco)


async def _send_widget_xml(aseco: 'Aseco', login: str, xml: str):
    await deliver_ui(aseco, 
        'SendDisplayManialinkPageToLogin',
        login,
        aseco.format_colors(xml),
        0,
        False,
    )
    for recipient in login.split(','):
        _last_widget_xml[recipient] = xml


async def _hide_widget_for_user(aseco: 'Aseco', login: str):
    await _send_widget_xml(aseco, login, f'<manialink id="{WIDGET_ID}"></manialink>')


def _build_widget_xml() -> str:
    cell_width_h = 14.3
    column_step_h = 14.3
    time_label_width_h = 5.9
    nick_label_width_h = 6.8
    cell_width_v = 16.8

    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append(f'<manialink id="{WIDGET_ID}">')
    xml.append(f'<frame posn="{_config.pos_x} {_config.pos_y}">')
    xml.append('<format textsize="1"/>')

    entries = [(place, _tab_cp_time[cp_index]) for place, cp_index in enumerate(sorted(_tab_cp_time), start=1)]
    if _config.orientation == 0 and _config.rows > 0:
        entries = entries[: _config.newline * _config.rows]
    elif _config.rows > 0:
        entries = entries[: _config.rows]
    count = len(entries)

    if _config.orientation in (2, 3) and count > 0:
        height = count * 2 + 0.2
        xml.append(
            f'<quad posn="0 1.1" sizen="{cell_width_v} {height}" halign="center" valign="top" '
            'style="Bgs1InRace" substyle="NavButton" />'
        )

    if _config.orientation == 0:
        line = 0
        col = 0
        for place, value in entries:
            text = f'$z{place:02d}. {_format_cp_time(value.time)}'

            if place == ((line + 1) * _config.newline + 1):
                line += 1
                col = 0

            posx = col * column_step_h
            posy = -(line * 2.25)

            xml.append(
                f'<quad posn="{posx} {posy}" sizen="{cell_width_h} 2.2" halign="center" valign="center" '
                'style="Bgs1InRace" substyle="NavButton" />'
            )
            xml.append(
                f'<label posn="{posx - 6.7} {posy}" sizen="{time_label_width_h} 2" halign="left" valign="center" '
                f'text="{_esc(text)}"/>'
            )
            xml.append(
                f'<label posn="{posx - 0.1} {posy}" sizen="{nick_label_width_h} 2" halign="left" valign="center" '
                f'text="{_esc(value.nickname)}"/>'
            )
            col += 1
    elif _config.orientation == 1:
        for idx, (place, value) in enumerate(entries):
            text = f'$z{place}. {_format_cp_time(value.time)}'
            posy = idx * -2
            xml.append(
                f'<quad posn="0 {posy}" sizen="{cell_width_v} 2.2" halign="center" valign="center" '
                'style="Bgs1InRace" substyle="NavButton" />'
            )
            xml.append(
                f'<label posn="-7.55 {posy + 0.1}" sizen="6.4 2" halign="left" valign="center" '
                f'text="{_esc(text)}"/>'
            )
            xml.append(
                f'<label posn="0.15 {posy + 0.1}" sizen="7.0 2" halign="left" valign="center" '
                f'text="{_esc(value.nickname)}"/>'
            )
    else:
        for idx, (place, value) in enumerate(entries):
            text = f'$z{place}. {_format_cp_time(value.time)}'
            posy = idx * -2 + 0.1
            xml.append(
                f'<label posn="-7.35 {posy}" sizen="6.4 2" halign="left" valign="center" '
                f'text="{_esc(text)}"/>'
            )
            xml.append(
                f'<label posn="0.15 {posy}" sizen="7.0 2" halign="left" valign="center" '
                f'text="{_esc(value.nickname)}"/>'
            )

    xml.append('</frame></manialink>')
    return ''.join(xml)


async def _broadcast_widget(aseco: 'Aseco'):
    if _is_score_mode(aseco):
        _last_widget_xml.clear()
        await deliver_ui(aseco, 
            'SendDisplayManialinkPage',
            f'<manialink id="{WIDGET_ID}"></manialink>',
            0,
            False,
        )
        return
    xml = _build_widget_xml()
    recipients = [
        player.login for player in aseco.server.players.all()
        if player.login not in _hidden_for and _last_widget_xml.get(player.login) != xml
    ]
    if recipients:
        await _send_widget_xml(aseco, ','.join(recipients), xml)


async def _bestcps_sync(aseco: 'Aseco', _param=None):
    _last_widget_xml.clear()
    _load_config(aseco)
    if _tab_cp_time:
        await _broadcast_widget(aseco)


async def _bestcps_player_connect(aseco: 'Aseco', player: 'Player'):
    _last_widget_xml.pop(player.login, None)
    _load_config(aseco)
    if _is_score_mode(aseco):
        await _hide_widget_for_user(aseco, player.login)
        return
    if player.login not in _hidden_for and _tab_cp_time:
        await _send_widget_xml(aseco, player.login, _build_widget_xml())


async def _bestcps_player_disconnect(aseco: 'Aseco', player: 'Player'):
    _last_widget_xml.pop(player.login, None)
    _hidden_for.discard(player.login)


async def _bestcps_new_challenge(aseco: 'Aseco', challenge):
    global _widget_dirty
    _widget_dirty = False
    _last_widget_xml.clear()
    _load_config(aseco)
    _tab_cp_time.clear()
    await deliver_ui(aseco, 
        'SendDisplayManialinkPage',
        f'<manialink id="{WIDGET_ID}"></manialink>',
        1,
        False,
    )
async def _bestcps_player_finish(aseco: 'Aseco', record):
    # Preserved only as a compatibility hook from the original plugin.
    return


async def _bestcps_begin_round(aseco: 'Aseco', _param=None):
    _last_widget_xml.clear()
    if _tab_cp_time:
        await _broadcast_widget(aseco)


async def _bestcps_end_race(aseco: 'Aseco', _param=None):
    _last_widget_xml.clear()
    await deliver_ui(aseco, 
        'SendDisplayManialinkPage',
        f'<manialink id="{WIDGET_ID}"></manialink>',
        0,
        False,
    )


async def _bestcps_checkpoint(aseco: 'Aseco', param: list):
    global _widget_dirty
    if len(param) < 5:
        return

    try:
        login = param[1]
        time_ms = int(param[2])
        cp_index = int(param[4])
    except Exception:
        return

    challenge = getattr(aseco.server, 'challenge', None)
    nbchecks = int(getattr(challenge, 'nbchecks', 0) or 0)

    if cp_index == nbchecks - 1:
        return
    if cp_index >= _config.number:
        return

    player = aseco.server.players.get_player(login)
    if not player:
        return

    current = _tab_cp_time.get(cp_index)
    if current is None or time_ms < current.time:
        _tab_cp_time[cp_index] = CpTime(time=time_ms, nickname=player.nickname)
        _widget_dirty = True


async def _bestcps_refresh(aseco: 'Aseco', _record):
    global _widget_dirty
    if _is_score_mode(aseco):
        _last_widget_xml.clear()
        await deliver_ui(aseco, 
            'SendDisplayManialinkPage',
            f'<manialink id="{WIDGET_ID}"></manialink>',
            0,
            False,
        )
        return
    if _tab_cp_time and _widget_dirty:
        await _broadcast_widget(aseco)
        _widget_dirty = False


async def reload_bestcps_runtime(aseco: 'Aseco') -> None:
    _last_widget_xml.clear()
    _load_config(aseco)
    if _is_score_mode(aseco) or not _tab_cp_time:
        await _bestcps_end_race(aseco)
        return
    await _broadcast_widget(aseco)


async def chat_bestcps(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login

    if login in _hidden_for:
        _hidden_for.discard(login)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            'Bestcps widget enabled',
            login,
        )
        if _tab_cp_time:
            await _send_widget_xml(aseco, login, _build_widget_xml())
    else:
        _hidden_for.add(login)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            'Bestcps widget disabled',
            login,
        )
        await _hide_widget_for_user(aseco, login)
