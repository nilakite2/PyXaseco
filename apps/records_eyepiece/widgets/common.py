from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


async def _send(aseco: 'Aseco', login: str, xml: str):
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin',
        login,
        aseco.format_colors(xml),
        0,
        False,
    )


async def _hide(aseco: 'Aseco', login: str, ml_id: int):
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin',
        login,
        f'<manialink id="{ml_id}"></manialink>',
        0,
        False,
    )


async def _send_chat(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg),
        login,
    )