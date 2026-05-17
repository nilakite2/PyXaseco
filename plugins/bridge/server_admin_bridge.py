"""
plugin_server_admin_bridge.py — Port of plugins/plugin.server_admin_bridge.php

Registers the dedicated server's own login as a MasterAdmin at startup.
This lets /admin commands sent via the server console be authorised.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: 'Aseco'):
    aseco.register_event('onSync', _sai_setup_server_login)


async def _sai_setup_server_login(aseco: 'Aseco', _data):
    login = getattr(aseco.server, 'serverlogin', '')
    if not login:
        return

    # Ensure server login is in the masteradmin list
    master_logins = aseco.settings.masteradmin_list.get('TMLOGIN', [])
    if login not in master_logins:
        master_logins.append(login)
        aseco.settings.masteradmin_list['TMLOGIN'] = master_logins

        ips = aseco.settings.masteradmin_list.get('IPADDRESS', [])
        ips.append('')  # keep arrays aligned; '' = any IP
        aseco.settings.masteradmin_list['IPADDRESS'] = ips

    aseco.console('[SAI] Server login "{1}" whitelisted as MasterAdmin.', login)


def sai_is_server_login(aseco: 'Aseco', login: str) -> bool:
    """Helper: true if login is the dedicated server's own account."""
    if not login:
        return False
    return login.lower() == getattr(aseco.server, 'serverlogin', '').lower()
