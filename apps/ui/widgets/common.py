from __future__ import annotations

import re

from pyxaseco.core.widget_delivery import deliver_ui

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


async def _send(aseco: 'Aseco', login: str, xml: str):
    await deliver_ui(aseco, 
        'SendDisplayManialinkPageToLogin',
        login,
        aseco.format_colors(xml),
        0,
        False,
    )
    if re.search(r'<manialink\b[^>]*\bid=["\']9180[01]["\']', xml):
        for recipient in login.split(','):
            getattr(aseco, '_challenge_overviews', {}).pop(recipient, None)


async def _hide(aseco: 'Aseco', login: str, ml_id: int):
    await deliver_ui(aseco, 
        'SendDisplayManialinkPageToLogin',
        login,
        f'<manialink id="{ml_id}"></manialink>',
        0,
        False,
    )
    from ..config import _state
    digest = {91812: 'player_local_digest', 91811: 'player_dedi_digest',
              91813: 'player_live_digest'}.get(ml_id)
    if digest:
        getattr(_state, digest).pop(login, None)
    if ml_id in (91800, 91801):
        getattr(aseco, '_challenge_overviews', {}).pop(login, None)


async def _send_chat(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(msg),
        login,
    )
