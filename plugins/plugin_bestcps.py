"""
plugin_bestcps.py — Python base port of plugin.bestcps.php

Displays best checkpoint times on the current challenge in a compact widget,
with a per-player toggle via `/bestcps` or the small Toggle BestCPs panel.
"""

from __future__ import annotations

import html
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

WIDGET_ID = 123123456
TOGGLE_ID = 123123457
ACTION_TOGGLE = 9000


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
    orientation: int = 0
    pos_x_counter: float = 0.0
    pos_y_counter: float = -35.0


_tab_cp_time: dict[int, CpTime] = {}
_hidden_for: set[str] = set()
_config = BestCpsConfig()


def register(aseco: 'Aseco'):
    aseco.register_event('onSync', _bestcps_sync)
    aseco.register_event('onPlayerConnect', _bestcps_player_connect)
    aseco.register_event('onCheckpoint', _bestcps_checkpoint)
    aseco.register_event('onCheckpoint', _bestcps_refresh)
    aseco.register_event('onNewChallenge', _bestcps_new_challenge)
    aseco.register_event('onPlayerFinish', _bestcps_player_finish)
    aseco.register_event('onPlayerManialinkPageAnswer', _bestcps_click)

    aseco.add_chat_command('bestcps', 'Toggle show/hide bestcps')
    aseco.register_event('onChat_bestcps', chat_bestcps)


def _config_path(aseco: 'Aseco') -> Path:
    return Path(getattr(aseco, '_base_dir', '.')).resolve() / 'bestcps.xml'


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

    path = _config_path(aseco)
    if not path.exists():
        logger.warning('[BestCps] bestcps.xml not found at %s, using defaults', path)
        _config = BestCpsConfig()
        return

    try:
        root = ET.parse(path).getroot()

        pos = root.find('position')
        pos_counter = root.find('position_counter')

        _config = BestCpsConfig(
            pos_x=_parse_float(pos.findtext('x', '-58') if pos is not None else '-58', -58.0),
            pos_y=_parse_float(pos.findtext('y', '44.8') if pos is not None else '44.8', 44.8),
            number=_parse_int(root.findtext('number', '30'), 30),
            newline=max(1, _parse_int(root.findtext('newline', '10'), 10)),
            orientation=_parse_int(root.findtext('orientation', '0'), 0),
            pos_x_counter=_parse_float(pos_counter.findtext('x_counter', '0') if pos_counter is not None else '0', 0.0),
            pos_y_counter=_parse_float(pos_counter.findtext('y_counter', '-35') if pos_counter is not None else '-35', -35.0),
        )
    except Exception as e:
        logger.warning('[BestCps] Could not parse %s: %s', path, e)
        _config = BestCpsConfig()


def _format_cp_time(ms: int) -> str:
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    centis = (ms % 1000) // 10
    return f'{minutes}:{seconds:02d}.{centis:02d}'


def _esc(value: str) -> str:
    return html.escape(str(value or ''), quote=True)


async def _send_widget_xml(aseco: 'Aseco', login: str, xml: str):
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin',
        login,
        aseco.format_colors(xml),
        0,
        False,
    )


async def _hide_widget_for_user(aseco: 'Aseco', login: str):
    await _send_widget_xml(aseco, login, f'<manialink id="{WIDGET_ID}"></manialink>')


def _build_toggle_xml() -> str:
    return (
        f'<manialink id="{TOGGLE_ID}">'
        '<frame posn="57.5 -32.25">'
        '<format textsize="0.5"/>'
        f'<label posn="1 1" sizen="5.5 2" halign="left" valign="center" text="Toggle BestCPs" action="{ACTION_TOGGLE}"/>'
        '</frame>'
        '</manialink>'
    )


async def _send_toggle(aseco: 'Aseco', login: str | None = None):
    xml = _build_toggle_xml()
    if login:
        await _send_widget_xml(aseco, login, xml)
    else:
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPage',
            aseco.format_colors(xml),
            0,
            False,
        )


