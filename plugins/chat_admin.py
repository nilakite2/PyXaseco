"""
chat_admin.py — Port of plugins/chat.admin.php

Full admin command system: server settings, map control, player moderation,
jukebox admin, access control, track management and more.

Commands are all under /admin <subcommand>.
Tier: MasterAdmin > Admin > Operator (with per-command ability checks).
"""

from __future__ import annotations
import asyncio
import logging
import pathlib
import urllib.request
import urllib.error
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, strip_colors, display_manialink, display_manialink_multi

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

GAME_MODES = {
    'ta': 1, 'rounds': 0, 'round': 0, 'team': 2,
    'laps': 3, 'stunts': 4, 'cup': 5,
}

_LEGACY_ADMINOPS_TITLES = {
    'masteradmin': 'MasterAdmin',
    'admin': 'Admin',
    'operator': 'Operator',
}
_LEGACY_ADMIN_ABILITIES: dict[str, bool] = {}
_LEGACY_OPERATOR_ABILITIES: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# Module-level runtime globals
# ---------------------------------------------------------------------------

PM_BUFFER: list[str] = []
PM_BUFFER_LEN = 30
PM_LINE_LEN = 40

AUTO_SCOREPANEL = True
ROUNDS_FINISHPANEL = True

# Reserved ManiaLink action id ranges for admin panels
ML_WARN_BASE = 2200
ML_IGNORE_BASE = 2400
ML_UNIGNORE_BASE = 2600
ML_KICK_BASE = 2800
ML_BAN_BASE = 3000
ML_UNBAN_BASE = 3200
ML_BLACK_BASE = 3400
ML_UNBLACK_BASE = 3600
ML_ADDGUEST_BASE = 3800
ML_REMOVEGUEST_BASE = 4000
ML_FORCESPEC_BASE = 4200
ML_LIST_UNIGNORE_BASE = 4400
ML_LIST_UNBAN_BASE = 4600
ML_LIST_UNBLACK_BASE = 4800
ML_LIST_REMOVEGUEST_BASE = 5000
ML_UNBANIP_NEG_BASE = -7900

def register(aseco: 'Aseco'):
    aseco.register_event('onPlayerManialinkPageAnswer', _event_admin)
    aseco.register_event('onStartup', _admin_startup)
    
    aseco.register_event('onPlayerConnect', _admin_player_connect)
    
    aseco.add_chat_command('admin', 'Provides admin commands (see: /admin help)')
    aseco.add_chat_command('ad', 'Provides admin commands (see: /ad help)')
    aseco.add_chat_command('listmasters', 'Displays current masteradmin list')
    aseco.add_chat_command('listadmins', 'Displays current admin list')
    aseco.add_chat_command('listops', 'Displays current operator list')
    aseco.register_event('onChat_admin', chat_admin)
    aseco.register_event('onChat_ad', chat_admin)
    aseco.register_event('onChat_listmasters', chat_listmasters)
    aseco.register_event('onChat_listadmins', chat_listadmins)
    aseco.register_event('onChat_listops', chat_listops)

    admin_cmds = [
        # --- HELP ---
        ('help',          'Shows all available /admin commands', True),
        ('helpall',       'Displays help for available /admin commands', True),
    
        # --- SERVER SETTINGS ---
        ('setservername', 'Changes the name of the server', True),
        ('setcomment',    'Changes the server comment', True),
        ('setpwd',        'Changes the player password', True),
        ('setspecpwd',    'Changes the spectator password', True),
        ('setrefpwd',     'Changes the referee password', True),
        ('setmaxplayers', 'Sets a new maximum of players', True),
        ('setmaxspecs',   'Sets a new maximum of spectators', True),
        ('setgamemode',   'Sets next mode {ta,rounds,team,laps,stunts,cup}', True),
        ('setrefmode',    'Sets referee mode {0=top3,1=all}', True),
        ('acdl',          'Sets AllowChallengeDownload {ON/OFF}', True),
        ('autotime',      'Sets Auto TimeLimit {ON/OFF}', True),
        ('disablerespawn','Disables respawn at CPs {ON/OFF}', True),
        ('forceshowopp',  'Forces to show opponents {##/ALL/OFF}', True),
        ('scorepanel',    'Shows automatic scorepanel {ON/OFF}', True),
        ('roundsfinish',  'Shows rounds panel upon first finish {ON/OFF}', True),
        ('uptodate',      'Checks whether XAseco is up to date', True),
    
        # --- MAP CONTROL ---
        ('next',          'Forces server to load next track', True),
        ('nextmap',       'Forces server to load next track', True),
        ('skip',          'Forces server to skip track', True),
        ('skipmap',       'Forces server to load next track', True),
        ('previous',      'Forces server to load previous track', True),
        ('prev',          'Forces server to load previous track', True),
        ('nextenv',       'Loads next track in same environment', True),
        ('restart',       'Restarts currently running track', True),
        ('restartmap',    'Restarts currently running track', True),
        ('res',           'Restarts currently running track', True),
        ('replay',        'Replays current track (via jukebox)', True),
        ('replaymap',     'Replays current track (via jukebox)', True),
        ('endround',      'Forces end of current round', True),
        ('er',            'Forces end of current round', True),
    
        # --- Jukebox ---
        ('dropjukebox',   'Drops a track from the jukebox', True),
        ('djb',           'Drops a track from the jukebox', True),
        ('clearjukebox',  'Clears the entire jukebox', True),
        ('cjb',           'Clears the entire jukebox', True),
    
        # --- TRACK MANAGEMENT ---
        ('add',           'Adds track from TMX: /admin add <id> [tmnf|tmu|tmo|tms|tmn]', True),
        ('addlocal',      'Adds a local track (<filename>)', True),
        ('remove',        'Removes a track from rotation', True),
        ('erase',         'Removes a track from rotation and deletes file', True),
        ('removethis',    'Removes this track from rotation', True),
        ('rt',            'Removes this track from rotation', True),
        ('erasethis',     'Removes this track from rotation and deletes file', True),
        ('addthis',       'Adds current /add-ed track permanently', True),
        ('shuffle',       'Randomizes current track list', True),
        ('shufflemaps',   'Randomizes current track list', True),
        ('listdupes',     'Displays list of duplicate tracks', True),
        ('clearhist',     'Clears (part of) track history', True),
    
        # --- PLAYERS / MODERATION ---
        ('warn',          'Sends a kick/ban warning to a player', True),
        ('kick',          'Kicks a player from server', True),
        ('kickghost',     'Kicks a ghost player from server', True),
        ('ban',           'Bans a player from server', True),
        ('unban',         'UnBans a player from server', True),
        ('banip',         'Bans an IP address from server', True),
        ('unbanip',       'UnBans an IP address from server', True),
        ('black',         'Blacklists a player from server', True),
        ('unblack',       'UnBlacklists a player from server', True),
        ('addguest',      'Adds a guest player to server', True),
        ('removeguest',   'Removes a guest player from server', True),
        ('forceteam',     'Forces player into {Blue} or {Red} team', True),
        ('forcespec',     'Forces player into free spectator', True),
        ('specfree',      'Forces spectator into free mode', True),
    
        # --- VOTING ---
        ('pass',          'Passes a chat-based or TMX /add vote', True),
        ('cancel',        'Cancels any running vote', True),
        ('can',           'Cancels any running vote', True),
    
        # --- LISTS / DATABASE ---
        ('players',       'Displays list of known players', True),
        ('showbanlist',   'Displays current ban list', True),
        ('listbans',      'Displays current ban list', True),
        ('showiplist',    'Displays current banned IPs list', True),
        ('listips',       'Displays current banned IPs list', True),
        ('showblacklist', 'Displays current black list', True),
        ('listblacks',    'Displays current black list', True),
        ('showguestlist', 'Displays current guest list', True),
        ('listguests',    'Displays current guest list', True),
    
        # --- LIST MANAGEMENT ---
        ('writeiplist',   'Saves current banned IPs list', True),
        ('readiplist',    'Loads current banned IPs list', True),
        ('cleaniplist',   'Cleans current banned IPs list', True),
        ('writeblacklist','Saves current black list', True),
        ('readblacklist', 'Loads current black list', True),
        ('cleanblacklist','Cleans current black list', True),
        ('writeguestlist','Saves current guest list', True),
        ('readguestlist', 'Loads current guest list', True),
        ('cleanguestlist','Cleans current guest list', True),
        ('cleanbanlist',  'Cleans current ban list', True),
    
        # --- MUTE / IGNORE ---
        ('mute',          'Adds a player to global mute/ignore list', True),
        ('ignore',        'Adds a player to global mute/ignore list', True),
        ('unmute',        'Removes a player from global mute/ignore list', True),
        ('unignore',      'Removes a player from global mute/ignore list', True),
        ('mutelist',      'Displays global mute/ignore list', True),
        ('listmutes',     'Displays global mute/ignore list', True),
        ('ignorelist',    'Displays global mute/ignore list', True),
        ('listignores',   'Displays global mute/ignore list', True),
        ('cleanmutes',    'Cleans global mute/ignore list', True),
        ('cleanignores',  'Cleans global mute/ignore list', True),
    
        # --- ADMIN MANAGEMENT ---
        ('addadmin',      'Adds a new admin', True),
        ('removeadmin',   'Removes an admin', True),
        ('addop',         'Adds a new operator', True),
        ('removeop',      'Removes an operator', True),
        ('listmasters',   'Displays current masteradmin list', True),
        ('listadmins',    'Displays current admin list', True),
        ('listops',       'Displays current operator list', True),
        ('adminability',  'Shows/changes admin ability {ON/OFF}', True),
        ('opability',     'Shows/changes operator ability {ON/OFF}', True),
        ('listabilities', 'Displays current abilities list', True),
        ('writeabilities','Saves current admin/operator abilities', True),
        ('readabilities', 'Loads admin/operator abilities', True),
    
        # --- FILE / TRACKLIST ---
        ('writetracklist','Saves current track list', True),
        ('readtracklist', 'Loads current track list', True),
    
        # --- UI / PANELS ---
        ('panel',         'Selects admin panel (see: /admin panel help)', True),
        ('style',         'Selects default window style', True),
        ('admpanel',      'Selects default admin panel', True),
        ('donpanel',      'Selects default donate panel', True),
        ('recpanel',      'Selects default records panel', True),
        ('votepanel',     'Selects default vote panel', True),
    
        # --- RECORDS ---
        ('delrec',        'Deletes specific record on current track', True),
        ('prunerecs',     'Deletes records for specified track', True),
    
        # --- MATCH / GAMEPLAY ---
        ('rpoints',       'Sets custom Rounds points (see: /admin rpoints help)', True),
        ('match',         '{begin/end} to start/stop match tracking', True),
    
        # --- ECONOMY ---
        ('coppers',       "Shows server's coppers amount", True),
        ('pay',           'Pays server coppers to login', True),
    
        # --- COMMUNICATION ---
        ('wall',          'Displays popup message to all players', True),
        ('mta',           'Displays popup message to all players', True),
        ('pm',            'Sends private message to all available admins', True),
        ('pmlog',         'Displays log of recent private admin messages', True),
    
        # --- MISC ---
        ('relays',        'Displays relays list or shows relay master', True),
        ('access',        'Handles player access control', True),
        ('mergegbl',      'Merges a global black list {URL}', True),
        ('call',          'Executes direct server call (see: /admin call help)', True),
    
        # --- SYSTEM ---
        ('unlock',        'Unlocks admin commands & features', True),
        ('debug',         'Toggles debugging output', True),
        ('pyres',         'Reinitializes the entire PyXaseco controller', True),
        ('shutdown',      'Shuts down XASECO', True),
        ('shutdownall',   'Shuts down Server & XASECO', True),
    ]
        # Commands registered by other plugins — must not get admin aliases



    _read_adminops_xml(aseco)


async def _admin_startup(aseco: 'Aseco', _param=None):
    try:
        ok = _read_adminops_xml(aseco)
        if ok:
            logger.info('[Admin] Loaded adminops.xml on startup')
        else:
            logger.warning('[Admin] adminops.xml not loaded on startup')
    except Exception as e:
        logger.warning('[Admin] Startup read adminops.xml failed: %s', e)

async def _admin_player_connect(aseco: 'Aseco', player):
    await _display_admin_panel_if_available(aseco, player)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _reply(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)


async def _broadcast(aseco: 'Aseco', msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage', aseco.format_colors(msg))

async def _display_admin_panel_if_available(aseco: 'Aseco', player):
    """
    Show the player's selected admin panel, if plugin_panels is available
    and the player is an admin.
    """
    try:
        if not aseco.is_any_admin(player):
            return

        from pyxaseco.plugins.plugin_panels import display_admpanel
        await display_admpanel(aseco, player)
    except Exception:
        pass


async def _hide_admin_panel(aseco: 'Aseco', login: str):
    """
    Hide admin panel directly. Ownership lives in chat_admin.py now.
    """
    try:
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPageToLogin',
            login,
            aseco.format_colors('<manialink id="3"></manialink>'),
            0,
            False
        )
    except Exception:
        pass

def _visible_admin_commands_for_player(aseco: 'Aseco', player) -> list[tuple[str, str]]:
    result = []

    for name, cc in sorted(aseco._chat_commands.items()):
        if not getattr(cc, 'isadmin', False):
            continue

        cmd = name.lower().split('/')[0]

        if _auth_check(aseco, player, cmd)[0]:
            result.append((name, cc.help))

    return result


