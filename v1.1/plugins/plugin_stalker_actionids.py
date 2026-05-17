"""
plugin_stalker_actionids.py - port of stalker.actionIDs.php

Routes a few legacy Manialink action ids to chat commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


_ACTION_COMMANDS: dict[int, str] = {
    27008505: "/st chatall",
    270085052: "/jfreu players live",
    270085053: "/music list",
    270085054: "/list",
}


def register(aseco: "Aseco"):
    aseco.register_event("onPlayerManialinkPageAnswer", _event_stalker_actionids)


async def _event_stalker_actionids(aseco: "Aseco", command: list):
    if len(command) < 3:
        return

    login = str(command[1] or "").strip()
    if not login:
        return

    try:
        action = int(command[2])
    except Exception:
        return

    chat_command = _ACTION_COMMANDS.get(action)
    if not chat_command:
        return

    await aseco.dispatch_chat_command(login, chat_command)