def _build_widget_xml() -> str:
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append(f'<manialink id="{WIDGET_ID}">')
    xml.append(f'<frame posn="{_config.pos_x} {_config.pos_y}">')
    textsize = '0.5' if _config.orientation == 0 else '1'
    xml.append(f'<format textsize="{textsize}"/>')

    entries = [(place, _tab_cp_time[cp_index]) for place, cp_index in enumerate(sorted(_tab_cp_time), start=1)]
    count = len(entries)

    if _config.orientation in (2, 3) and count > 0:
        height = count * 2 + 0.2
        xml.append(
            f'<quad posn="0 1.1" sizen="14 {height}" halign="center" valign="top" '
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

            posx = col * 11.5
            posy = -(line * 2.25)

            xml.append(
                f'<quad posn="{posx} {posy}" sizen="11.5 2.2" halign="center" valign="center" '
                'style="Bgs1InRace" substyle="NavButton" />'
            )
            xml.append(
                f'<label posn="{posx - 5.25} {posy}" sizen="5.5 2" halign="left" valign="center" '
                f'text="{_esc(text)}"/>'
            )
            xml.append(
                f'<label posn="{posx - 0.35} {posy}" sizen="5.5 2" halign="left" valign="center" '
                f'text="{_esc(value.nickname)}"/>'
            )
            col += 1
    elif _config.orientation == 1:
        for idx, (place, value) in enumerate(entries):
            text = f'$z{place}. {_format_cp_time(value.time)}'
            posy = idx * -2
            xml.append(
                f'<quad posn="0 {posy}" sizen="14 2.2" halign="center" valign="center" '
                'style="Bgs1InRace" substyle="NavButton" />'
            )
            xml.append(
                f'<label posn="-6.5 {posy + 0.1}" sizen="6.5 2" halign="left" valign="center" '
                f'text="{_esc(text)}"/>'
            )
            xml.append(
                f'<label posn="-0.4 {posy + 0.1}" sizen="6.5 2" halign="left" valign="center" '
                f'text="{_esc(value.nickname)}"/>'
            )
    else:
        for idx, (place, value) in enumerate(entries):
            text = f'$z{place}. {_format_cp_time(value.time)}'
            posy = idx * -2 + 0.1
            xml.append(
                f'<label posn="-6.2 {posy}" sizen="6.5 2" halign="left" valign="center" '
                f'text="{_esc(text)}"/>'
            )
            xml.append(
                f'<label posn="-0.4 {posy}" sizen="6.5 2" halign="left" valign="center" '
                f'text="{_esc(value.nickname)}"/>'
            )

    xml.append('</frame></manialink>')
    return ''.join(xml)


async def _broadcast_widget(aseco: 'Aseco'):
    xml = _build_widget_xml()
    for player in aseco.server.players.all():
        if player.login in _hidden_for:
            continue
        await _send_widget_xml(aseco, player.login, xml)


async def _bestcps_sync(aseco: 'Aseco', _param=None):
    _load_config(aseco)
    await _send_toggle(aseco)
    if _tab_cp_time:
        await _broadcast_widget(aseco)


async def _bestcps_player_connect(aseco: 'Aseco', player: 'Player'):
    await _send_toggle(aseco, player.login)
    if player.login not in _hidden_for and _tab_cp_time:
        await _send_widget_xml(aseco, player.login, _build_widget_xml())


async def _bestcps_new_challenge(aseco: 'Aseco', challenge):
    _load_config(aseco)
    _tab_cp_time.clear()
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPage',
        f'<manialink id="{WIDGET_ID}"></manialink>',
        1,
        False,
    )
    await _send_toggle(aseco)


async def _bestcps_player_finish(aseco: 'Aseco', record):
    # Preserved only as a compatibility hook from the original plugin.
    return


async def _bestcps_checkpoint(aseco: 'Aseco', param: list):
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


async def _bestcps_refresh(aseco: 'Aseco', _record):
    if _tab_cp_time:
        await _broadcast_widget(aseco)


async def _bestcps_click(aseco: 'Aseco', answer: list):
    if len(answer) < 3:
        return
    try:
        action = int(answer[2])
    except Exception:
        return

    if action != ACTION_TOGGLE:
        return

    player = aseco.server.players.get_player(answer[1])
    if not player:
        return

    aseco.console('player {1} clicked command "/bestcps"', player.login)
    await chat_bestcps(aseco, {'author': player})


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