def _visible_normal_commands_for_player(aseco: 'Aseco', player) -> list[tuple[str, str]]:
    result = []

    for name, cc in sorted(aseco._chat_commands.items()):
        if getattr(cc, 'isadmin', False):
            continue

        try:
            if aseco.allow_ability(player, name.split('/')[0]):
                result.append((name, cc.help))
        except Exception:
            result.append((name, cc.help))

    return result

async def _deny_protected_target(aseco: 'Aseco', actor, target_login: str):
    await _reply(
        aseco,
        actor.login,
        f'{{#server}}> {{#error}}You are not allowed to target {{#highlite}}{target_login}{{#error}} due to access hierarchy.'
    )

def _all_visible_commands_for_player(aseco: 'Aseco', player) -> list[tuple[str, str]]:
    seen = set()
    rows: list[tuple[str, str]] = []

    for name, help_text in _visible_normal_commands_for_player(aseco, player):
        key = name.lower()
        if key not in seen:
            seen.add(key)
            rows.append((name, help_text))

    for name, help_text in _visible_admin_commands_for_player(aseco, player):
        key = name.lower()
        if key not in seen:
            seen.add(key)
            rows.append((name, help_text))

    return rows

def _is_masteradmin_player(aseco: 'Aseco', player) -> bool:
    return _viewer_role_level(aseco, player) >= 3

def _fmt_admin(aseco: 'Aseco', admin, chattitle: str, action: str, target: str = '') -> str:
    """Format standard admin action message."""
    nick = strip_colors(admin.nickname)
    base = f'{{#server}}>> {{#admin}}{chattitle}$z$s {{#highlite}}{nick}$z$s{{#admin}} {action}'
    if target:
        base += f' {{#highlite}}{target}'
    return base


def _login_in_role_list(role_list: dict, login: str) -> bool:
    vals = role_list.get('TMLOGIN', []) if isinstance(role_list, dict) else []
    login_l = (login or '').strip().lower()
    return any(str(v).strip().lower() == login_l for v in vals)

def _role_level(aseco: 'Aseco', login: str) -> int:
    """
    0 = player
    1 = operator
    2 = admin
    3 = masteradmin
    """
    login = (login or '').strip()

    if _login_in_role_list(getattr(aseco.settings, 'masteradmin_list', {}), login):
        return 3
    if _login_in_role_list(getattr(aseco.settings, 'admin_list', {}), login):
        return 2
    if _login_in_role_list(getattr(aseco.settings, 'operator_list', {}), login):
        return 1
    return 0


def _role_name(level: int) -> str:
    return {
        0: 'Player',
        1: 'Operator',
        2: 'Admin',
        3: 'MasterAdmin',
    }.get(level, 'Player')


def _viewer_role_level(aseco: 'Aseco', player) -> int:
    return _role_level(aseco, getattr(player, 'login', ''))


def _can_target_player(aseco: 'Aseco', actor, target) -> bool:
    """
    Moderation hierarchy:
      Operator -> may target Player only
      Admin -> may target Player and Operator only
      MasterAdmin -> may target everyone
    """
    actor_level = _viewer_role_level(aseco, actor)
    target_level = _role_level(aseco, getattr(target, 'login', ''))

    if actor_level <= 0:
        return False
    if actor_level >= 3:
        return True

    return actor_level > target_level


def _can_target_login(aseco: 'Aseco', actor, target_login: str) -> bool:
    actor_level = _viewer_role_level(aseco, actor)
    target_level = _role_level(aseco, target_login)

    if actor_level <= 0:
        return False
    if actor_level >= 3:
        return True

    return actor_level > target_level


def _auth_check(aseco: 'Aseco', admin, sub: str):
    """
    Returns (logtitle, chattitle) if the player has access to the subcommand.
    Some informational commands are public.
    """
    login = getattr(admin, 'login', '')
    sub = (sub or '').strip().lower()

    public_admin_commands = {'help', 'helpall', 'listmasters', 'listadmins', 'listops'}
    masteradmin_only = {'addadmin', 'removeadmin'}
    admin_or_master_only = {'addop', 'removeop'}

    if sub in public_admin_commands:
        level = _role_level(aseco, login)
        return _role_name(level), _role_name(level)

    if sub == 'pyres' or sub in masteradmin_only:
        if _login_in_role_list(getattr(aseco.settings, 'masteradmin_list', {}), login):
            return 'MasterAdmin', 'MasterAdmin'
        return None, None

    if sub in admin_or_master_only:
        if _login_in_role_list(getattr(aseco.settings, 'masteradmin_list', {}), login):
            return 'MasterAdmin', 'MasterAdmin'
        if _login_in_role_list(getattr(aseco.settings, 'admin_list', {}), login):
            return 'Admin', 'Admin'
        return None, None

    if _login_in_role_list(getattr(aseco.settings, 'masteradmin_list', {}), login):
        return 'MasterAdmin', 'MasterAdmin'

    if _login_in_role_list(getattr(aseco.settings, 'admin_list', {}), login):
        if _ability_enabled(aseco, 'admin', sub):
            return 'Admin', 'Admin'
        return None, None

    if _login_in_role_list(getattr(aseco.settings, 'operator_list', {}), login):
        if _ability_enabled(aseco, 'op', sub):
            return 'Operator', 'Operator'
        return None, None

    return None, None


def _get_ability_store(aseco: 'Aseco', role: str) -> dict:
    """
    role: 'admin' or 'op'
    Keeps a mutable dict on aseco.settings.
    """
    attr = 'admin_abilities' if role == 'admin' else 'op_abilities'
    store = getattr(aseco.settings, attr, None)
    if not isinstance(store, dict):
        store = {}
        setattr(aseco.settings, attr, store)
    return store


def _ability_enabled(aseco: 'Aseco', role: str, ability: str) -> bool:
    ability = (ability or '').strip().lower()
    if not ability:
        return False

    store = _get_ability_store(aseco, role)
    if ability in store:
        return bool(store[ability])

    # Fallback to current runtime permission rules
    if role == 'admin':
        try:
            return bool(aseco.allow_admin_ability(ability))
        except Exception:
            return False
    else:
        try:
            return bool(aseco.allow_op_ability(ability))
        except Exception:
            return False


def _set_ability_enabled(aseco: 'Aseco', role: str, ability: str, enabled: bool):
    ability = (ability or '').strip().lower()
    if not ability:
        return
    store = _get_ability_store(aseco, role)
    store[ability] = bool(enabled)


def _all_admin_command_names(aseco: 'Aseco') -> list[str]:
    names = set()

    for name, cc in sorted(aseco._chat_commands.items()):
        if getattr(cc, 'isadmin', False):
            for part in str(name).lower().split('/'):
                part = part.strip()
                if part:
                    names.add(part)

    names.update(_LEGACY_ADMIN_ABILITIES.keys())
    names.update(_LEGACY_OPERATOR_ABILITIES.keys())

    return sorted(names)


def _ability_rows(aseco: 'Aseco') -> list[list[str]]:
    rows = [['Command', 'Admin', 'Operator']]
    for cmd in _all_admin_command_names(aseco):
        rows.append([
            f'/{cmd}',
            '{#green}ON' if _ability_enabled(aseco, 'admin', cmd) else '{#error}OFF',
            '{#green}ON' if _ability_enabled(aseco, 'op', cmd) else '{#error}OFF',
        ])
    return rows


def _find_player_login_by_id_or_name(aseco: 'Aseco', admin, value: str) -> str | None:
    value = (value or '').strip()
    if not value:
        return None

    if value.isdigit() and hasattr(admin, 'playerlist'):
        idx = int(value) - 1
        if 0 <= idx < len(admin.playerlist):
            item = admin.playerlist[idx]
            if isinstance(item, dict):
                return item.get('login')
            return str(item)

    pl = aseco.server.players.get_player(value)
    if pl:
        return pl.login

    value_l = value.lower()
    for pl in aseco.server.players.all():
        if pl.login.lower() == value_l:
            return pl.login
        if value_l in strip_colors(getattr(pl, 'nickname', '')).lower():
            return pl.login

    return value


def _write_adminops_xml(aseco: 'Aseco'):
    """
    Write adminops.xml in XAseco-compatible legacy format, preserving legacy ability keys.
    """
    global _LEGACY_ADMINOPS_TITLES, _LEGACY_ADMIN_ABILITIES, _LEGACY_OPERATOR_ABILITIES

    try:
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        path = base / 'adminops.xml'

        masters = list(aseco.settings.masteradmin_list.get('TMLOGIN', []))
        admins  = list(aseco.settings.admin_list.get('TMLOGIN', []))
        ops     = list(aseco.settings.operator_list.get('TMLOGIN', []))

        admin_store = _get_ability_store(aseco, 'admin')
        op_store    = _get_ability_store(aseco, 'op')

        admin_abilities = dict(_LEGACY_ADMIN_ABILITIES)
        operator_abilities = dict(_LEGACY_OPERATOR_ABILITIES)

        admin_abilities.update({k.lower(): bool(v) for k, v in admin_store.items()})
        operator_abilities.update({k.lower(): bool(v) for k, v in op_store.items()})

        all_cmds = sorted(set(admin_abilities) | set(operator_abilities) | set(_all_admin_command_names(aseco)))

        def yn(v: bool) -> str:
            return 'true' if v else 'false'

        titles = {
            'masteradmin': _LEGACY_ADMINOPS_TITLES.get('masteradmin', 'MasterAdmin'),
            'admin': _LEGACY_ADMINOPS_TITLES.get('admin', 'Admin'),
            'operator': _LEGACY_ADMINOPS_TITLES.get('operator', 'Operator'),
        }

        lines = ['<?xml version="1.0" encoding="utf-8" ?>', '<lists>']

        lines.append('\t<titles>')
        lines.append(f'\t\t<masteradmin>{titles["masteradmin"]}</masteradmin>')
        lines.append(f'\t\t<admin>{titles["admin"]}</admin>')
        lines.append(f'\t\t<operator>{titles["operator"]}</operator>')
        lines.append('\t</titles>')
        lines.append('')

        lines.append('\t<masteradmins>')
        for login in masters:
            lines.append(f'\t\t<tmlogin>{login}</tmlogin> <ipaddress></ipaddress>')
        lines.append('\t</masteradmins>')
        lines.append('')

        lines.append('\t<admins>')
        for login in admins:
            lines.append(f'\t\t<tmlogin>{login}</tmlogin> <ipaddress></ipaddress>')
        lines.append('\t</admins>')
        lines.append('')

        lines.append('\t<operators>')
        for login in ops:
            lines.append(f'\t\t<tmlogin>{login}</tmlogin> <ipaddress></ipaddress>')
        lines.append('\t</operators>')
        lines.append('')

        lines.append('\t<admin_abilities>')
        for cmd in all_cmds:
            value = admin_abilities.get(cmd, _ability_enabled(aseco, 'admin', cmd))
            lines.append(f'\t\t<{cmd}>{yn(bool(value))}</{cmd}>')
        lines.append('\t</admin_abilities>')
        lines.append('')

        lines.append('\t<operator_abilities>')
        for cmd in all_cmds:
            value = operator_abilities.get(cmd, _ability_enabled(aseco, 'op', cmd))
            lines.append(f'\t\t<{cmd}>{yn(bool(value))}</{cmd}>')
        lines.append('\t</operator_abilities>')

        lines.append('</lists>')
        path.write_text('\n'.join(lines), encoding='utf-8')

        _LEGACY_ADMIN_ABILITIES = dict(admin_abilities)
        _LEGACY_OPERATOR_ABILITIES = dict(operator_abilities)

        return path

    except Exception as e:
        logger.warning('[Admin] Could not write adminops.xml: %s', e)
        return None

def _read_adminops_xml(aseco: 'Aseco'):
    """
    Read legacy XAseco adminops.xml format and preserve all ability keys.
    """
    global _LEGACY_ADMINOPS_TITLES, _LEGACY_ADMIN_ABILITIES, _LEGACY_OPERATOR_ABILITIES

    try:
        from pyxaseco.core.config import parse_xml_file

        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        path = base / 'adminops.xml'
        if not path.exists():
            return False

        data = parse_xml_file(path)
        if not data:
            return False

        root = data.get('LISTS', {})
        if not isinstance(root, dict):
            return False

        titles_section = root.get('TITLES', [])
        if titles_section:
            blk = titles_section[0] if isinstance(titles_section, list) else titles_section
            if isinstance(blk, dict):
                _LEGACY_ADMINOPS_TITLES = {
                    'masteradmin': (blk.get('MASTERADMIN', ['MasterAdmin'])[0] if blk.get('MASTERADMIN') else 'MasterAdmin'),
                    'admin': (blk.get('ADMIN', ['Admin'])[0] if blk.get('ADMIN') else 'Admin'),
                    'operator': (blk.get('OPERATOR', ['Operator'])[0] if blk.get('OPERATOR') else 'Operator'),
                }

        def _extract_logins(section_name: str) -> list[str]:
            section = root.get(section_name.upper(), [])
            if not section:
                return []
            blk = section[0] if isinstance(section, list) else section
            if not isinstance(blk, dict):
                return []
            vals = blk.get('TMLOGIN', [])
            return [str(v).strip() for v in vals if str(v).strip()]

        aseco.settings.masteradmin_list['TMLOGIN'] = _extract_logins('MASTERADMINS')
        aseco.settings.admin_list['TMLOGIN'] = _extract_logins('ADMINS')
        aseco.settings.operator_list['TMLOGIN'] = _extract_logins('OPERATORS')

        admin_store = _get_ability_store(aseco, 'admin')
        op_store = _get_ability_store(aseco, 'op')
        admin_store.clear()
        op_store.clear()

        def _load_abilities(section_name: str) -> dict[str, bool]:
            result: dict[str, bool] = {}
            section = root.get(section_name.upper(), [])
            if not section:
                return result

            blk = section[0] if isinstance(section, list) else section
            if not isinstance(blk, dict):
                return result

            for key, value in blk.items():
                if key == 'IPADDRESS':
                    continue
                if not value:
                    continue
                raw = value[0] if isinstance(value, list) else value
                result[key.lower()] = str(raw).strip().lower() == 'true'
            return result

        _LEGACY_ADMIN_ABILITIES = _load_abilities('ADMIN_ABILITIES')
        _LEGACY_OPERATOR_ABILITIES = _load_abilities('OPERATOR_ABILITIES')

        admin_store.update(_LEGACY_ADMIN_ABILITIES)
        op_store.update(_LEGACY_OPERATOR_ABILITIES)

        return True

    except Exception as e:
        logger.warning('[Admin] Could not read adminops.xml: %s', e)
        return False

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

