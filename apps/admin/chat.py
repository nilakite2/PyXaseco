"""
Admin command router and shared admin helpers.

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
from pyxaseco.core.config import load_toml_file, _load_dotenv, _env
from pyxaseco.core.command_queries import (
    admin_ability_names,
    combined_visible_commands_for_player,
    visible_admin_commands_for_player,
    visible_chat_commands_for_player,
)
from pyxaseco.core.runtime_imports import import_runtime_callable
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.toml_tools import write_toml

from . import lists as admin_lists
from . import map as admin_map
from . import player as admin_player
from . import server as admin_server

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
    
    aseco.register_command(
        'admin',
        'Provides admin commands (see: /admin help)',
        is_admin=True,
        owner='chat/admin',
        app='admin',
        category='admin-entry',
        aliases=['ad', 'a'],
        usage='/admin <subcommand>',
        display_name='admin',
        public=True,
        order=0,
    )
    aseco.register_command(
        'listmasters',
        'Displays current masteradmin list',
        is_admin=True,
        owner='chat/admin',
        app='admin',
        category='admin-public',
        usage='/listmasters',
        display_name='listmasters',
        public=True,
        permission='listmasters',
        role='public',
        order=5,
    )
    aseco.register_command(
        'listadmins',
        'Displays current admin list',
        is_admin=True,
        owner='chat/admin',
        app='admin',
        category='admin-public',
        usage='/listadmins',
        display_name='listadmins',
        public=True,
        permission='listadmins',
        role='public',
        order=6,
    )
    aseco.register_command(
        'listops',
        'Displays current operator list',
        is_admin=True,
        owner='chat/admin',
        app='admin',
        category='admin-public',
        usage='/listops',
        display_name='listops',
        public=True,
        permission='listops',
        role='public',
        order=7,
    )
    aseco.register_event('onChat_admin', chat_admin)
    aseco.register_event('onChat_ad', chat_admin)
    aseco.register_event('onChat_a', chat_admin)
    aseco.register_event('onChat_listmasters', chat_listmasters)
    aseco.register_event('onChat_listadmins', chat_listadmins)
    aseco.register_event('onChat_listops', chat_listops)

    _read_adminops_toml(aseco)


async def _admin_startup(aseco: 'Aseco', _param=None):
    try:
        ok = _read_adminops_toml(aseco)
        if ok:
            logger.info('[Admin] Loaded adminops.toml on startup')
        else:
            logger.warning('[Admin] adminops.toml not loaded on startup')
    except Exception as e:
        logger.warning('[Admin] Startup read adminops.toml failed: %s', e)

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
    Show the player's selected admin panel, if the panel runtime is available
    and the player is an admin.
    """
    try:
        if not aseco.is_any_admin(player):
            return

        from apps.platform_ui.panels import display_admpanel
        await display_admpanel(aseco, player)
    except Exception:
        pass


