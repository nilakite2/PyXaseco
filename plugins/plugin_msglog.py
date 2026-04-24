"""
plugin_msglog.py — Port of plugins/plugin.msglog.php

Keeps log of recent system messages and displays them via:
  - /msglog command
  - small clickable msglog button on connect
  - send_window_message() API used by other plugins

Action ID 7223 matches XAseco.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

ML_WINDOW_ID = 7
ML_BUTTON_ID = 8
ML_ACTION_ID = 7223

MSG_BUF_LEN = 21
MSG_LINE_LEN = 800
MSG_WIN_LEN = 5

_msgbuf: list[str] = []


def register(aseco: "Aseco"):
    aseco.add_chat_command("msglog", "Displays log of recent system messages")
    aseco.register_event("onPlayerManialinkPageAnswer", _event_msglog)
    aseco.register_event("onPlayerConnect", _msglog_button)
    aseco.register_event("onChat_msglog", chat_msglog)


def _server_is_tmf(aseco: "Aseco") -> bool:
    return getattr(aseco.server, "get_game", lambda: "")() == "TMF"


def get_msgbuf() -> list[str]:
    return list(_msgbuf)


def _active_msgbuf() -> list[str]:
    """
    Prefer the shared muting/msglog history when available, because several
    plugins write system-window messages through plugin_muting.send_window_message().
    """
    try:
        from pyxaseco.plugins.plugin_muting import get_msgbuf as muting_get_msgbuf
        buf = muting_get_msgbuf()
        if buf:
            return list(buf)
    except Exception:
        pass
    return list(_msgbuf)


async def send_window_message(aseco: "Aseco", message: str, scoreboard: bool):
    """
    Append message line(s) to local history and show the recent message window.
    Mirrors XAseco's send_window_message().
    """
    global _msgbuf

    for item in str(message).split("\n"):
        if item is None:
            continue
        item = str(item)
        if not item:
            continue

        # wordwrap('$z$s' . $item, MSG_LINE_LEN, LF . '$z$s$n')
        prefixed = "$z$s" + item
        while len(prefixed) > MSG_LINE_LEN:
            line = prefixed[:MSG_LINE_LEN]
            if len(_msgbuf) >= MSG_BUF_LEN:
                _msgbuf.pop(0)
            _msgbuf.append(aseco.format_colors(line))
            prefixed = "$z$s$n" + prefixed[MSG_LINE_LEN:]
        if len(_msgbuf) >= MSG_BUF_LEN:
            _msgbuf.pop(0)
        _msgbuf.append(aseco.format_colors(prefixed))

    if scoreboard:
        try:
            timeout_info = await aseco.client.query("GetChatTime") or {}
            timeout = int(timeout_info.get("CurrentValue", 0)) + 5000
        except Exception:
            timeout = 10000
    else:
        timeout = int(aseco.settings.window_timeout) * 1000

    lines = _msgbuf[-MSG_WIN_LEN:]
    await _display_msgwindow(aseco, lines, timeout)


async def _display_msgwindow(aseco: "Aseco", msgs: list[str], timeout: int):
    if not msgs:
        return

    cnt = len(msgs)
    xml = f'<manialink id="{ML_WINDOW_ID}"><frame posn="-49 43.5 0">'           f'<quad sizen="93 {1.5 + cnt * 2.5}" style="Bgs1" substyle="NavButton"/>'
    pos = -1.0
    for msg in msgs:
        safe = html.escape(str(msg), quote=True)
        xml += (
            f'<label posn="1 {pos} 1" sizen="91 1" style="TextRaceChat" '
            f'text="{safe}"/>'
        )
        pos -= 2.5
    xml += "</frame></manialink>"

    try:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, timeout, False)
    except Exception:
        logger.debug("[MsgLog] failed to display msg window", exc_info=True)


async def _msglog_button(aseco: "Aseco", player):
    xml = (
        f'<manialink id="{ML_BUTTON_ID}"><frame posn="-63.9 -33.5 0">'
        f'<quad sizen="1.65 1.65" style="Icons64x64_1" substyle="ArrowUp" action="{ML_ACTION_ID}"/>'
        f'</frame></manialink>'
    )
    try:
        await aseco.client.query_ignore_result(
            "SendDisplayManialinkPageToLogin", player.login, xml, 0, False
        )
    except Exception:
        logger.debug("[MsgLog] failed to display button", exc_info=True)


async def _event_msglog(aseco: "Aseco", answer: list):
    if len(answer) < 3:
        return

    try:
        action = int(answer[2])
    except Exception:
        return

    if action != ML_ACTION_ID:
        return

    player = aseco.server.players.get_player(answer[1])
    if not player:
        return

    aseco.console('player {1} clicked command "/msglog "', player.login)
    await chat_msglog(aseco, {"author": player, "params": ""})


async def chat_msglog(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login

    if not _server_is_tmf(aseco):
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors(aseco.get_chat_message("FOREVER_ONLY")),
            login,
        )
        return

    msgbuf = _active_msgbuf()
    if msgbuf:
        header = "Recent system message history:"
        msgs = [[line] for line in msgbuf]
        display_manialink(
            aseco,
            login,
            header,
            ["Icons64x64_1", "NewMessage"],
            msgs,
            [1.53],
            "OK",
        )
    else:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors("{#server}> {#error}No system message history found!"),
            login,
        )