async def _get_player_param(aseco: 'Aseco', admin, arg: str, offline: bool = False):
    value = (arg or '').strip()
    if not value:
        await _reply(aseco, admin.login, '{#server}> {#error}Missing player parameter.')
        return None

    players = aseco.server.players.all()

    pl = aseco.server.players.get_player(value)
    if pl:
        return pl

    value_l = value.lower()

    exact = [p for p in players if p.login.lower() == value_l]
    if exact:
        return exact[0]

    partial = [p for p in players if value_l in p.login.lower()]
    if len(partial) == 1:
        return partial[0]

    nick_matches = [
        p for p in players
        if value_l in strip_colors(getattr(p, 'nickname', '')).lower()
    ]
    if len(nick_matches) == 1:
        return nick_matches[0]

    if len(partial) > 1 or len(nick_matches) > 1:
        await _reply(
            aseco,
            admin.login,
            '{#server}> {#error}Multiple players match that name/login.'
        )
        return None

    if offline:
        db_player = await _get_offline_player_from_db(aseco, value)
        if db_player:
            return db_player

        class _OfflinePlayer:
            def __init__(self, login: str):
                self.login = login
                self.nickname = login
        return _OfflinePlayer(value)

    await _reply(
        aseco,
        admin.login,
        f'{{#server}}> {{#error}}Player not found: {{#highlite}}{value}'
    )
    return None


async def _get_offline_player_from_db(aseco: 'Aseco', value: str):
    value = (value or '').strip()
    if not value:
        return None

    try:
        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
        except ImportError:
            from pyxaseco_plugins.plugin_localdatabase import get_pool

        pool = await get_pool()
        if not pool:
            return None

        value_l = value.lower()
        like = f'%{value}%'

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT Login, NickName FROM players WHERE Login=%s LIMIT 1',
                    (value,)
                )
                row = await cur.fetchone()
                if row:
                    rows = [row]
                else:
                    await cur.execute(
                        'SELECT Login, NickName FROM players '
                        'WHERE Login LIKE %s OR NickName LIKE %s '
                        'ORDER BY UpdatedAt DESC LIMIT 50',
                        (like, like)
                    )
                    rows = await cur.fetchall()
    except Exception:
        return None

    if not rows:
        return None

    candidates = []
    for row in rows:
        if isinstance(row, dict):
            login = str(row.get('Login') or '').strip()
            nickname = str(row.get('NickName') or '').strip()
        else:
            login = str(row[0] or '').strip()
            nickname = str(row[1] or '').strip()
        if not login:
            continue
        candidates.append((login, nickname))

    if not candidates:
        return None

    exact_login = [item for item in candidates if item[0].lower() == value_l]
    if len(exact_login) == 1:
        login, nickname = exact_login[0]
    else:
        stripped_exact = [
            item for item in candidates
            if strip_colors(item[1]).strip().lower() == value_l
        ]
        if len(stripped_exact) == 1:
            login, nickname = stripped_exact[0]
        else:
            partial = [
                item for item in candidates
                if value_l in item[0].lower() or value_l in strip_colors(item[1]).lower()
            ]
            if len(partial) != 1:
                return None
            login, nickname = partial[0]

    class _OfflinePlayer:
        def __init__(self, login: str, nickname: str):
            self.login = login
            self.nickname = nickname or login

    return _OfflinePlayer(login, nickname)


async def _admin_display_name(aseco: 'Aseco', login: str) -> str:
    login = (login or '').strip()
    if not login:
        return ''

    player = aseco.server.players.get_player(login)
    if player and getattr(player, 'nickname', ''):
        nickname = strip_colors(player.nickname).strip()
        if nickname:
            return nickname

    try:
        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
        except ImportError:
            from pyxaseco_plugins.plugin_localdatabase import get_pool

        pool = await get_pool()
        if not pool:
            return login

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName FROM players WHERE Login=%s LIMIT 1',
                    (login,)
                )
                row = await cur.fetchone()
    except Exception:
        return login

    if isinstance(row, dict):
        nickname = row.get('NickName', '')
    elif row:
        nickname = row[0]
    else:
        nickname = ''

    nickname = strip_colors(str(nickname or '')).strip()
    return nickname or login


async def _admin_display_names(aseco: 'Aseco', logins: list[str]) -> list[str]:
    names: list[str] = []
    for item in logins:
        names.append(await _admin_display_name(aseco, item))
    return names


async def _find_track_uid_by_filename(aseco: 'Aseco', fname: str) -> str:
    try:
        tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
        for t in tracks:
            if t.get('FileName', '') == fname:
                return t.get('UId', '') or t.get('Uid', '') or ''
    except Exception:
        pass

    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import _parse_gbx_metadata
        gbx_path = _resolve_track_path(aseco, fname)
        if gbx_path.exists():
            metadata = await asyncio.to_thread(_parse_gbx_metadata, gbx_path)
            return (metadata.get('uid', '') or '').strip()
    except Exception:
        pass

    return ''


def _resolve_track_path(aseco: 'Aseco', fname: str) -> pathlib.Path:
    rel = str(fname or '').replace('/', '\\').lstrip('\\')
    return (aseco._base_dir.parent / 'GameData' / 'Tracks' / rel).resolve()


async def _remove_track_from_rotation(aseco: 'Aseco', fname: str, uid: str = ''):
    await aseco.client.query_ignore_result('RemoveChallenge', fname)
    await aseco.release_event('onTracklistChanged', ['remove', fname])

    if not uid:
        return

    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import (
            _matchsettings_path, _remove_matchsettings_entry_by_uid
        )
        await asyncio.to_thread(
            _remove_matchsettings_entry_by_uid,
            _matchsettings_path(aseco),
            uid
        )
    except Exception as e:
        aseco.console('[Admin] MatchSettings warning for [{1}]: {2}', fname, str(e))


async def _erase_track_from_localdb(aseco: 'Aseco', uid: str):
    uid = (uid or '').strip()
    if not uid:
        return

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT Id FROM challenges WHERE Uid=%s LIMIT 1',
                    (uid,)
                )
                row = await cur.fetchone()
                if isinstance(row, dict):
                    challenge_id = int(row.get('Id') or 0)
                elif row:
                    challenge_id = int(row[0] or 0)
                else:
                    challenge_id = 0

                if challenge_id:
                    await cur.execute('DELETE FROM records WHERE ChallengeId=%s', (challenge_id,))
                    await cur.execute('DELETE FROM rs_times WHERE challengeID=%s', (challenge_id,))
                    await cur.execute('DELETE FROM rs_karma WHERE ChallengeId=%s', (challenge_id,))
                else:
                    challenge_id = 0

                try:
                    await cur.execute('DELETE FROM rs_karma WHERE uid=%s', (uid,))
                except Exception:
                    pass

                await cur.execute('DELETE FROM custom_tracktimes WHERE challenge_uid=%s', (uid,))
                await cur.execute('DELETE FROM challenges WHERE Uid=%s', (uid,))
    except Exception as e:
        aseco.console('[Admin] erase LocalDB warning for UID [{1}]: {2}', uid, str(e))

def _get_bool_on_off(value: str) -> bool | None:
    v = (value or '').strip().lower()
    if v == 'on':
        return True
    if v == 'off':
        return False
    return None


async def _delegate_if_exists(
    aseco: 'Aseco',
    login: str,
    func_path: str,
    *args,
    unavailable_msg: str | None = None,
) -> bool:
    try:
        mod_name, func_name = func_path.rsplit('.', 1)
        module = __import__(mod_name, fromlist=[func_name])
        func = getattr(module, func_name, None)
        if not callable(func):
            raise AttributeError(func_name)
    except (ImportError, AttributeError):
        if unavailable_msg:
            await _reply(aseco, login, unavailable_msg)
        return False

    result = func(*args)
    if asyncio.iscoroutine(result):
        await result
    return True

def _playerlist_get_login(admin, idx1: int) -> str | None:
    items = getattr(admin, 'playerlist', None) or []
    idx0 = idx1 - 1
    if 0 <= idx0 < len(items):
        item = items[idx0]
        if isinstance(item, dict):
            return item.get('login')
        return getattr(item, 'login', None) or str(item)
    return None

def _playerlist_get_ip(admin, idx1: int) -> str | None:
    items = getattr(admin, 'iplist', None) or []
    idx0 = idx1 - 1
    if 0 <= idx0 < len(items):
        return str(items[idx0])
    return None


async def _dispatch_public_admin_subcommand(aseco: 'Aseco', command: dict, sub: str):
    forwarded = dict(command)
    forwarded['params'] = sub
    await chat_admin(aseco, forwarded)


async def chat_listmasters(aseco: 'Aseco', command: dict):
    await _dispatch_public_admin_subcommand(aseco, command, 'listmasters')


async def chat_listadmins(aseco: 'Aseco', command: dict):
    await _dispatch_public_admin_subcommand(aseco, command, 'listadmins')


async def chat_listops(aseco: 'Aseco', command: dict):
    await _dispatch_public_admin_subcommand(aseco, command, 'listops')

def _is_unlocked(admin) -> bool:
    return bool(getattr(admin, 'unlocked', False))

def _set_unlocked(admin, value: bool = True):
    setattr(admin, 'unlocked', bool(value))

def _lock_password_enabled(aseco: 'Aseco') -> str:
    settings = getattr(aseco, 'settings', None)
    if settings is None:
        return ''
    pw = getattr(settings, 'lock_password', '')
    if isinstance(settings, dict):
        pw = settings.get('lock_password', pw)
    return str(pw or '')

def _is_admin_recipient(aseco: 'Aseco', player) -> bool:
    return _viewer_role_level(aseco, player) >= 1

def _online_admin_recipients(aseco: 'Aseco', sender) -> list:
    recipients = []
    for pl in aseco.server.players.all():
        if not getattr(pl, 'login', ''):
            continue
        if pl.login == getattr(sender, 'login', ''):
            continue
        if _is_admin_recipient(aseco, pl):
            recipients.append(pl)
    return recipients

def _parse_call_arg(value: str):
    raw = (value or '').strip()
    low = raw.lower()

    if low == 'true':
        return True
    if low == 'false':
        return False
    if low == 'none' or low == 'null':
        return None

    if raw.isdigit() or (raw.startswith('-') and raw[1:].isdigit()):
        try:
            return int(raw)
        except Exception:
            pass

    try:
        if '.' in raw:
            return float(raw)
    except Exception:
        pass

    if (raw.startswith('[') and raw.endswith(']')) or (raw.startswith('{') and raw.endswith('}')):
        try:
            import ast
            return ast.literal_eval(raw)
        except Exception:
            return raw

    return raw

