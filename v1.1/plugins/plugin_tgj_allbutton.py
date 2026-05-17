"""
plugin_tgj_allbutton.py — Python base port of tgj.allbutton.php

Displays a small race HUD with quick chat buttons and a temporary secondary
"x or nub" popup.
"""

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

MAIN_ML_ID = 10
SUB_ML_ID = 11

ACTION_HELLO = 40001
ACTION_HIN = 40002
ACTION_BYE = 40003
ACTION_RAGEQUIT = 40004
ACTION_RIP = 40005
ACTION_OPEN_SUB = 40024

SUB_ACTIONS = {
    50001: '.0x or nub',
    50002: '.1x or nub',
    50003: '.2x or nub',
    50004: '.3x or nub',
    50005: '.4x or nub',
    50006: '.5x or nub',
    50007: '.6x or nub',
    50008: '.7x or nub',
    50009: '.8x or nub',
    50010: '.9x or nub',
}

_MAIN_MESSAGES = {
    ACTION_HELLO: 'Hello everyone!',
    ACTION_BYE: 'Cya guys :)',
    ACTION_RAGEQUIT: '\nRAGEQUIT!!\nRAGEQUIT!!\nRAGEQUIT!!\nRAGEQUIT!!\nRAGEQUIT!!\nRAGEQUIT!!',
}

_STYLE_CODES = set('ozsiuntmglw')
_last_nick: str = ''


def register(aseco: 'Aseco'):
    aseco.register_event('onPlayerConnect', _allbutton_player_connect)
    aseco.register_event('onNewChallenge', _send_main_buttons)
    aseco.register_event('onEndRace', _send_main_buttons)
    aseco.register_event('onPlayerManialinkPageAnswer', _allbutton_click)


async def _allbutton_player_connect(aseco: 'Aseco', player: 'Player'):
    global _last_nick
    _last_nick = getattr(player, 'nickname', '') or getattr(player, 'login', '')
    await _send_main_buttons(aseco)


def _visible_color_runs(nickname: str) -> list[tuple[str, int]]:
    text = str(nickname or '').replace('$$', '\x00')
    text = re.sub(r'\$[LlHh]\[[^\]]*\]', '', text)

    runs: list[tuple[str, int]] = []
    current = '$fff'
    current_len = 0
    i = 0

    while i < len(text):
        ch = text[i]
        if ch == '$':
            token3 = text[i + 1:i + 4]
            token1 = text[i + 1:i + 2]
            if len(token3) == 3 and re.fullmatch(r'[0-9a-fA-F]{3}', token3):
                if current_len > 0:
                    runs.append((current, current_len))
                    current_len = 0
                current = '$' + token3.lower()
                i += 4
                continue
            if token1 and token1.lower() in _STYLE_CODES:
                i += 2
                continue
        if ch != '\x00' and not ch.isspace():
            current_len += 1
        i += 1

    if current_len > 0:
        runs.append((current, current_len))
    if not runs:
        runs.append(('$fff', max(1, len(re.sub(r'\s+', '', text.replace('\x00', '$'))))))
    return runs


def _colorize_message_from_nick(nickname: str, message: str) -> str:
    message = str(message or '')
    if not message:
        return message

    runs = _visible_color_runs(nickname)
    total_weight = sum(weight for _, weight in runs) or 1
    total_chars = len(message)
    pieces: list[str] = []
    start = 0

    for idx, (color, weight) in enumerate(runs):
        if idx == len(runs) - 1:
            end = total_chars
        else:
            end = start + max(1, math.floor((weight * total_chars) / total_weight))
            end = min(end, total_chars)
        if end <= start:
            continue
        pieces.append(f'{color}{message[start:end]}')
        start = end

    if start < total_chars:
        color = runs[-1][0] if runs else '$fff'
        pieces.append(f'{color}{message[start:]}')

    return ''.join(pieces) if pieces else message


async def _send_colored_chat(aseco: 'Aseco', player: 'Player', message: str):
    nick = getattr(player, 'nickname', '') or getattr(player, 'login', '')
    body = _colorize_message_from_nick(nick, message)
    chat = f'$z$s[{nick}$z] $w$s$i{body}'
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage',
        aseco.format_colors(chat),
    )