async def _hide_admin_panel(aseco: 'Aseco', login: str):
    """
    Hide admin panel directly. Ownership lives in the admin chat runtime now.
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
    rows: list[tuple[str, str]] = []
    for name, cc in visible_admin_commands_for_player(
        aseco,
        player,
        auth_check=lambda cmd, _cc: bool(_auth_check(aseco, player, cmd)[0]),
    ):
        display_name = getattr(cc, 'display_name', '') or name.split('/')[-1]
        rows.append((display_name, cc.help_text))
    return rows


def _visible_normal_commands_for_player(aseco: 'Aseco', player) -> list[tuple[str, str]]:
    return [(name, cc.help_text) for name, cc in visible_chat_commands_for_player(aseco, player)]

async def _deny_protected_target(aseco: 'Aseco', actor, target_login: str):
    await _reply(
        aseco,
        actor.login,
        f'{{#server}}> {{#error}}You are not allowed to target {{#highlite}}{target_login}{{#error}} due to access hierarchy.'
    )

def _all_visible_commands_for_player(aseco: 'Aseco', player) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for name, cc in combined_visible_commands_for_player(
        aseco,
        player,
        admin_auth_check=lambda cmd, _cc: bool(_auth_check(aseco, player, cmd)[0]),
    ):
        label = getattr(cc, 'display_name', '') or name.split('/')[-1]
        rows.append((label, cc.help_text))
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
    legacy = set(_LEGACY_ADMIN_ABILITIES.keys()) | set(_LEGACY_OPERATOR_ABILITIES.keys())
    return admin_ability_names(aseco, legacy_names=legacy)


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


def _write_adminops_toml(aseco: 'Aseco'):
    """
    Write adminops.toml, preserving legacy ability keys.
    """
    global _LEGACY_ADMINOPS_TITLES, _LEGACY_ADMIN_ABILITIES, _LEGACY_OPERATOR_ABILITIES

    try:
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        path = base / 'adminops.toml'

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

        data = {
            'titles': titles,
            'masteradmins': {
                'tmlogin': masters,
                'ipaddress': [''] * len(masters),
            },
            'admins': {
                'tmlogin': admins,
                'ipaddress': [''] * len(admins),
            },
            'operators': {
                'tmlogin': ops,
                'ipaddress': [''] * len(ops),
            },
            'abilities': {
                'admin': {cmd: bool(admin_abilities.get(cmd, _ability_enabled(aseco, 'admin', cmd))) for cmd in all_cmds},
                'operator': {cmd: bool(operator_abilities.get(cmd, _ability_enabled(aseco, 'op', cmd))) for cmd in all_cmds},
            },
        }
        write_toml(path, data)

        _LEGACY_ADMIN_ABILITIES = dict(admin_abilities)
        _LEGACY_OPERATOR_ABILITIES = dict(operator_abilities)

        return path

    except Exception as e:
        logger.warning('[Admin] Could not write adminops.toml: %s', e)
        return None

def _read_adminops_toml(aseco: 'Aseco'):
    """
    Read adminops.toml and preserve all ability keys.
    """
    global _LEGACY_ADMINOPS_TITLES, _LEGACY_ADMIN_ABILITIES, _LEGACY_OPERATOR_ABILITIES

    try:
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        path = base / 'adminops.toml'
        if not path.exists():
            return False

        data = load_toml_file(path)
        if not data:
            return False

        root = data if isinstance(data, dict) else {}
        if not isinstance(root, dict):
            return False

        blk = root.get('titles', {})
        if isinstance(blk, dict):
            _LEGACY_ADMINOPS_TITLES = {
                'masteradmin': str(blk.get('masteradmin', 'MasterAdmin')),
                'admin': str(blk.get('admin', 'Admin')),
                'operator': str(blk.get('operator', 'Operator')),
            }

        def _extract_logins(section_name: str) -> list[str]:
            section = root.get(section_name.lower(), {})
            if not isinstance(section, dict):
                return []
            vals = section.get('tmlogin', [])
            return [str(v).strip() for v in vals if str(v).strip()]

        aseco.settings.masteradmin_list['TMLOGIN'] = _extract_logins('MASTERADMINS')
        aseco.settings.admin_list['TMLOGIN'] = _extract_logins('ADMINS')
        aseco.settings.operator_list['TMLOGIN'] = _extract_logins('OPERATORS')

        master_ips = aseco.settings.masteradmin_list.get('IPADDRESS', [])
        master_cnt = len(aseco.settings.masteradmin_list['TMLOGIN'])
        if not master_ips or len(master_ips) < master_cnt:
            aseco.settings.masteradmin_list['IPADDRESS'] = (master_ips or []) + [''] * (master_cnt - len(master_ips))

        # Re-apply env-defined MasterAdmins after adminops.toml reload so
        # empty XML files do not wipe explicit controller-level overrides.
        _load_dotenv(base / '.env')
        _load_dotenv('.env')
        extra_masteradmins = [x.strip() for x in (_env('MASTERADMIN_LOGINS') or '').split(',') if x.strip()]
        existing = {str(v).strip().lower() for v in aseco.settings.masteradmin_list['TMLOGIN']}
        for login in extra_masteradmins:
            if login.lower() not in existing:
                aseco.settings.masteradmin_list['TMLOGIN'].append(login)
                aseco.settings.masteradmin_list['IPADDRESS'].append('')
                existing.add(login.lower())

        admin_store = _get_ability_store(aseco, 'admin')
        op_store = _get_ability_store(aseco, 'op')
        admin_store.clear()
        op_store.clear()

        def _load_abilities(section_name: str) -> dict[str, bool]:
            result: dict[str, bool] = {}
            abilities = root.get('abilities', {})
            if not isinstance(abilities, dict):
                return result
            blk = abilities.get(section_name.lower(), {})
            if not isinstance(blk, dict):
                return result

            for key, value in blk.items():
                result[str(key).lower()] = bool(value) if isinstance(value, bool) else str(value).strip().lower() == 'true'
            return result

        _LEGACY_ADMIN_ABILITIES = _load_abilities('admin')
        _LEGACY_OPERATOR_ABILITIES = _load_abilities('operator')

        admin_store.update(_LEGACY_ADMIN_ABILITIES)
        op_store.update(_LEGACY_OPERATOR_ABILITIES)

        return True

    except Exception as e:
        logger.warning('[Admin] Could not read adminops.toml: %s', e)
        return False


def _bannedips_path(aseco: 'Aseco') -> pathlib.Path:
    base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
    return base / 'bannedips.toml'


async def _write_bannedips_toml(aseco: 'Aseco') -> pathlib.Path | None:
    try:
        ips = await aseco.client.query('GetBannedIPs') or []
        path = _bannedips_path(aseco)
        write_toml(path, {'banned_ips': [str(ip).strip() for ip in ips if str(ip).strip()]})
        return path
    except Exception as e:
        logger.warning('[Admin] Could not write bannedips.toml: %s', e)
        return None


async def _read_bannedips_toml(aseco: 'Aseco') -> bool:
    try:
        path = _bannedips_path(aseco)
        data = load_toml_file(path)
        if not data:
            return False
        ips = data.get('banned_ips', data.get('ipaddress', []))
        if not isinstance(ips, list):
            return False
        await aseco.client.query_ignore_result('CleanBannedIPs')
        for ip in ips:
            ip = str(ip).strip()
            if ip:
                await aseco.client.query_ignore_result('BanIP', ip)
        return True
    except Exception as e:
        logger.warning('[Admin] Could not read bannedips.toml: %s', e)
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
        pool = await localdb_get_pool(aseco)
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
        pool = await localdb_get_pool(aseco)
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
        from apps.rasp.jukebox import _parse_gbx_metadata
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
        from apps.rasp.jukebox import (
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
        pool = await localdb_get_pool(aseco)
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
                    from pyxaseco.core.challenges_cache import remove_for_uid
                    await remove_for_uid(pool, uid)
                except Exception:
                    pass

                try:
                    await cur.execute('DELETE FROM rs_karma WHERE uid=%s', (uid,))
                except Exception:
                    pass

                try:
                    await cur.execute('DELETE FROM custom_tracktimes WHERE challenge_uid=%s', (uid,))
                except Exception as e:
                    # FlexiTime is optional; if its table does not exist, ignore it.
                    if 'doesn\'t exist' not in str(e).lower() and '1146' not in str(e):
                        raise
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
        func = import_runtime_callable(func_path)
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

    if admin_server.can_handle(sub):
        handled = await admin_server.handle_subcommand(
            aseco, command, sub, args, arg, login, admin, logtitle, chattitle
        )
        if handled:
            return

    if admin_lists.can_handle(sub):
        handled = await admin_lists.handle_subcommand(
            aseco, command, sub, args, arg, login, admin, logtitle, chattitle
        )
        if handled:
            return

    if admin_map.can_handle(sub):
        handled = await admin_map.handle_subcommand(
            aseco, command, sub, args, arg, login, admin, logtitle, chattitle
        )
        if handled:
            return

    if admin_player.can_handle(sub):
        handled = await admin_player.handle_subcommand(
            aseco, command, sub, args, arg, login, admin, logtitle, chattitle
        )
        if handled:
            return

    # ---- Player moderation ----

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