def _extract_logins_from_text(text: str) -> list[str]:
    """
    Extract plausible TM logins from a fetched blacklist text file.
    Accepts plain lines, optionally ignoring comments and separators.
    """
    result: list[str] = []
    seen: set[str] = set()

    for raw_line in (text or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('#') or line.startswith('//') or line.startswith(';'):
            continue

        # common cases: "login", "login|comment", "login comment"
        token = line.split('|', 1)[0].strip()
        token = token.split(None, 1)[0].strip()

        if not token:
            continue

        key = token.lower()
        if key not in seen:
            seen.add(key)
            result.append(token)

    return result


async def _fetch_text_url(url: str, timeout: int = 15) -> str:
    def _read() -> str:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'PyXASECO/ChatAdmin'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            charset = resp.headers.get_content_charset() or 'utf-8'
            return data.decode(charset, errors='replace')

    return await asyncio.to_thread(_read)


async def _best_effort_shutdown(aseco: 'Aseco', stop_server: bool = False) -> bool:
    """
    Try several common shutdown hooks without assuming one exact runtime API.
    Returns True if a shutdown path was invoked.
    """
    # Optionally stop dedicated server first
    if stop_server:
        for method_name in ('StopServer', 'QuitServer'):
            try:
                await aseco.client.query_ignore_result(method_name)
                break
            except Exception:
                pass

    # Aseco/framework shutdown hooks
    for attr in ('shutdown', 'stop', 'quit', 'terminate'):
        func = getattr(aseco, attr, None)
        if callable(func):
            result = func()
            if asyncio.iscoroutine(result):
                await result
            return True

    # Fallback flags some cores use
    for attr in ('running', '_running', 'alive', '_alive'):
        if hasattr(aseco, attr):
            try:
                setattr(aseco, attr, False)
                return True
            except Exception:
                pass

    return False

async def chat_admin(aseco: 'Aseco', command: dict):
    admin = command['author']
    login = admin.login
    raw = (command.get('params') or '').strip()

    # panel is delegated later in this dispatcher

    parts = raw.split(None, 1)
    sub   = parts[0].lower() if parts else ''
    arg   = parts[1] if len(parts) > 1 else ''
    args  = arg.split() if arg else []

    logtitle, chattitle = _auth_check(aseco, admin, sub)

    # Allow everyone to use informational public admin commands.
    if sub not in ('help', 'helpall', 'listmasters', 'listadmins', 'listops') and not logtitle:
        aseco.console('{1} tried to use admin command (no permission!): {2}', login, sub)
        await _reply(aseco, login, '{#error}You don\'t have the required admin rights to do that!')
        return

    if not logtitle:
        logtitle, chattitle = 'Player', 'Player'

    # when lock_password is configured, admin commands require /admin unlock first.
    lock_password = _lock_password_enabled(aseco)
    if lock_password and not _is_unlocked(admin) and sub != 'unlock':
        aseco.console('{1} tried to use admin command (not unlocked!): {2}', login, raw)
        await _reply(aseco, login, '{#error}You don\'t have the required admin rights to do that!')
        return

    # ---- Map / server control ----
    if sub == 'unlock':
        lock_password = _lock_password_enabled(aseco)
        if not lock_password:
            await _reply(aseco, login, '{#server}> {#message}Admin commands are not locked.')
            return

        if arg.strip() == lock_password:
            _set_unlocked(admin, True)
            aseco.console('{1} [{2}] unlocked admin commands', logtitle, login)
            await _reply(aseco, login, '{#server}> {#message}Admin commands unlocked.')
        else:
            aseco.console('{1} [{2}] failed unlock attempt', logtitle, login)
            await _reply(aseco, login, '{#server}> {#error}Invalid unlock password.')
        return

    if sub == 'help':
        cmds_list = _all_visible_commands_for_player(aseco, admin)
        shown = cmds_list[:20]

        if shown:
            msg = (
                f'{{#server}}> Available commands: ' +
                ' '.join(f'{{#highlite}}/{n}{{#message}}' for n, _ in shown)
            )
            if len(cmds_list) > len(shown):
                msg += ' {#message}... use {#highlite}/admin helpall'
        else:
            msg = '{#server}> {#error}No commands available.'

        await _reply(aseco, login, msg)

    elif sub == 'helpall':
        visible = _all_visible_commands_for_player(aseco, admin)
        rows = [[f'/{name}', help_text] for name, help_text in visible]

        pages = [rows[i:i+14] for i in range(0, max(len(rows), 1), 14)]
        admin.msgs = [[
            1,
            'Available commands:',
            [1.2, 0.3, 0.9],
            ['Icons128x128_1', 'ProfileAdvanced', 0.02]
        ]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub == 'setservername' and arg:
        await aseco.client.query_ignore_result('SetServerName', arg)
        aseco.console('{1} [{2}] set new server name [{3}]', logtitle, login, arg)
        await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                           'sets servername to', arg))

    elif sub == 'setcomment' and arg:
        await aseco.client.query_ignore_result('SetServerComment', arg)
        aseco.console('{1} [{2}] set server comment', logtitle, login)
        await _reply(aseco, login,
                     _fmt_admin(aseco, admin, chattitle, 'sets server comment to', arg))

    elif sub == 'setpwd':
        await aseco.client.query_ignore_result('SetServerPassword', arg)
        action = f'sets player password to {arg!r}' if arg else 'disables player password'
        aseco.console('{1} [{2}] {3}', logtitle, login, action)
        await _reply(aseco, login, _fmt_admin(aseco, admin, chattitle, action))

    elif sub == 'setspecpwd':
        await aseco.client.query_ignore_result('SetServerPasswordForSpectator', arg)
        action = f'sets spectator password to {arg!r}' if arg else 'disables spectator password'
        aseco.console('{1} [{2}] {3}', logtitle, login, action)
        await _reply(aseco, login, _fmt_admin(aseco, admin, chattitle, action))

    elif sub == 'setrefpwd':
        if getattr(aseco.server, 'game', '').upper() == 'TMF' or getattr(getattr(aseco.server, 'gameinfo', None), 'game', '').upper() == 'TMF':
            await aseco.client.query_ignore_result('SetRefereePassword', arg)
            action = f'sets referee password to {arg!r}' if arg else 'disables referee password'
            aseco.console('{1} [{2}] {3}', logtitle, login, action)
            await _reply(aseco, login, _fmt_admin(aseco, admin, chattitle, action))
        else:
            await _reply(aseco, login, '{#server}> {#error}Command only available on TMF/TMUF.')

    elif sub == 'setmaxplayers' and args and args[0].isdigit():
        n = int(args[0])
        await aseco.client.query_ignore_result('SetMaxPlayers', n)
        aseco.console('{1} [{2}] set new player maximum [{3}]', logtitle, login, n)
        await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                           f'sets new player maximum to {n}!'))

    elif sub == 'setmaxspecs' and args and args[0].isdigit():
        n = int(args[0])
        await aseco.client.query_ignore_result('SetMaxSpectators', n)
        aseco.console('{1} [{2}] set new spectator maximum [{3}]', logtitle, login, n)
        await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                           f'sets new spectator maximum to {n}!'))

    elif sub == 'setgamemode' and args:
        mode_name = args[0].lower()
        mode = GAME_MODES.get(mode_name, -1)
        if mode >= 0:
            current_mode = getattr(getattr(aseco.server, 'gameinfo', None), 'mode', None)
            changing_mode = bool(getattr(aseco, 'changingmode', False))
            if changing_mode or current_mode != mode:
                await aseco.client.query_ignore_result('SetGameMode', mode)
                setattr(aseco, 'changingmode', True)
                aseco.console('{1} [{2}] set new game mode [{3}]', logtitle, login, mode_name.upper())
                await _broadcast(
                    aseco,
                    _fmt_admin(aseco, admin, chattitle, f'sets next game mode to {mode_name.upper()}!')
                )
            else:
                setattr(aseco, 'changingmode', False)
                await _reply(aseco, login, f'{{#server}}> Same game mode {{#highlite}}{mode_name.upper()}')
        else:
            await _reply(
                aseco,
                login,
                f'{{#server}}> {{#error}}Invalid game mode {{#highlite}}$i {args[0]}'
            )

    elif sub == 'setrefmode':
        if args and args[0] in ('0', '1'):
            m = int(args[0])
            await aseco.client.query_ignore_result('SetRefereeMode', m)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               f'sets referee mode to {m}!'))
        else:
            m = await aseco.client.query('GetRefereeMode') or 0
            await _reply(aseco, login,
                         f'{{#server}}> Referee mode is {("All" if m == 1 else "Top-3")}')

    # ---- Map navigation ----

    elif sub in ('nextmap', 'next', 'skipmap', 'skip'):
        skipped_jb = None
        jb_selected = False
    
        try:
            from pyxaseco.plugins.plugin_rasp_jukebox import force_jukebox_next, jukebox
    
            if jukebox:
                _uid, skipped_jb = next(iter(jukebox.items()))
                jb_selected = await force_jukebox_next(aseco)
                if not jb_selected:
                    await _reply(
                        aseco,
                        login,
                        '{#server}> {#error}Could not queue the first jukebox track as next challenge.'
                    )
                    return
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}Jukebox skip failed: {e}')
            return
    
        if skipped_jb is not None:
            try:
                await aseco.release_event('onJukeboxChanged', ['skip', skipped_jb])
            except Exception:
                pass
    
        await aseco.client.query_ignore_result('NextChallenge')
        aseco.console('{1} [{2}] forced next challenge', logtitle, login)
        await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle, 'skips to next track!'))

    elif sub in ('previous', 'prev'):
        try:
            from pyxaseco.plugins.plugin_rasp_jukebox import jb_buffer

            if not isinstance(jb_buffer, list) or len(jb_buffer) < 2:
                await _reply(
                    aseco,
                    login,
                    '{#server}> {#error}No previous track in history.'
                )
                return

            current_uid = str(getattr(aseco.server.challenge, 'uid', '') or '').strip()
            prev_uid = ''

            # Walk backward through history and find the most recent entry
            # that is not the currently loaded map.
            for hist_uid in reversed(jb_buffer):
                hist_uid = str(hist_uid or '').strip()
                if not hist_uid:
                    continue
                if hist_uid != current_uid:
                    prev_uid = hist_uid
                    break

            if not prev_uid:
                await _reply(
                    aseco,
                    login,
                    '{#server}> {#error}No previous track in history.'
                )
                return

            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            prev_track = None

            for t in track_list:
                tuid = str(t.get('UId', '') or t.get('Uid', '') or '').strip()
                if tuid == prev_uid:
                    prev_track = t
                    break

            if not prev_track:
                await _reply(
                    aseco,
                    login,
                    '{#server}> {#error}Previous track from history is no longer in the live track list.'
                )
                return

            prev_filename = str(prev_track.get('FileName', '') or '').strip()
            prev_name = strip_colors(prev_track.get('Name', prev_uid))

            if not prev_filename:
                await _reply(
                    aseco,
                    login,
                    '{#server}> {#error}Could not resolve previous track filename.'
                )
                return

            await aseco.client.query_ignore_result('ChooseNextChallenge', prev_filename)
            await aseco.client.query_ignore_result('NextChallenge')

            aseco.console(
                '{1} [{2}] loaded previous track [{3}]',
                logtitle, login, prev_name
            )
            await _broadcast(
                aseco,
                _fmt_admin(aseco, admin, chattitle, 'loads previous track', prev_name)
            )

        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('restartmap', 'restart', 'res'):
        try:
            await aseco.client.query_ignore_result('ChallengeRestart')
            aseco.console('{1} [{2}] restarted challenge', logtitle, login)
            await _broadcast(
                aseco,
                _fmt_admin(aseco, admin, chattitle, 'restarts this track!')
            )
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('replaymap', 'replay'):
        try:
            await aseco.client.query_ignore_result(
                'ChooseNextChallenge',
                aseco.server.challenge.filename
            )
            aseco.console('{1} [{2}] replay queued for current challenge', logtitle, login)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'replays this track after finish!'))
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('dropjukebox', 'djb'):
        try:
            from pyxaseco.plugins.plugin_rasp_jukebox import jukebox
            if not jukebox:
                await _reply(aseco, login, '{#server}> {#error}Jukebox is empty!')
                return
            # Drop by index or first
            if args and args[0].isdigit():
                idx = int(args[0]) - 1
                keys = list(jukebox.keys())
                if 0 <= idx < len(keys):
                    drop = jukebox.pop(keys[idx])
                    name = strip_colors(drop.get('Name', '?'))
                    await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                                       f'drops {name} from jukebox!'))
                    await aseco.release_event('onJukeboxChanged', ['drop', drop])
                else:
                    await _reply(aseco, login, '{#server}> {#error}Track not found in jukebox!')
            else:
                drop_uid, drop = next(iter(jukebox.items()))
                del jukebox[drop_uid]
                await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                                   f'drops {strip_colors(drop.get("Name","?"))} from jukebox!'))
                await aseco.release_event('onJukeboxChanged', ['drop', drop])
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('clearjukebox', 'cjb'):
        try:
            from pyxaseco.plugins.plugin_rasp_jukebox import jukebox
            jukebox.clear()
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'clears the entire jukebox!'))
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'clearhist':
        try:
            from pyxaseco.plugins.plugin_rasp_jukebox import jb_buffer

            buf = jb_buffer
            if not isinstance(buf, list):
                await _reply(aseco, login, '{#server}> {#error}Track history buffer unavailable.')
                return

            raw_arg = arg.strip().lower()
            buf_len = len(buf)

            if raw_arg == '':
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}The track history contains {{#highlite}}{buf_len}{{#message}} track{"s" if buf_len != 1 else ""}.'
                )
                return

            if raw_arg == 'all':
                clear = buf_len
                aseco.console('{1} [{2}] clears entire track history!', logtitle, login)
                await _broadcast(
                    aseco,
                    _fmt_admin(aseco, admin, chattitle, 'clears entire track history!')
                )
            elif raw_arg.lstrip('-').isdigit() and raw_arg != '0':
                clear = int(raw_arg)
                desc = f'newest {abs(clear)}' if clear > 0 else f'oldest {abs(clear)}'
                aseco.console(
                    '{1} [{2}] clears {3} track{4} from history!',
                    logtitle, login, desc, '' if abs(clear) == 1 else 's'
                )
                await _broadcast(
                    aseco,
                    _fmt_admin(
                        aseco, admin, chattitle,
                        f'clears {desc} track{"s" if abs(clear) != 1 else ""} from history!'
                    )
                )
            else:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}The track history contains {{#highlite}}{buf_len}{{#message}} track{"s" if buf_len != 1 else ""}.'
                )
                return

            if clear > 0:
                clear = min(clear, len(buf))
                for _ in range(clear):
                    buf.pop()
            else:
                clear = max(clear, -len(buf))
                for _ in range(abs(clear)):
                    buf.pop(0)

        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    # ---- Vote control ----

    elif sub == 'pass':
        # Force-pass any ongoing vote
        try:
            from pyxaseco.plugins.plugin_rasp_votes import chatvote, tmxadd
            from pyxaseco.plugins.plugin_rasp_jukebox import chat_y
            if chatvote or tmxadd:
                # Set votes to 0 so next /y passes
                if chatvote:
                    chatvote['votes'] = 0
                elif tmxadd:
                    tmxadd['votes'] = 0
                await chat_y(aseco, command)
                aseco.console('{1} [{2}] passed vote', logtitle, login)
            else:
                await _reply(aseco, login, '{#server}> {#error}No vote in progress!')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('cancel', 'can'):
        try:
            from pyxaseco.plugins.plugin_rasp_votes import chatvote, tmxadd
            if chatvote:
                aseco.console('{1} [{2}] cancelled vote', logtitle, login)
                msg = format_text('{#server}>> {#error}Vote cancelled by admin.')
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessage', aseco.format_colors(msg))
                chatvote.clear()
            elif tmxadd:
                tmxadd.clear()
                msg = format_text('{#server}>> {#error}TMX vote cancelled by admin.')
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessage', aseco.format_colors(msg))
            else:
                await _reply(aseco, login, '{#server}> {#error}No vote in progress!')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('endround', 'er'):
        await aseco.client.query_ignore_result('ForceEndRound')
        aseco.console('{1} [{2}] forced end of round', logtitle, login)
        await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                           'forces end of current round!'))

    # ---- Player moderation ----

    elif sub == 'warn':
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return

            msg = format_text(
                '{#server}>> {#error}Warning: {#highlite}{1}$z$s{#error} - you risk being kicked or banned!',
                strip_colors(target.nickname)
            )
            await aseco.client.query_ignore_result(
                'ChatSendServerMessage', aseco.format_colors(msg)
            )
            aseco.console('{1} [{2}] warned [{3}]', logtitle, login, target.login)

    elif sub == 'kick':
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return

            aseco.console('{1} [{2}] kicked [{3}]', logtitle, login, target.login)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'kicks', strip_colors(target.nickname)))
            await aseco.client.query_ignore_result('Kick', target.login)

    elif sub == 'kickghost':
        target_login = arg.strip()
        if target_login:
            if not _can_target_login(aseco, admin, target_login):
                await _deny_protected_target(aseco, admin, target_login)
                return
            try:
                await aseco.client.query_ignore_result('Kick', target_login)
                aseco.console('{1} [{2}] kicked ghost [{3}]', logtitle, login, target_login)
                await _reply(aseco, login, f'{{#server}}> Kicked ghost: {{#highlite}}{target_login}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'ban':
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return

            aseco.console('{1} [{2}] banned [{3}]', logtitle, login, target.login)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'bans', strip_colors(target.nickname)))
            await aseco.client.query_ignore_result('Ban', target.login)

    elif sub == 'unban':
        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not _can_target_login(aseco, admin, target.login):
                await _deny_protected_target(aseco, admin, target.login)
                return
            try:
                await aseco.client.query_ignore_result('UnBan', target.login)
                aseco.console('{1} [{2}] unbanned [{3}]', logtitle, login, target.login)
                await _reply(aseco, login,
                             f'{{#server}}> Unbanned: {{#highlite}}{target.login}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'banip':
        ip = arg.strip()
        if ip:
            try:
                await aseco.client.query_ignore_result('BanIP', ip)
                await aseco.client.query_ignore_result('SaveBannedIPs', 'bannedips.xml')
                aseco.console('{1} [{2}] banned IP [{3}]', logtitle, login, ip)
                await _reply(aseco, login, f'{{#server}}> Banned IP: {{#highlite}}{ip}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'unbanip':
        ip = arg.strip()
        if ip:
            try:
                await aseco.client.query_ignore_result('UnBanIP', ip)
                await aseco.client.query_ignore_result('SaveBannedIPs', 'bannedips.xml')
                aseco.console('{1} [{2}] unbanned IP [{3}]', logtitle, login, ip)
                await _reply(aseco, login, f'{{#server}}> Unbanned IP: {{#highlite}}{ip}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'black':
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return

            try:
                await aseco.client.query_ignore_result('BlackList', target.login)
                await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
                aseco.console('{1} [{2}] blacklisted [{3}]', logtitle, login, target.login)
                await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                                   'blacklists', strip_colors(target.nickname)))
                await aseco.client.query_ignore_result('Kick', target.login)
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'unblack':
        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not _can_target_login(aseco, admin, target.login):
                await _deny_protected_target(aseco, admin, target.login)
                return
            try:
                await aseco.client.query_ignore_result('UnBlackList', target.login)
                await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
                aseco.console('{1} [{2}] unblacklisted [{3}]', logtitle, login, target.login)
                await _reply(aseco, login,
                             f'{{#server}}> UnBlacklisted: {{#highlite}}{target.login}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'addguest':
        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not _can_target_login(aseco, admin, target.login):
                await _deny_protected_target(aseco, admin, target.login)
                return
            try:
                await aseco.client.query_ignore_result('AddGuest', target.login)
                await aseco.client.query_ignore_result('SaveGuestList', 'guestlist.txt')
                aseco.console('{1} [{2}] added guest [{3}]', logtitle, login, target.login)
                await _reply(aseco, login,
                             f'{{#server}}> Added guest: {{#highlite}}{target.login}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'removeguest':
        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not _can_target_login(aseco, admin, target.login):
                await _deny_protected_target(aseco, admin, target.login)
                return
            try:
                await aseco.client.query_ignore_result('RemoveGuest', target.login)
                await aseco.client.query_ignore_result('SaveGuestList', 'guestlist.txt')
                aseco.console('{1} [{2}] removed guest [{3}]', logtitle, login, target.login)
                await _reply(aseco, login,
                             f'{{#server}}> Removed guest: {{#highlite}}{target.login}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('mute', 'ignore'):
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return

            try:
                await aseco.client.query_ignore_result('Ignore', target.login)
                if target.login not in aseco.server.mutelist:
                    aseco.server.mutelist.append(target.login)
                aseco.console('{1} [{2}] muted [{3}]', logtitle, login, target.login)
                await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                                   'mutes', strip_colors(target.nickname)))
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('unmute', 'unignore'):
        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not _can_target_login(aseco, admin, target.login):
                await _deny_protected_target(aseco, admin, target.login)
                return

            try:
                await aseco.client.query_ignore_result('UnIgnore', target.login)
                if target.login in aseco.server.mutelist:
                    aseco.server.mutelist.remove(target.login)
                aseco.console('{1} [{2}] unmuted [{3}]', logtitle, login, target.login)
                await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                                   'unmutes', target.login))
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('mutelist', 'listmutes', 'ignorelist', 'listignores'):
        ml = list(getattr(aseco.server, 'mutelist', []))
        if ml:
            admin.playerlist = [{'login': lgn, 'nickname': lgn} for lgn in ml]
            header = 'Global Mute/Ignore List:'
            rows = [['#', 'Login', 'Action']]
            for i, lgn in enumerate(ml, 1):
                action = f'$l[{ML_LIST_UNIGNORE_BASE + i}]{{#highlite}}UNMUTE$l'
                rows.append([f'{i:02d}.', lgn, action])
            display_manialink(
                aseco, login, header,
                ['Icons64x64_1', 'NotBuddy'],
                rows, [0.10, 0.65, 0.25], 'OK'
            )
        else:
            await _reply(aseco, login, '{#server}> Mute list is empty.')

    elif sub in ('cleanmutes', 'cleanignores'):
        aseco.server.mutelist = []
        await _reply(aseco, login, '{#server}> Mute list cleared.')

    # ---- Track list management ----

    elif sub in ('writetracklist',):
        await _reply(aseco, login,
                     '{#server}> MatchSettings.txt is maintained automatically.')

    elif sub == 'readtracklist':
        try:
            await aseco.client.query_ignore_result('LoadMatchSettings', 'MatchSettings/MatchSettings.txt')
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'reloads track list!'))
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('shuffle', 'shufflemaps'):
        try:
            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            import random
            random.shuffle(track_list)
            file_names = [t['FileName'] for t in track_list]
            await aseco.client.query_ignore_result('SetChallengeList', file_names)
            aseco.console('{1} [{2}] shuffled track list', logtitle, login)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'shuffles track list!'))
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'erase' and arg:
        try:
            if arg.strip().isdigit() and hasattr(admin, 'tracklist'):
                idx = int(arg.strip()) - 1
                if not (0 <= idx < len(admin.tracklist)):
                    await _reply(aseco, login, '{#server}> {#error}Track index out of range.')
                    return
                fname = admin.tracklist[idx].get('filename', '')
            else:
                fname = arg.strip()

            if not fname:
                await _reply(aseco, login, '{#server}> {#error}Missing track filename.')
                return

            uid = await _find_track_uid_by_filename(aseco, fname)

            await _remove_track_from_rotation(aseco, fname, uid)
            await _erase_track_from_localdb(aseco, uid)

            try:
                gbx_path = _resolve_track_path(aseco, fname)
                if gbx_path.exists():
                    gbx_path.unlink()
            except Exception as e:
                aseco.console('[Admin] erase file warning: {1}', str(e))

            aseco.console('{1} [{2}] erased track [{3}]', logtitle, login, fname)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'erases track', fname))
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('removethis', 'rt'):
        fname = aseco.server.challenge.filename
        uid = aseco.server.challenge.uid
        try:
            await _remove_track_from_rotation(aseco, fname, uid)

            aseco.console('{1} [{2}] removed current track', logtitle, login)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'removes current track from rotation!'))
            await aseco.client.query_ignore_result('NextChallenge')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'erasethis':
        fname = aseco.server.challenge.filename
        uid = getattr(aseco.server.challenge, 'uid', '')
        try:
            await _remove_track_from_rotation(aseco, fname, uid)
            await _erase_track_from_localdb(aseco, uid)

            try:
                gbx_path = _resolve_track_path(aseco, fname)
                if gbx_path.exists():
                    gbx_path.unlink()
            except Exception as e:
                aseco.console('[Admin] erasethis file warning: {1}', str(e))

            aseco.console('{1} [{2}] erased current track', logtitle, login)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'erases current track!'))
            await aseco.client.query_ignore_result('NextChallenge')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'remove' and arg:
        try:
            if arg.strip().isdigit() and hasattr(admin, 'tracklist'):
                idx = int(arg.strip()) - 1
                if not (0 <= idx < len(admin.tracklist)):
                    await _reply(aseco, login, '{#server}> {#error}Track index out of range.')
                    return
                fname = admin.tracklist[idx].get('filename', '')
                uid   = admin.tracklist[idx].get('uid', '')
            else:
                fname = arg.strip()
                uid = await _find_track_uid_by_filename(aseco, fname)

            if not fname:
                await _reply(aseco, login, '{#server}> {#error}Missing track filename.')
                return

            if not uid:
                uid = await _find_track_uid_by_filename(aseco, fname)

            await _remove_track_from_rotation(aseco, fname, uid)

            aseco.console('{1} [{2}] removed track [{3}]', logtitle, login, fname)
            await _broadcast(aseco, _fmt_admin(aseco, admin, chattitle,
                                               'removes track', fname))
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'nextenv':
        try:
            env = aseco.server.challenge.environment
            track_list = await aseco.client.query('GetChallengeList', 5000, 0) or []
            for t in track_list:
                if t.get('Environnement', '') == env and t['FileName'] != aseco.server.challenge.filename:
                    await aseco.client.query_ignore_result('SetNextChallengeList', [t])
                    await aseco.client.query_ignore_result('NextChallenge')
                    await _reply(aseco, login,
                                 f'{{#server}}> Next env track: {{#highlite}}{t.get("Name", "?")}')
                    return
            await _reply(aseco, login, f'{{#server}}> {{#error}}No other {env} tracks found.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    # ---- List commands ----

    elif sub == 'players':
        online = aseco.server.players.all()
        if not online:
            await _reply(aseco, login, '{#server}> {#error}No players online.')
            return
    
        admin.playerlist = [{'login': p.login, 'nickname': p.nickname} for p in online]

        def _action_cell(label: str, action_id: int | None):
            if action_id is None:
                return label
            return [label, action_id]
    
        rows = [[
            'Id',
            '{#nick}Nick $g/{#login} Login',
            'Warn',
            'Ignore',
            'Kick',
            'Ban',
            'Black',
            'Guest',
            'Spec',
        ]]
    
        muted = {
            str(x).strip().lower()
            for x in (getattr(aseco.server, 'mutelist', []) or [])
        }

        try:
            black_entries = await aseco.client.query('GetBlackList', 300, 0) or []
        except Exception:
            black_entries = []

        try:
            guest_entries = await aseco.client.query('GetGuestList', 300, 0) or []
        except Exception:
            guest_entries = []

        black_logins = {
            str(b.get('Login', '')).strip().lower()
            for b in black_entries if isinstance(b, dict)
        }
        guest_logins = {
            str(g.get('Login', '')).strip().lower()
            for g in guest_entries if isinstance(g, dict)
        }

        for i, pl in enumerate(online, 1):
            login_l = pl.login.lower()

            ignore_cell = (
                _action_cell('$f93Unignore', ML_UNIGNORE_BASE + i)
                if login_l in muted
                else _action_cell('$f93Ignore', ML_IGNORE_BASE + i)
            )

            black_cell = (
                _action_cell('$f03Unblack', ML_UNBLACK_BASE + i)
                if login_l in black_logins
                else _action_cell('$f03Black', ML_BLACK_BASE + i)
            )

            guest_cell = (
                _action_cell('$3c3Remove', ML_REMOVEGUEST_BASE + i)
                if login_l in guest_logins
                else _action_cell('$3c3Add', ML_ADDGUEST_BASE + i)
            )

            spec_cell = (
                '$09cSpec'
                if getattr(pl, 'isspectator', False)
                else _action_cell('$09fForce', ML_FORCESPEC_BASE + i)
            )

            rows.append([
                f'{i:02d}.',
                f'{{#black}}{strip_colors(pl.nickname)}$z / {{#login}}{pl.login}',
                _action_cell('$ff3Warn', ML_WARN_BASE + i),
                ignore_cell,
                _action_cell('$c3fKick', ML_KICK_BASE + i),
                _action_cell('$f30Ban', ML_BAN_BASE + i),
                black_cell,
                guest_cell,
                spec_cell,
            ])
    
        pages = [rows[k:k+15] for k in range(0, len(rows), 15)]
        admin.msgs = [[
            1,
            'Current Players:',
            [1.49, 0.15, 0.5, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
            ['Icons128x128_1', 'Buddies']
        ]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub in ('showbanlist', 'listbans'):
        try:
            bans = await aseco.client.query('GetBanList', 100, 0) or []
            if bans:
                admin.playerlist = [
                    {'login': b.get('Login', ''), 'nickname': b.get('NickName', '')}
                    for b in bans
                ]
                header = 'Current Ban List:'
                rows = [['#', 'Login', 'Nick', 'Action']]
                for i, b in enumerate(bans, 1):
                    rows.append([
                        f'{i:02d}.',
                        b.get('Login', ''),
                        strip_colors(b.get('NickName', '')),
                        f'$l[{ML_LIST_UNBAN_BASE + i}]{{#highlite}}UNBAN$l'
                    ])
                display_manialink(
                    aseco, login, header,
                    ['Icons64x64_1', 'NotBuddy'],
                    rows, [0.10, 0.38, 0.34, 0.18], 'OK'
                )
            else:
                await _reply(aseco, login, '{#server}> Ban list is empty.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('showblacklist', 'listblacks'):
        try:
            bl = await aseco.client.query('GetBlackList', 100, 0) or []
            if bl:
                admin.playerlist = [
                    {'login': b.get('Login', ''), 'nickname': b.get('NickName', '')}
                    for b in bl
                ]
                header = 'Current Black List:'
                rows = [['#', 'Login', 'Nick', 'Action']]
                for i, b in enumerate(bl, 1):
                    rows.append([
                        f'{i:02d}.',
                        b.get('Login', ''),
                        strip_colors(b.get('NickName', '')),
                        f'$l[{ML_LIST_UNBLACK_BASE + i}]{{#highlite}}UNBLACK$l'
                    ])
                display_manialink(
                    aseco, login, header,
                    ['Icons64x64_1', 'NotBuddy'],
                    rows, [0.10, 0.38, 0.34, 0.18], 'OK'
                )
            else:
                await _reply(aseco, login, '{#server}> Black list is empty.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('showiplist', 'listips'):
        try:
            ips = await aseco.client.query('GetBannedIPs') or []
            if ips:
                admin.iplist = list(ips)
                header = 'Banned IPs:'
                rows = [['#', 'IP Address', 'Action']]
                for i, ip in enumerate(ips, 1):
                    rows.append([
                        f'{i:02d}.',
                        ip,
                        f'$l[{ML_UNBANIP_NEG_BASE - i}]{{#highlite}}UNBAN$l'
                    ])
                display_manialink(
                    aseco, login, header,
                    ['Icons64x64_1', 'NotBuddy'],
                    rows, [0.10, 0.65, 0.25], 'OK'
                )
            else:
                await _reply(aseco, login, '{#server}> No banned IPs.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('showguestlist', 'listguests'):
        try:
            gl = await aseco.client.query('GetGuestList', 100, 0) or []
            if gl:
                admin.playerlist = [
                    {'login': g.get('Login', ''), 'nickname': g.get('NickName', '')}
                    for g in gl
                ]
                header = 'Current Guest List:'
                rows = [['#', 'Login', 'Nick', 'Action']]
                for i, g in enumerate(gl, 1):
                    rows.append([
                        f'{i:02d}.',
                        g.get('Login', ''),
                        strip_colors(g.get('NickName', '')),
                        f'$l[{ML_LIST_REMOVEGUEST_BASE + i}]{{#highlite}}REMOVE$l'
                    ])
                display_manialink(
                    aseco, login, header,
                    ['Icons128x128_1', 'Invite'],
                    rows, [0.10, 0.38, 0.34, 0.18], 'OK'
                )
            else:
                await _reply(aseco, login, '{#server}> Guest list is empty.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('cleanbanlist',):
        try:
            await aseco.client.query_ignore_result('CleanBanList')
            await _reply(aseco, login, '{#server}> Ban list cleaned.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('cleaniplist',):
        try:
            await aseco.client.query_ignore_result('CleanBannedIPs')
            await _reply(aseco, login, '{#server}> Banned IPs list cleaned.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('cleanblacklist',):
        try:
            await aseco.client.query_ignore_result('CleanBlackList')
            await _reply(aseco, login, '{#server}> Black list cleaned.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('cleanguestlist',):
        try:
            await aseco.client.query_ignore_result('CleanGuestList')
            await _reply(aseco, login, '{#server}> Guest list cleaned.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('writeblacklist',):
        try:
            await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
            await _reply(aseco, login, '{#server}> Black list saved.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('readblacklist',):
        try:
            await aseco.client.query_ignore_result('LoadBlackList', 'blacklist.txt')
            await _reply(aseco, login, '{#server}> Black list loaded.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('writeguestlist',):
        try:
            await aseco.client.query_ignore_result('SaveGuestList', 'guestlist.txt')
            await _reply(aseco, login, '{#server}> Guest list saved.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('readguestlist',):
        try:
            await aseco.client.query_ignore_result('LoadGuestList', 'guestlist.txt')
            await _reply(aseco, login, '{#server}> Guest list loaded.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('writeiplist',):
        try:
            await aseco.client.query_ignore_result('SaveBannedIPs', 'bannedips.xml')
            await _reply(aseco, login, '{#server}> Banned IPs list saved.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('readiplist',):
        try:
            await aseco.client.query_ignore_result('LoadBannedIPs', 'bannedips.xml')
            await _reply(aseco, login, '{#server}> Banned IPs list loaded.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    # ---- Admin / operator management ----

    elif sub == 'addadmin':
        if not _is_masteradmin_player(aseco, admin):
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only MasterAdmins may add admins.'
            )
            return

        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if _role_level(aseco, target.login) >= 3:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Cannot add {{#highlite}}{target.login}{{#error}} as Admin because this login is already a MasterAdmin.'
                )
                return

            admins = aseco.settings.admin_list.get('TMLOGIN', [])
            ops = aseco.settings.operator_list.get('TMLOGIN', [])

            changed = False

            if target.login not in admins:
                admins.append(target.login)
                aseco.settings.admin_list['TMLOGIN'] = admins
                changed = True

            if target.login in ops:
                ops.remove(target.login)
                aseco.settings.operator_list['TMLOGIN'] = ops
                changed = True

            if changed:
                _write_adminops_xml(aseco)

            aseco.console('{1} [{2}] added admin [{3}]', logtitle, login, target.login)
            target_name = await _admin_display_name(aseco, target.login)
            await _reply(
                aseco,
                login,
                f'{{#server}}> Added admin: {{#highlite}}{target_name}'
            )

    elif sub == 'removeadmin':
        if not _is_masteradmin_player(aseco, admin):
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only MasterAdmins may remove admins.'
            )
            return

        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            admins = aseco.settings.admin_list.get('TMLOGIN', [])
            removed = False

            if target.login in admins:
                admins.remove(target.login)
                aseco.settings.admin_list['TMLOGIN'] = admins
                removed = True

            if removed:
                _write_adminops_xml(aseco)
                aseco.console('{1} [{2}] removed admin [{3}]', logtitle, login, target.login)
                target_name = await _admin_display_name(aseco, target.login)
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> Removed admin: {{#highlite}}{target_name}'
                )
            else:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Login is not an admin: {{#highlite}}{target.login}'
                )

    elif sub == 'addop':
        if _viewer_role_level(aseco, admin) < 2:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only Admins or MasterAdmins may add operators.'
            )
            return

        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            target_level = _role_level(aseco, target.login)
            if target_level >= 2:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Cannot add {{#highlite}}{target.login}{{#error}} as Operator because this login is already Admin or MasterAdmin.'
                )
                return

            ops = aseco.settings.operator_list.get('TMLOGIN', [])
            if target.login not in ops:
                ops.append(target.login)
                aseco.settings.operator_list['TMLOGIN'] = ops
                _write_adminops_xml(aseco)

            aseco.console('{1} [{2}] added operator [{3}]', logtitle, login, target.login)
            target_name = await _admin_display_name(aseco, target.login)
            await _reply(
                aseco,
                login,
                f'{{#server}}> Added operator: {{#highlite}}{target_name}'
            )

    elif sub == 'removeop':
        if _viewer_role_level(aseco, admin) < 2:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only Admins or MasterAdmins may remove operators.'
            )
            return

        target = await _get_player_param(aseco, admin, arg, offline=True)
        if target:
            if _viewer_role_level(aseco, admin) < 3 and _role_level(aseco, target.login) >= 2:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Cannot remove operator access from {{#highlite}}{target.login}{{#error}} because this login is Admin or MasterAdmin.'
                )
                return

            ops = aseco.settings.operator_list.get('TMLOGIN', [])
            removed = False

            if target.login in ops:
                ops.remove(target.login)
                aseco.settings.operator_list['TMLOGIN'] = ops
                removed = True

            if removed:
                _write_adminops_xml(aseco)
                aseco.console('{1} [{2}] removed operator [{3}]', logtitle, login, target.login)
                target_name = await _admin_display_name(aseco, target.login)
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> Removed operator: {{#highlite}}{target_name}'
                )
            else:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Login is not an operator: {{#highlite}}{target.login}'
                )

    elif sub == 'listmasters':
        masters = aseco.settings.masteradmin_list.get('TMLOGIN', [])
        master_names = await _admin_display_names(aseco, masters)
        await _reply(aseco, login,
                     '{#server}> MasterAdmins: ' +
                     ', '.join(f'{{#highlite}}{m}{{#message}}' for m in master_names))

    elif sub == 'listadmins':
        admins = aseco.settings.admin_list.get('TMLOGIN', [])
        admin_names = await _admin_display_names(aseco, admins)
        await _reply(aseco, login,
                     '{#server}> Admins: ' +
                     ', '.join(f'{{#highlite}}{a}{{#message}}' for a in admin_names))

    elif sub == 'listops':
        ops = aseco.settings.operator_list.get('TMLOGIN', [])
        op_names = await _admin_display_names(aseco, ops)
        await _reply(aseco, login,
                     '{#server}> Operators: ' +
                     ', '.join(f'{{#highlite}}{o}{{#message}}' for o in op_names))

    elif sub == 'adminability':
        if not _is_masteradmin_player(aseco, admin):
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only MasterAdmins may change admin abilities.'
            )
            return

        if not args:
            await _reply(
                aseco,
                login,
                '{#server}> Usage: {#highlite}/admin adminability <command> [ON|OFF]'
            )
        else:
            ability = args[0].lower().lstrip('/')
            if len(args) >= 2 and args[1].upper() in ('ON', 'OFF'):
                enabled = args[1].upper() == 'ON'
                _set_ability_enabled(aseco, 'admin', ability, enabled)
                _write_adminops_xml(aseco)
                aseco.console(
                    '{1} [{2}] set admin ability [{3}] = {4}',
                    logtitle, login, ability, 'ON' if enabled else 'OFF'
                )
                await _broadcast(
                    aseco,
                    _fmt_admin(
                        aseco,
                        admin,
                        chattitle,
                        f'sets admin ability {ability} to {"ON" if enabled else "OFF"}!'
                    )
                )
            else:
                state = 'ON' if _ability_enabled(aseco, 'admin', ability) else 'OFF'
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> Admin ability {{#highlite}}{ability}{{#message}} is {{#highlite}}{state}'
                )

    elif sub == 'opability':
        if not _is_masteradmin_player(aseco, admin):
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only MasterAdmins may change operator abilities.'
            )
            return

        if not args:
            await _reply(
                aseco,
                login,
                '{#server}> Usage: {#highlite}/admin opability <command> [ON|OFF]'
            )
        else:
            ability = args[0].lower().lstrip('/')
            if len(args) >= 2 and args[1].upper() in ('ON', 'OFF'):
                enabled = args[1].upper() == 'ON'
                _set_ability_enabled(aseco, 'op', ability, enabled)
                _write_adminops_xml(aseco)
                aseco.console(
                    '{1} [{2}] set operator ability [{3}] = {4}',
                    logtitle, login, ability, 'ON' if enabled else 'OFF'
                )
                await _broadcast(
                    aseco,
                    _fmt_admin(
                        aseco,
                        admin,
                        chattitle,
                        f'sets operator ability {ability} to {"ON" if enabled else "OFF"}!'
                    )
                )
            else:
                state = 'ON' if _ability_enabled(aseco, 'op', ability) else 'OFF'
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> Operator ability {{#highlite}}{ability}{{#message}} is {{#highlite}}{state}'
                )

    elif sub == 'listabilities':
        rows = _ability_rows(aseco)
        pages = [rows[i:i+14] for i in range(0, max(len(rows), 1), 14)]
        admin.msgs = [[
            1,
            'Admin / Operator abilities:',
            [1.2, 0.45, 0.25, 0.25],
            ['Icons128x128_1', 'ProfileAdvanced', 0.02]
        ]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub == 'writeabilities':
        if _viewer_role_level(aseco, admin) < 2:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only Admins or MasterAdmins may write abilities.'
            )
            return

        path = _write_adminops_xml(aseco)
        if path:
            await _reply(
                aseco,
                login,
                f'{{#server}}> Abilities saved to {{#highlite}}{path.name}'
            )
        else:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Could not save abilities.'
            )

    elif sub == 'readabilities':
        if _viewer_role_level(aseco, admin) < 2:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Only Admins or MasterAdmins may read abilities.'
            )
            return

        ok = _read_adminops_xml(aseco)
        if ok:
            await _reply(
                aseco,
                login,
                '{#server}> Abilities loaded from {#highlite}adminops.xml'
            )
        else:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Could not load abilities.'
            )

    elif sub == 'access':
        if not args:
            await _reply(
                aseco,
                login,
                '{#server}> Usage: {#highlite}/admin access <player/login/id>'
            )
        else:
            target_login = _find_player_login_by_id_or_name(aseco, admin, args[0])
            if not target_login:
                await _reply(aseco, login, '{#server}> {#error}Player not found.')
            else:
                is_master = target_login in aseco.settings.masteradmin_list.get('TMLOGIN', [])
                is_admin_ = target_login in aseco.settings.admin_list.get('TMLOGIN', [])
                is_op     = target_login in aseco.settings.operator_list.get('TMLOGIN', [])
                is_muted  = target_login in getattr(aseco.server, 'mutelist', [])

                guest_list = []
                black_list = []
                try:
                    guest_list = await aseco.client.query('GetGuestList', 300, 0) or []
                except Exception:
                    pass
                try:
                    black_list = await aseco.client.query('GetBlackList', 300, 0) or []
                except Exception:
                    pass

                is_guest = any(g.get('Login', '') == target_login for g in guest_list if isinstance(g, dict))
                is_black = any(b.get('Login', '') == target_login for b in black_list if isinstance(b, dict))

                header = f'Access for {target_login}:'
                rows = [
                    ['MasterAdmin', '{#green}YES' if is_master else '{#error}NO'],
                    ['Admin',       '{#green}YES' if is_admin_ else '{#error}NO'],
                    ['Operator',    '{#green}YES' if is_op else '{#error}NO'],
                    ['Guest',       '{#green}YES' if is_guest else '{#error}NO'],
                    ['Blacklisted', '{#green}YES' if is_black else '{#error}NO'],
                    ['Muted',       '{#green}YES' if is_muted else '{#error}NO'],
                ]
                display_manialink(
                    aseco, login, header,
                    ['Icons128x128_1', 'ProfileAdvanced', 0.02],
                    rows, [0.9, 0.4, 0.5], 'OK'
                )

    elif sub == 'add':
        # /admin add <id1> [id2] ... [tmnf|tmu|tmo|tms|tmn]
        # Add permanently via AddChallenge and optionally queue it for the jukebox.
        if not args:
            await _reply(aseco, login,
                         '{#server}> {#error}Usage: {#highlite}/admin add <TMX_ID>... [tmnf|tmu|...]')
            return

        # Detect optional section suffix
        sections = {'tmnf', 'tmu', 'tmo', 'tms', 'tmn'}
        source_hint = ''
        track_ids   = []
        for a in args:
            if a.lower() in sections:
                source_hint = a.lower()
            elif a.isdigit():
                track_ids.append(a)
            else:
                await _reply(aseco, login,
                             f'{{#server}}> {{#highlite}}{a}{{#error}} is not a valid TMX Track_ID!')

        if not track_ids:
            await _reply(aseco, login, '{#server}> {#error}You must include a TMX Track_ID!')
            return

        # jukebox_adminadd defaults to enabled when not configured elsewhere.
        jukebox_adminadd = True

        for trkid in track_ids:
            try:
                from pyxaseco.plugins.plugin_rasp_jukebox import (
                    admin_add_tmx_track, jukebox as _jb
                )
                ok, info = await admin_add_tmx_track(
                    aseco, trkid, login, source_hint,
                    use_add_challenge=True  # Keep the track in the permanent rotation.
                )

                if ok:
                    track_name = info  # display name returned by admin_add_tmx_track
                    aseco.console('{1} [{2}] adds track "{3}" from TMX!',
                                  logtitle, login, track_name)

                    # Jukebox the added track if enabled
                    jb_phrase = ''
                    if jukebox_adminadd:
                        # Find the track in jukebox (admin_add_tmx_track adds it)
                        jb_phrase = '& jukeboxes '

                    msg = format_text(
                        '{#server}>> {#admin}{1}$z$s {#highlite}{2}$z$s '
                        '{#admin}adds {3}track: {#highlite}{4} {#admin}from TMX',
                        chattitle, admin.nickname, jb_phrase, track_name
                    )
                    await _broadcast(aseco, msg)
                else:
                    await _reply(aseco, login,
                                 f'{{#server}}> {{#error}}Could not add {trkid}: {info}')
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'addthis':
        try:
            # If the current track came from a temporary TMX add, move it to the permanent list.
            from pyxaseco.plugins.plugin_rasp_jukebox import tmxplayed
        except Exception:
            tmxplayed = None

        try:
            if not tmxplayed:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Current track {{#highlite}}$i {strip_colors(aseco.server.challenge.name)} {{#error}}already permanently in track list!'
                )
                return

            try:
                from pyxaseco.plugins.plugin_rasp_jukebox import (
                    _matchsettings_path, _ensure_matchsettings_entry
                )
            except Exception:
                _matchsettings_path = None
                _ensure_matchsettings_entry = None

            filename = aseco.server.challenge.filename
            uid = getattr(aseco.server.challenge, 'uid', '')

            if _matchsettings_path and _ensure_matchsettings_entry and uid:
                await asyncio.to_thread(
                    _ensure_matchsettings_entry,
                    _matchsettings_path(aseco),
                    filename,
                    uid
                )

            try:
                import pyxaseco.plugins.plugin_rasp_jukebox as rasp_jukebox_mod
                rasp_jukebox_mod.tmxplayed = False
            except Exception:
                pass

            await aseco.release_event('onTracklistChanged', ['rename', filename])

            aseco.console(
                '{1} [{2}] permanently adds current track [{3}]',
                logtitle, login, strip_colors(aseco.server.challenge.name)
            )
            await _broadcast(
                aseco,
                _fmt_admin(
                    aseco, admin, chattitle,
                    'permanently adds current track:',
                    strip_colors(aseco.server.challenge.name)
                )
            )
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'addlocal':
        if arg:
            try:
                rel_insert = arg.strip()
    
                await aseco.client.query_ignore_result('InsertChallenge', rel_insert)
                await aseco.release_event('onTracklistChanged', ['add', rel_insert])
    
                try:
                    from pyxaseco.plugins.plugin_rasp_jukebox import (
                        _parse_gbx_metadata, _matchsettings_path, _ensure_matchsettings_entry
                    )
    
                    gbx_path = (
                        aseco._base_dir.parent / 'GameData' / 'Tracks' / rel_insert
                    ).resolve()
    
                    metadata = await asyncio.to_thread(_parse_gbx_metadata, gbx_path)
                    uid = metadata.get('uid', '').strip()
    
                    if uid:
                        # Update MatchSettings.txt FIRST
                        await asyncio.to_thread(
                            _ensure_matchsettings_entry,
                            _matchsettings_path(aseco),
                            rel_insert,
                            uid
                        )
    
                        # Sync LocalDB
                        from pyxaseco.plugins.plugin_localdatabase import get_pool
                        pool = await get_pool()
                        if pool:
                            async with pool.acquire() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        'INSERT INTO challenges (Uid, Name, Author, Environment) '
                                        'VALUES (%s, %s, %s, %s) '
                                        'ON DUPLICATE KEY UPDATE Name=VALUES(Name), Author=VALUES(Author), Environment=VALUES(Environment)',
                                        (
                                            uid,
                                            metadata.get('name', ''),
                                            metadata.get('author', ''),
                                            metadata.get('environment', '')
                                        )
                                    )
    
                        # Reload tracklist from MatchSettings.txt
                        try:
                            await aseco.client.query_ignore_result(
                                'LoadMatchSettings',
                                'MatchSettings/MatchSettings.txt'
                            )
                        except Exception as e:
                            aseco.console('[Admin] addlocal reload warning: {1}', str(e))
    
                except Exception as e:
                    aseco.console('[Admin] addlocal post-sync warning: {1}', str(e))
    
                await _reply(aseco, login,
                            f'{{#server}}> Added local track: {{#highlite}}{rel_insert}')
    
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'listdupes':
        try:
            tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
            names: dict = {}
            dupes = []
            for t in tracks:
                n = t.get('Name', '')
                if n in names:
                    dupes.append(n)
                else:
                    names[n] = True
            if dupes:
                header = 'Duplicate tracks:'
                rows = [[f'{i+1:02d}.', strip_colors(n)] for i, n in enumerate(dupes)]
                display_manialink(aseco, login, header,
                                  ['Icons64x64_1', 'TrackInfo', -0.01],
                                  rows, [0.8, 0.1, 0.7], 'OK')
            else:
                await _reply(aseco, login, '{#server}> No duplicate tracks found.')
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub in ('wall', 'mta'):
        if not arg.strip():
            await _reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin wall <message>')
        else:
            await _broadcast(aseco, arg.strip())
            aseco.console('{1} [{2}] wall: {3}', logtitle, login, arg.strip())

    elif sub == 'rpoints':
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_rpoints.admin_rpoints',
            aseco, admin, logtitle, chattitle, arg.strip(),
            unavailable_msg='{#server}> {#admin}Custom Rounds points unavailable - include plugin_rpoints.py'
        )

    elif sub == 'match':
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_matchsave.admin_match',
            aseco, admin, logtitle, chattitle, arg.strip(),
            unavailable_msg='{#server}> {#admin}Match tracking unavailable - include plugin_matchsave.py'
        )

    elif sub == 'panel':
        panel_command = {
            'author': admin,
            'command': 'admin',
            'params': arg.strip(),
        }
    
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_panels.admin_panel',
            aseco, panel_command,
            unavailable_msg='{#server}> {#admin}Panel command unavailable - include plugin_panels.py'
        )

    elif sub in ('style', 'admpanel', 'donpanel', 'recpanel', 'votepanel'):
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_panels.chat_panel_pref',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Panel preferences unavailable - include plugin_panels.py'
        )

    elif sub == 'acdl':
        state = _get_bool_on_off(arg)
        try:
            if state is None:
                enabled = await aseco.client.query('IsChallengeDownloadAllowed')
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#admin}}AllowChallengeDownload is currently {"Enabled" if enabled else "Disabled"}'
                )
            else:
                await aseco.client.query_ignore_result('AllowChallengeDownload', state)
                aseco.console('{1} [{2}] set AllowChallengeDownload {3} !', logtitle, login, 'ON' if state else 'OFF')
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#admin}}AllowChallengeDownload set to {"Enabled" if state else "Disabled"}'
                )
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'autotime':
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_autotime.admin_autotime',
            aseco, admin, logtitle, chattitle, arg.strip(),
            unavailable_msg='{#server}> {#admin}Auto TimeLimit unavailable - include plugin_autotime.py'
        )

    elif sub == 'scorepanel':
        state = _get_bool_on_off(arg)
        global AUTO_SCOREPANEL
        if state is None:
            await _reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Automatic scorepanel is currently {"Enabled" if AUTO_SCOREPANEL else "Disabled"}'
            )
        else:
            AUTO_SCOREPANEL = state
            await _reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Automatic scorepanel set to {"Enabled" if state else "Disabled"}'
            )

    elif sub == 'roundsfinish':
        state = _get_bool_on_off(arg)
        global ROUNDS_FINISHPANEL
        if state is None:
            await _reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Rounds finish panel is currently {"Enabled" if ROUNDS_FINISHPANEL else "Disabled"}'
            )
        else:
            ROUNDS_FINISHPANEL = state
            await _reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Rounds finish panel set to {"Enabled" if state else "Disabled"}'
            )

    elif sub in ('delrec', 'prunerecs'):
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_records_eyepiece.chat_admin_records',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Record admin commands unavailable - include plugin_records_eyepiece.py'
        )

    elif sub == 'forcespec':
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return
            try:
                await aseco.client.query_ignore_result('ForceSpectator', target.login, 1)
                await aseco.client.query_ignore_result('ForceSpectator', target.login, 0)
                await aseco.client.query_ignore_result('ForceSpectatorTarget', target.login, '', 2)
                aseco.console('{1} [{2}] forced spectator [{3}]', logtitle, login, target.login)
                await _broadcast(
                    aseco,
                    _fmt_admin(aseco, admin, chattitle,
                               'forces to spectator', strip_colors(target.nickname))
                )
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'specfree':
        target = await _get_player_param(aseco, admin, arg)
        if target:
            if not _can_target_player(aseco, admin, target):
                await _deny_protected_target(aseco, admin, target.login)
                return
            try:
                await aseco.client.query_ignore_result('ForceSpectator', target.login, 2)
                aseco.console('{1} [{2}] set free spectator [{3}]', logtitle, login, target.login)
                await _broadcast(
                    aseco,
                    _fmt_admin(aseco, admin, chattitle,
                               'sets free spectator for', strip_colors(target.nickname))
                )
            except Exception as e:
                await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'forceteam':
        await _reply(aseco, login, '{#server}> {#error}/admin forceteam is not implemented yet.')

    elif sub in ('coppers', 'pay'):
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_donate.chat_admin_donate',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Coppers functions unavailable - include plugin_donate.py'
        )

    elif sub == 'relays':
        await _delegate_if_exists(
            aseco, login,
            'pyxaseco.plugins.plugin_relay.chat_admin_relays',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Relay admin unavailable.'
        )

    elif sub == 'pm':
        text = arg.strip()
        if not text:
            await _reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin pm <message>')
        else:
            sender_nick = strip_colors(admin.nickname)
            line = f'{sender_nick}: {text}'
            PM_BUFFER.append(line[:PM_LINE_LEN * 4])
            del PM_BUFFER[:-PM_BUFFER_LEN]

            recipients = _online_admin_recipients(aseco, admin)
            msg = format_text(
                '{#server}>> {#admin}PM from {#highlite}{1}$z$s{#admin}: {#message}{2}',
                sender_nick, text
            )

            sent = 0
            for pl in recipients:
                try:
                    await _reply(aseco, pl.login, msg)
                    sent += 1
                except Exception:
                    pass

            aseco.console('{1} [{2}] pm to {3} admin recipient(s): {4}', logtitle, login, sent, text)
            await _reply(
                aseco,
                login,
                f'{{#server}}> {{#message}}Private admin message sent to {{#highlite}}{sent}{{#message}} recipient{"s" if sent != 1 else ""}.'
            )

    elif sub == 'pmlog':
        if not PM_BUFFER:
            await _reply(aseco, login, '{#server}> {#message}Private admin message log is empty.')
        else:
            rows = [[f'{i+1:02d}.', line] for i, line in enumerate(PM_BUFFER[-14:])]
            display_manialink(
                aseco, login, 'Private admin messages:',
                ['Icons128x128_1', 'ProfileAdvanced', 0.02],
                rows, [0.12, 0.88], 'OK'
            )

    elif sub == 'call':
        if not args:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Usage: {#highlite}/admin call <MethodName> [arg1] [arg2] ...'
            )
        else:
            method = args[0]
            call_args = [_parse_call_arg(x) for x in args[1:]]

            try:
                result = await aseco.client.query(method, *call_args)
                aseco.console('{1} [{2}] direct call {3}({4})', logtitle, login, method, call_args)

                preview = str(result)
                if len(preview) > 300:
                    preview = preview[:297] + '...'

                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}Call {{#highlite}}{method}{{#message}} succeeded: {{#highlite}}{preview}'
                )
            except Exception as e:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Call {{#highlite}}{method}{{#error}} failed: {e}'
                )

    elif sub == 'uptodate':
        from pyxaseco.plugins.plugin_uptodate import admin_uptodate
        await admin_uptodate(aseco, command)

    elif sub == 'debug':
        current = bool(getattr(aseco, 'debug', False))
        setattr(aseco, 'debug', not current)
        await _reply(
            aseco, login,
            f'{{#server}}> {{#message}}Debug is now {{#highlite}}{"ON" if not current else "OFF"}'
        )

    elif sub == 'pyres':
        await _broadcast(
            aseco,
            _fmt_admin(aseco, admin, chattitle, 'reinitializes the PyXaseco controller!')
        )

        restart_fn = getattr(aseco, 'restart', None)
        if callable(restart_fn):
            result = restart_fn()
            if asyncio.iscoroutine(result):
                await result
        else:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}No controller restart hook available in this runtime.'
            )

    elif sub == 'shutdown':
        await _broadcast(
            aseco,
            _fmt_admin(aseco, admin, chattitle, 'shuts down XASECO!')
        )

        ok = await _best_effort_shutdown(aseco, stop_server=False)
        if not ok:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}No shutdown hook available in this runtime.'
            )

    elif sub == 'shutdownall':
        await _broadcast(
            aseco,
            _fmt_admin(aseco, admin, chattitle, 'shuts down server and XASECO!')
        )

        ok = await _best_effort_shutdown(aseco, stop_server=True)
        if not ok:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}No shutdown hook available in this runtime.'
            )

    elif sub == 'mergegbl':
        url = arg.strip()
        if not url:
            await _reply(
                aseco,
                login,
                '{#server}> {#error}Usage: {#highlite}/admin mergegbl <url>'
            )
        else:
            try:
                text = await _fetch_text_url(url)
                logins = _extract_logins_from_text(text)

                if not logins:
                    await _reply(
                        aseco,
                        login,
                        '{#server}> {#error}No valid blacklist logins found at that URL.'
                    )
                    return

                added = 0
                failed = 0

                for target_login in logins:
                    try:
                        await aseco.client.query_ignore_result('BlackList', target_login)
                        added += 1
                    except Exception:
                        failed += 1

                try:
                    await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
                except Exception:
                    pass

                aseco.console(
                    '{1} [{2}] merged global blacklist from [{3}] added={4} failed={5}',
                    logtitle, login, url, added, failed
                )

                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}Merged blacklist from {{#highlite}}{url}{{#message}}: '
                    f'{{#highlite}}{added}{{#message}} added, {{#highlite}}{failed}{{#message}} failed.'
                )

            except urllib.error.URLError as e:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Could not fetch URL: {e}'
                )
            except Exception as e:
                await _reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}{e}'
                )

    elif sub == 'disablerespawn':
        state = _get_bool_on_off(arg)
        try:
            if state is None:
                try:
                    current = await aseco.client.query('GetDisableRespawn')
                except Exception:
                    current = getattr(getattr(aseco.server, 'gameinfo', None), 'disablerespawn', None)

                if current is None:
                    await _reply(aseco, login, '{#server}> {#error}Could not read DisableRespawn state.')
                else:
                    await _reply(
                        aseco,
                        login,
                        f'{{#server}}> {{#admin}}DisableRespawn is currently {"Enabled" if current else "Disabled"}'
                    )
            else:
                await aseco.client.query_ignore_result('SetDisableRespawn', state)
                aseco.console('{1} [{2}] set DisableRespawn {3}!', logtitle, login, 'ON' if state else 'OFF')
                await _broadcast(
                    aseco,
                    _fmt_admin(
                        aseco, admin, chattitle,
                        f'sets DisableRespawn to {"ON" if state else "OFF"}!'
                    )
                )
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    elif sub == 'forceshowopp':
        value = arg.strip().upper()

        try:
            if not value:
                current = getattr(getattr(aseco.server, 'gameinfo', None), 'forceshowallopponents', None)
                if current is None:
                    await _reply(aseco, login, '{#server}> {#error}Could not read ForceShowOpponents state.')
                else:
                    if current == 0:
                        shown = 'OFF'
                    elif current == -1:
                        shown = 'ALL'
                    else:
                        shown = str(current)

                    await _reply(
                        aseco,
                        login,
                        f'{{#server}}> {{#admin}}ForceShowOpponents is currently {{#highlite}}{shown}'
                    )
            else:
                if value == 'OFF':
                    n = 0
                elif value == 'ALL':
                    n = -1
                elif value.isdigit():
                    n = int(value)
                else:
                    await _reply(
                        aseco,
                        login,
                        '{#server}> {#error}Usage: {#highlite}/admin forceshowopp <OFF|ALL|number>'
                    )
                    return

                await aseco.client.query_ignore_result('SetForceShowAllOpponents', n)
                aseco.console('{1} [{2}] set ForceShowOpponents [{3}]', logtitle, login, n)
                await _broadcast(
                    aseco,
                    _fmt_admin(
                        aseco, admin, chattitle,
                        f'sets ForceShowOpponents to {"OFF" if n == 0 else "ALL" if n == -1 else n}!'
                    )
                )
        except Exception as e:
            await _reply(aseco, login, f'{{#server}}> {{#error}}{e}')

    else:
        await _reply(aseco, login,
                     f'{{#server}}> {{#error}}Unknown admin command or missing param: {{#highlite}}$i {sub} {arg}')


