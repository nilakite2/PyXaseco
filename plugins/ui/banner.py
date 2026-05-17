from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import strip_colors, strip_sizes

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

ML_ID = 5834290

# Matches the top-left HUD area used by CP Live closely enough to feel native.
POS_X = -64.4
POS_Y = 22.7
MAX_WIDTH = 21.0
MIN_WIDTH = 7.0
CHAR_WIDTH = 0.82
HEIGHT = 2.7
SCALE = 1.0
TEXT_SIZE = 1
TEXT_X = 0.6
TEXT_Y = -0.35

FALLBACK_BANNER_TEXT = "Could not getch server name."


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", _banner_on_startup)
    aseco.register_event("onNewChallenge", _banner_on_new_challenge)
    aseco.register_event("onPlayerConnect", _banner_on_player_connect)


async def _get_banner_text(aseco: "Aseco") -> str:
    try:
        server_name = await aseco.client.query("GetServerName")
        if isinstance(server_name, str) and server_name.strip():
            return server_name.strip()
    except Exception:
        logger.debug("[Banner] Failed to fetch server name", exc_info=True)
    return FALLBACK_BANNER_TEXT


def _build_xml(banner_text: str) -> str:
    visible_text = strip_sizes(strip_colors(banner_text, for_tm=False), for_tm=False).strip()
    visible_len = max(1, len(visible_text))
    width = min(MAX_WIDTH, max(MIN_WIDTH, 1.2 + (visible_len * CHAR_WIDTH)))
    banner_text = html.escape(banner_text, quote=True)
    return "".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<manialink id="{ML_ID}">',
            f'<frame posn="{POS_X} {POS_Y} 0">',
            f'<format textsize="{TEXT_SIZE}"/>',
            (
                f'<quad posn="0 0 0" sizen="{width:.2f} {HEIGHT}" scale="{SCALE}" '
                'halign="left" valign="top" style="Bgs1InRace" substyle="NavButton" />'
            ),
            (
                f'<label posn="{TEXT_X} {TEXT_Y} 0.1" sizen="{max(1.0, width - 1.2):.2f} {HEIGHT}" '
                f'scale="{SCALE}" halign="left" valign="top" text="{banner_text}"/>'
            ),
            "</frame>",
            "</manialink>",
        ]
    )


async def _show_banner(aseco: "Aseco", login: str | None = None):
    xml = _build_xml(await _get_banner_text(aseco))
    if login:
        await aseco.client.query_ignore_result(
            "SendDisplayManialinkPageToLogin", login, xml, 0, False
        )
    else:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def _banner_on_startup(aseco: "Aseco", _params):
    await _show_banner(aseco)


async def _banner_on_new_challenge(aseco: "Aseco", _challenge):
    await _show_banner(aseco)


async def _banner_on_player_connect(aseco: "Aseco", player: "Player"):
    await _show_banner(aseco, player.login)
