"""
plugin_uptodate.py — Port of plugins/plugin.uptodate.php

Checks PyXaseco version at startup and on MasterAdmin connect.
Provides /admin uptodate command (wired up by chat_admin).
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

PYXASECO_VERSION = '0.1.0'
# Set to '' to disable version checks
VERSION_URL = ''   # e.g. 'https://your-site.com/version.txt'


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',          start_uptodate)
    aseco.register_event('onPlayerConnect', connect_uptodate)
    aseco.add_chat_command('uptodate', 'Checks current version of PyXaseco', is_admin=True)
    aseco.register_event('onChat_uptodate', admin_uptodate)


async def _check_version(aseco: 'Aseco') -> str | None:
    """Fetch remote version and return formatted message, or None on error."""
    if not VERSION_URL:
        return None
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(VERSION_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                current = (await resp.text()).strip()
        if current and current != '-1':
            if current != PYXASECO_VERSION:
                return format_text(aseco.get_chat_message('UPTODATE_NEW'),
                                   current, VERSION_URL)
            else:
                return format_text(aseco.get_chat_message('UPTODATE_OK'), current)
    except Exception:
        pass
    return None


async def start_uptodate(aseco: 'Aseco', _param):
    """Check version on startup."""
    msg = await _check_version(aseco)
    if msg:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(msg))


async def connect_uptodate(aseco: 'Aseco', player: 'Player'):
    """Check version when a MasterAdmin connects."""
    if not aseco.is_master_admin(player):
        return
    msg = await _check_version(aseco)
    if msg:
        ok_pattern = format_text(aseco.get_chat_message('UPTODATE_OK'), '.*')
        if not re.match(ok_pattern, msg):
            msg = msg.replace('{#server}>> ', '{#server}> ')
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', aseco.format_colors(msg), player.login)


async def admin_uptodate(aseco: 'Aseco', command: dict):
    """Handle /admin uptodate."""
    login = command['author'].login
    msg = await _check_version(aseco)
    if msg:
        msg = msg.replace('{#server}>> ', '{#server}> ')
    else:
        msg = "{#server}> {#error}Version check disabled - Alpha testing."
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)