async def _event_admin(aseco: 'Aseco', answer: list):
    """
    Handle ManiaLink clicks from admin-related panels.

    Action ranges:
      2201-2400  warn
      2401-2600  ignore
      2601-2800  unignore
      2801-3000  kick
      3001-3200  ban
      3201-3400  unban
      3401-3600  black
      3601-3800  unblack
      3801-4000  addguest
      4001-4200  removeguest
      4201-4400  forcespec
      4401-4600  listignores -> unignore
      4601-4800  listbans -> unban
      4801-5000  listblacks -> unblack
      5001-5200  listguests -> removeguest
      -7901--8100 unbanip
    """
    try:
        if not answer or len(answer) < 3:
            return

        login = answer[1]
        player = aseco.server.players.get_player(login)
        if not player:
            return

        action_id = int(answer[2])
        command_login: str | None = None
        subcmd: str | None = None

        # Positive ranges use admin.playerlist index
        if ML_WARN_BASE < action_id <= ML_IGNORE_BASE:
            subcmd = 'warn'
            command_login = _playerlist_get_login(player, action_id - ML_WARN_BASE)
        elif ML_IGNORE_BASE < action_id <= ML_UNIGNORE_BASE:
            subcmd = 'ignore'
            command_login = _playerlist_get_login(player, action_id - ML_IGNORE_BASE)
        elif ML_UNIGNORE_BASE < action_id <= ML_KICK_BASE:
            subcmd = 'unignore'
            command_login = _playerlist_get_login(player, action_id - ML_UNIGNORE_BASE)
        elif ML_KICK_BASE < action_id <= ML_BAN_BASE:
            subcmd = 'kick'
            command_login = _playerlist_get_login(player, action_id - ML_KICK_BASE)
        elif ML_BAN_BASE < action_id <= ML_UNBAN_BASE:
            subcmd = 'ban'
            command_login = _playerlist_get_login(player, action_id - ML_BAN_BASE)
        elif ML_UNBAN_BASE < action_id <= ML_BLACK_BASE:
            subcmd = 'unban'
            command_login = _playerlist_get_login(player, action_id - ML_UNBAN_BASE)
        elif ML_BLACK_BASE < action_id <= ML_UNBLACK_BASE:
            subcmd = 'black'
            command_login = _playerlist_get_login(player, action_id - ML_BLACK_BASE)
        elif ML_UNBLACK_BASE < action_id <= ML_ADDGUEST_BASE:
            subcmd = 'unblack'
            command_login = _playerlist_get_login(player, action_id - ML_UNBLACK_BASE)
        elif ML_ADDGUEST_BASE < action_id <= ML_REMOVEGUEST_BASE:
            subcmd = 'addguest'
            command_login = _playerlist_get_login(player, action_id - ML_ADDGUEST_BASE)
        elif ML_REMOVEGUEST_BASE < action_id <= ML_FORCESPEC_BASE:
            subcmd = 'removeguest'
            command_login = _playerlist_get_login(player, action_id - ML_REMOVEGUEST_BASE)
        elif ML_FORCESPEC_BASE < action_id <= ML_LIST_UNIGNORE_BASE:
            subcmd = 'forcespec'
            command_login = _playerlist_get_login(player, action_id - ML_FORCESPEC_BASE)
        elif ML_LIST_UNIGNORE_BASE < action_id <= ML_LIST_UNBAN_BASE:
            subcmd = 'unignore'
            command_login = _playerlist_get_login(player, action_id - ML_LIST_UNIGNORE_BASE)
        elif ML_LIST_UNBAN_BASE < action_id <= ML_LIST_UNBLACK_BASE:
            subcmd = 'unban'
            command_login = _playerlist_get_login(player, action_id - ML_LIST_UNBAN_BASE)
        elif ML_LIST_UNBLACK_BASE < action_id <= ML_LIST_REMOVEGUEST_BASE:
            subcmd = 'unblack'
            command_login = _playerlist_get_login(player, action_id - ML_LIST_UNBLACK_BASE)
        elif ML_LIST_REMOVEGUEST_BASE < action_id <= 5200:
            subcmd = 'removeguest'
            command_login = _playerlist_get_login(player, action_id - ML_LIST_REMOVEGUEST_BASE)
        elif -8100 <= action_id < ML_UNBANIP_NEG_BASE:
            subcmd = 'unbanip'
            command_login = _playerlist_get_ip(player, ML_UNBANIP_NEG_BASE - action_id)

        if subcmd and command_login:
            await chat_admin(
                aseco,
                {
                    'author': player,
                    'command': 'admin',
                    'params': f'{subcmd} {command_login}',
                }
            )

            if subcmd in (
                'warn', 'ignore', 'unignore', 'kick',
                'ban', 'unban',
                'black', 'unblack',
                'addguest', 'removeguest',
                'forcespec'
            ):
                await chat_admin(
                    aseco,
                    {
                        'author': player,
                        'command': 'admin',
                        'params': 'players',
                    }
                )

    except Exception as e:
        logger.warning('[Admin] event_admin failed: %s', e)
