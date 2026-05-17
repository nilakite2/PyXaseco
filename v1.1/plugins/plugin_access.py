"""
plugin_access.py — Port of plugins/plugin.access.php

Controls player access by TMF zone using Apache mod_access
style allow/deny rules loaded from access.xml.

Config file: access.xml (optional — if absent, all players are allowed)
  <access>
    <order>Allow,Deny</order>   <!-- or Deny,Allow -->
    <allow><from>World|Europe</from><from>World|Americas</from></allow>
    <deny><from>all</from></deny>
    <messages>
      <denied>{1} from {3} is not allowed on this server.</denied>
      <dialog>Your {2} ({3}) is not permitted on this server.</dialog>
      <reload>{#server}> Access control reloaded.</reload>
      <xmlerr>{#server}> {#error}Error loading access.xml!</xmlerr>
      <missing>{#server}> {#error}Missing parameter for /admin access.</missing>
    </messages>
  </access>
"""

from __future__ import annotations
import pathlib
import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, strip_colors, display_manialink, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# Access control state
_access: dict = {}   # loaded config; empty = disabled


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup',        _access_init)
    aseco.register_event('onPlayerConnect2', _access_playerconnect)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

async def _access_init(aseco: 'Aseco', _data):
    global _access
    base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
    cfg  = base / 'access.xml'
    if not cfg.exists():
        aseco.console('[Access] access.xml not found — access control disabled.')
        return
    _access = _load_config(aseco, cfg)


def _load_config(aseco: 'Aseco', path: pathlib.Path) -> dict:
    """Parse access.xml and return config dict, or {} on error."""
    try:
        from pyxaseco.core.config import parse_xml_file
        raw = parse_xml_file(path)
        if not raw:
            logger.warning('[Access] Could not parse %s', path)
            return {}

        root = raw.get('ACCESS', {})

        def g(key, default=''):
            v = root.get(key.upper(), [default])
            return v[0] if v else default

        order_str = g('ORDER', 'deny,allow').replace(' ', '').lower()
        order = (order_str == 'allow,deny')  # True=Allow,Deny  False=Deny,Allow

        allow_block = root.get('ALLOW', [{}])[0] if root.get('ALLOW') else {}
        deny_block  = root.get('DENY',  [{}])[0] if root.get('DENY')  else {}

        allow_froms = allow_block.get('FROM', [])
        deny_froms  = deny_block.get('FROM',  [])

        allow_all = ('all' in allow_froms)
        deny_all  = ('all' in deny_froms)
        allow_list = sorted([f for f in allow_froms if f and f != 'all'])
        deny_list  = sorted([f for f in deny_froms  if f and f != 'all'])

        msgs_block = root.get('MESSAGES', [{}])[0] if root.get('MESSAGES') else {}
        def gm(key, default):
            v = msgs_block.get(key.upper(), [default])
            return v[0] if v else default

        messages = {
            'denied':  gm('DENIED',  '{1} from {3} is not permitted on this server.'),
            'dialog':  gm('DIALOG',  'Your {2} ({3}) is not allowed on this server.'),
            'reload':  gm('RELOAD',  '{#server}> Access control reloaded.'),
            'xmlerr':  gm('XMLERR',  '{#server}> {#error}Error reloading access.xml!'),
            'missing': gm('MISSING', '{#server}> {#error}Missing parameter for /admin access.'),
        }

        aseco.console('[Access] Loaded access.xml: order={1}, allow={2}, deny={3}',
                      'Allow,Deny' if order else 'Deny,Allow',
                      'all' if allow_all else str(allow_list),
                      'all' if deny_all  else str(deny_list))
        return {
            'order':    order,
            'allowall': allow_all,
            'allow':    allow_list,
            'denyall':  deny_all,
            'deny':     deny_list,
            'messages': messages,
        }
    except Exception as e:
        logger.warning('[Access] Config error: %s', e)
        return {}


def _in_zones(value: str, zones: list) -> bool:
    """True if value starts with any entry in zones list."""
    return any(value.startswith(z) for z in zones)