def _main_xml() -> str:
    return (
        f"<manialink id='{MAIN_ML_ID}'>"
        "<frame posn='-61 -45.1 0'>"
        "<quad posn='-0.8 -0.5 0' sizen='50 2.5' style='Bgs1InRace' substyle='NavButton'/>"
        f"<label posn='0 -0.8 0' action='{ACTION_HELLO}' sizen='2 1' style='TextCardSmallScores2Rank' text='$s$08FHIA'/>"
        f"<label posn='2 -0.8 0' action='{ACTION_HIN}' sizen='2 1' style='TextCardSmallScores2Rank' text='$s$999HI-N'/>"
        f"<label posn='4 -0.8 0' action='{ACTION_BYE}' sizen='2 1' style='TextCardSmallScores2Rank' text='$s$08FCU'/>"
        f"<label posn='6 -0.8 0' action='{ACTION_RAGEQUIT}' sizen='2 1' style='TextCardSmallScores2Rank' text='$s$999RQ'/>"
        f"<label posn='8 -0.8 0' action='{ACTION_RIP}' sizen='2 1' style='TextCardSmallScores2Rank' text='$s$08FRIP'/>"
        f"<label posn='47 -0.8 0' action='{ACTION_OPEN_SUB}' sizen='2 1' style='TextCardSmallScores2Rank' text='$s$999+'/>"
        "</frame>"
        "</manialink>"
    )


def _submenu_xml() -> str:
    labels = []
    for idx, action in enumerate(sorted(SUB_ACTIONS)):
        labels.append(
            f"<label posn='{idx * 2} -0.8 0' action='{action}' sizen='2 1' "
            f"style='TextCardSmallScores2Rank' text='$s{'$08F' if idx % 2 == 0 else '$999'}{idx}X'/>"
        )
    return (
        f"<manialink id='{SUB_ML_ID}'>"
        "<frame posn='-39 -28.2 0'>"
        "<quad posn='-0.8 -0.5 0' sizen='21 2.5' style='Bgs1InRace' substyle='NavButton'/>"
        + ''.join(labels) +
        "</frame>"
        "</manialink>"
    )


async def _send_main_buttons(aseco: 'Aseco', _param=None):
    xml = _main_xml()
    for player in aseco.server.players.all():
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPageToLogin',
            player.login,
            xml,
            0,
            False,
        )


async def _send_submenu(aseco: 'Aseco', login: str):
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin',
        login,
        _submenu_xml(),
        15000,
        True,
    )


async def _allbutton_click(aseco: 'Aseco', answer: list):
    global _last_nick

    if len(answer) < 3:
        return
    try:
        action = int(answer[2])
    except Exception:
        return

    login = answer[1]
    player = aseco.server.players.get_player(login)
    if not player:
        return

    if action in _MAIN_MESSAGES:
        await _send_colored_chat(aseco, player, _MAIN_MESSAGES[action])
        if action == ACTION_RAGEQUIT:
            try:
                await aseco.client.query_ignore_result('Kick', player.login)
            except Exception as e:
                logger.debug('[AllButton] Kick failed for %s: %s', player.login, e)
        return

    if action == ACTION_HIN:
        target = _last_nick or '?'
        msg = (
            f'$z$s[{player.nickname}$z] {{#interact}}$s$i$w'
            f'$f00D$f90a$ff0y$0f0u$0cfu$00cu$63fm $00ci$0cft$0f0s $ff0d$f90a$f00t $z$s{target}'
        )
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage',
            aseco.format_colors(msg),
        )
        return

    if action == ACTION_RIP:
        target = _last_nick or '?'
        msg = f'$z$s[{player.nickname}$z] {{#interact}}$s$i$w$000RIP $z$s{target}'
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage',
            aseco.format_colors(msg),
        )
        return

    if action == ACTION_OPEN_SUB:
        await _send_submenu(aseco, player.login)
        return

    if action in SUB_ACTIONS:
        await _send_colored_chat(aseco, player, SUB_ACTIONS[action])
