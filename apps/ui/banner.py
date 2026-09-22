from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, as_float, as_int, as_str, bind_app_settings
from pyxaseco.helpers import strip_colors, strip_sizes
from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

ML_ID = 5834290

BANNER_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='ui',
    section_name='ui',
    description='Server banner HUD settings',
    settings=(
        AppSetting('banner/enabled', True, as_bool, 'Enable the server banner widget.', 'banner'),
        AppSetting('banner/pos_x', -64.4, as_float, 'Banner X position.', 'banner'),
        AppSetting('banner/pos_y', 22.7, as_float, 'Banner Y position.', 'banner'),
        AppSetting('banner/width', 21.0, as_float, 'Maximum banner width.', 'banner'),
        AppSetting('banner/min_width', 7.0, as_float, 'Minimum banner width.', 'banner'),
        AppSetting('banner/char_width', 0.82, as_float, 'Estimated per-character width.', 'banner'),
        AppSetting('banner/height', 2.7, as_float, 'Banner height.', 'banner'),
        AppSetting('banner/text_size', 1, as_int, 'Banner text size.', 'banner'),
        AppSetting('banner/text_x', 0.6, as_float, 'Banner text X offset.', 'banner'),
        AppSetting('banner/text_y', -0.35, as_float, 'Banner text Y offset.', 'banner'),
        AppSetting('banner/background_style', 'Bgs1InRace', as_str, 'Banner background style.', 'banner'),
        AppSetting('banner/background_substyle', 'NavButton', as_str, 'Banner background substyle.', 'banner'),
    ),
)

_enabled = True
_pos_x = -64.4
_pos_y = 22.7
_max_width = 21.0
_min_width = 7.0
_char_width = 0.82
_height = 2.7
_scale = 1.0
_text_size = 1
_text_x = 0.6
_text_y = -0.35
_bg_style = 'Bgs1InRace'
_bg_substyle = 'NavButton'

FALLBACK_BANNER_TEXT = "Could not getch server name."


def register(aseco: "Aseco"):
    _apply_app_defaults(aseco)
    aseco.register_event("onStartup", _banner_on_startup)
    aseco.register_event("onEndRace", _banner_on_end_race)
    aseco.register_event("onNewChallenge", _banner_on_new_challenge)
    aseco.register_event("onPlayerConnect", _banner_on_player_connect)


def _apply_app_defaults(aseco: "Aseco") -> None:
    global _enabled, _pos_x, _pos_y, _max_width, _min_width, _char_width
    global _height, _text_size, _text_x, _text_y, _bg_style, _bg_substyle

    bound = bind_app_settings(BANNER_SETTINGS_SCHEMA, getattr(aseco, '_base_dir', None))
    _enabled = bool(bound.values['banner/enabled'])
    _pos_x = float(bound.values['banner/pos_x'])
    _pos_y = float(bound.values['banner/pos_y'])
    _max_width = float(bound.values['banner/width'])
    _min_width = float(bound.values['banner/min_width'])
    _char_width = float(bound.values['banner/char_width'])
    _height = float(bound.values['banner/height'])
    _text_size = int(bound.values['banner/text_size'])
    _text_x = float(bound.values['banner/text_x'])
    _text_y = float(bound.values['banner/text_y'])
    _bg_style = str(bound.values['banner/background_style'] or 'Bgs1InRace')
    _bg_substyle = str(bound.values['banner/background_substyle'] or 'NavButton')

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
    width = min(_max_width, max(_min_width, 1.2 + (visible_len * _char_width)))
    banner_text = html.escape(banner_text, quote=True)
    return "".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<manialink id="{ML_ID}">',
            f'<frame posn="{_pos_x} {_pos_y} 0">',
            f'<format textsize="{_text_size}"/>',
            (
                f'<quad posn="0 0 0" sizen="{width:.2f} {_height}" scale="{_scale}" '
                f'halign="left" valign="top" style="{_bg_style}" substyle="{_bg_substyle}" />'
            ),
            (
                f'<label posn="{_text_x} {_text_y} 0.1" sizen="{max(1.0, width - 1.2):.2f} {_height}" '
                f'scale="{_scale}" halign="left" valign="top" text="{banner_text}"/>'
            ),
            "</frame>",
            "</manialink>",
        ]
    )


async def _show_banner(aseco: "Aseco", login: str | None = None):
    if not _enabled:
        await _hide_banner(aseco, login)
        return
    xml = _build_xml(await _get_banner_text(aseco))
    if login:
        await aseco.client.query_ignore_result(
            "SendDisplayManialinkPageToLogin", login, xml, 0, False
        )
    else:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def _hide_banner(aseco: "Aseco", login: str | None = None):
    xml = f'<manialink id="{ML_ID}"></manialink>'
    if login:
        await aseco.client.query_ignore_result(
            "SendDisplayManialinkPageToLogin", login, xml, 0, False
        )
    else:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def _banner_on_startup(aseco: "Aseco", _params):
    _apply_app_defaults(aseco)
    await _show_banner(aseco)


async def _banner_on_end_race(aseco: "Aseco", _race):
    await _hide_banner(aseco)


async def _banner_on_new_challenge(aseco: "Aseco", _challenge):
    _apply_app_defaults(aseco)
    await _show_banner(aseco)


async def _banner_on_player_connect(aseco: "Aseco", player: "Player"):
    _apply_app_defaults(aseco)
    if not _enabled:
        await _hide_banner(aseco, player.login)
        return
    if getattr(getattr(aseco.server, "gameinfo", None), "mode", -1) == getattr(Gameinfo, "SCOR", 7):
        await _hide_banner(aseco, player.login)
        return
    await _show_banner(aseco, player.login)


async def reload_banner_runtime(aseco: "Aseco") -> None:
    _apply_app_defaults(aseco)
    await _hide_banner(aseco)
    if not _enabled:
        return
    if getattr(getattr(aseco.server, "gameinfo", None), "state", None) == Gameinfo.SCOR:
        return
    await _show_banner(aseco)