def _is_allowed(access_value: str) -> bool:
    """Apply Allow/Deny logic and return True if player is allowed."""
    if not _access:
        return True  # no config = allow all
    if not access_value:
        # Empty zone/nation: default depends on order
        return not _access['order']  # Allow,Deny → default denied; Deny,Allow → default allowed

    order    = _access['order']
    allow_all = _access['allowall']
    deny_all  = _access['denyall']
    allows   = _access['allow']
    denies   = _access['deny']

    in_allow = allow_all or _in_zones(access_value, allows)
    in_deny  = deny_all  or _in_zones(access_value, denies)

    if order:  # Allow,Deny: allowed unless also denied
        return in_allow and not in_deny
    else:       # Deny,Allow: denied unless also allowed
        return not in_deny or in_allow


# ---------------------------------------------------------------------------
# Event: onPlayerConnect
# ---------------------------------------------------------------------------

async def _access_playerconnect(aseco: 'Aseco', player):
    if not _access:
        return

    # Use zone for TMF
    access_value = getattr(player, 'zone', '') or getattr(player, 'nation', '')

    if _is_allowed(access_value):
        return

    # Log and kick
    aseco.console("[Access] Player '{1}' denied from \"{2}\" — kicking.",
                  player.login, access_value)

    msgs = _access.get('messages', {})
    msg = format_text(msgs.get('denied', ''),
                      strip_colors(player.nickname), 'zone', access_value)
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage', aseco.format_colors(msg))

    kick_msg = format_text(msgs.get('dialog', ''), 'zone', access_value)
    try:
        await aseco.client.query_ignore_result(
            'Kick', player.login, aseco.format_colors(kick_msg))
    except Exception:
        await aseco.client.query_ignore_result('Kick', player.login)


# ---------------------------------------------------------------------------
# /admin access sub-command (called from chat_admin.py)
# ---------------------------------------------------------------------------

async def admin_access(aseco: 'Aseco', command: dict):
    global _access
    player = command['author']
    login  = player.login
    param  = (command.get('params') or '').strip()
    msgs   = _access.get('messages', {}) if _access else {}

    async def reply(msg):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)

    if param == 'help':
        header = '{#black}/admin access$g handles player access control:'
        data = [
            ['...', '{#black}help',   'Displays this help information'],
            ['...', '{#black}list',   'Displays current access control settings'],
            ['...', '{#black}reload', 'Reloads updated settings from access.xml'],
        ]
        display_manialink(aseco, login, header,
                          ['Icons64x64_1', 'TrackInfo', -0.01],
                          data, [0.8, 0.05, 0.15, 0.6], 'OK')

    elif param == 'list':
        if not _access:
            await reply('{#server}> {#error}Access control is disabled (no access.xml).')
            return
        header = 'Current player access control settings:'
        info = [
            ['Order:', '{#black}' + ('Allow,Deny' if _access['order'] else 'Deny,Allow')],
            [],
            ['Allow:', '{#black}' + ('all' if _access['allowall'] else ', '.join(_access['allow']) or '(none)')],
            ['Deny:',  '{#black}' + ('all' if _access['denyall']  else ', '.join(_access['deny'])  or '(none)')],
        ]
        pages = [info[i:i+14] for i in range(0, max(len(info), 1), 14)]
        player.msgs = [[1, header, [1.0, 0.2, 0.8], ['Icons128x128_1', 'ManiaZones']]]
        player.msgs.extend(pages)
        display_manialink_multi(aseco, player)

    elif param == 'reload':
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        cfg  = base / 'access.xml'
        if cfg.exists():
            new = _load_config(aseco, cfg)
            if new:
                _access = new
                await reply(msgs.get('reload', '{#server}> Access control reloaded.'))
            else:
                await reply(msgs.get('xmlerr', '{#server}> {#error}Error reloading access.xml!'))
        else:
            await reply('{#server}> {#error}access.xml not found.')

    else:
        await reply(msgs.get('missing', '{#server}> {#error}Usage: /admin access help|list|reload'))
