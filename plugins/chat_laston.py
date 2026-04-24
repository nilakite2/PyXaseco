"""
chat_laston.py — Port of plugins/chat.laston.php

/laston [login] — Shows when a player was last online.
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.add_chat_command('laston', 'Shows when a player was last online')
    aseco.register_event('onChat_laston', chat_laston)


async def chat_laston(aseco: 'Aseco', command: dict):
    player = command['author']
    login  = player.login

# Determine target from login or numeric player index.
    # We resolve: if no param, use self; if param given, resolve against online players
    # first (supports numeric IDs via player list), then fall back to DB lookup.
    param = command['params'].strip()
    if not param:
        target_login = login
        target_nick  = player.nickname
    else:
# Try to resolve as an online player, including numeric indices.
        resolved = aseco.server.players.get_player(param)
        if resolved:
            target_login = resolved.login
            target_nick  = resolved.nickname
        else:
            # Treat as login string for DB lookup; nick resolved from DB below
            target_login = param
            target_nick  = None

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName, UpdatedAt FROM players WHERE Login=%s',
                    (target_login,))
                row = await cur.fetchone()
    except Exception:
        return

    if not row:
        msg = aseco.format_colors(
            f'{{#server}}> {{#error}}Player {target_login} not found in database!')
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', msg, login)
        return

    db_nick, updated_at = row
    # Use DB nickname when target was resolved from DB (not online)
    if target_nick is None:
        target_nick = db_nick

# Strip trailing seconds from the timestamp for display.
    ts = str(updated_at)
    ts = re.sub(r':\d\d$', '', ts)

# Compose the final "last online" message.
    msg = (f'{{#server}}> Player {{#highlite}}{target_nick}'
           f'$z$s{{#server}} was last online on: {{#highlite}}{ts}')
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
