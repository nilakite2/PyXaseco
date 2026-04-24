"""
jfreu_plugin.py — Port of plugins/jfreu.plugin.php + jfreu.chat.php

Jfreu's plugin v0.14 — rank limiting, VIP system, badwords filter,
SpecOnly management, unspec voting, player join/leave messages,
random info messages, and a comprehensive /jfreu admin command panel.

Config files (in plugins/jfreu/ alongside plugins.xml):
  jfreu.config.xml — main settings (ranklimit, autorank, badwords, etc.)
  jfreu.vips.xml   — VIP and VIP_Team lists
  jfreu.bans.xml   — temporary ban list

Commands:
  /ranklimit  /password  /unspec  /yes  /no  /message  /fake  /jfreu [subcmd]
"""

from __future__ import annotations
import time as _time
import random
import re
import pathlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pyxaseco.core.config import parse_xml_file
from pyxaseco.helpers import format_text, format_time_h, strip_colors, display_manialink_multi, display_manialink

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

VERSION = '0.14'

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PlayerEntry:
    hasvoted: int = 0       # 0=not voted, 1=yes, -1=no
    badwords: int = 0
    kicked: bool = False
    isvip: bool = False
    speconly: bool = False
    banned: int = 0         # unix timestamp when ban expires, 0=not banned


@dataclass
class Vote:
    login: str = ''
    yes: int = 0
    no: int = 0
    total: int = 0
    nb_votes_needed: int = 0
    type: str = ''


@dataclass
class JfreuState:
    version: str = VERSION

    # Config
    conf_file: str = ''
    vips_file: str = ''
    bans_file: str = ''
    servername: str = ''
    top: str = ''
    autochangename: bool = False

    # Rank limiting
    ranklimit: bool = False
    limit: int = 500000
    hardlimit: int = 0
    autorank: bool = False
    offset: int = 0
    autolimit: int = 500000
    autorankminplayers: int = 10
    autorankvip: bool = False
    maxplayers: int = 20
    kickhirank: bool = False

    # Colors (pre-formatted)
    white: str = '$fff'
    yellow: str = '$ff0'
    red: str = '$f00'
    blue: str = '$09f'
    green: str = '$0f0'
    admin: str = '$f80'

    # Messages
    infomessages: int = 1
    message_start: str = ''
    messages: list = field(default_factory=list)
    nbmessages: int = 0
    player_join: str = ''
    player_joins: str = ''
    player_left: str = ''

    # Votes
    current_vote: bool = False
    vote_item: Vote = field(default_factory=Vote)
    novote: bool = False
    unspecvote: bool = True

    # Player tracking
    playerlist: dict = field(default_factory=dict)  # {login: PlayerEntry}

    # VIP lists
    vip_list: list = field(default_factory=list)
    vip_team_list: list = field(default_factory=list)

    # BadWords
    badwords: bool = False
    badwordsban: bool = False
    badwordsnum: int = 3
    badwordstime: int = 10
    badwordslist: list = field(default_factory=list)

    # PF kick
    pf: int = 0


# Module-level state
_state: JfreuState = JfreuState()
_base_dir: pathlib.Path = pathlib.Path('.')


def register(aseco: 'Aseco'):
    global _base_dir
    _base_dir = aseco._base_dir

    aseco.register_event('onStartup',        init_jfreu)
    aseco.register_event('onPlayerConnect',  player_connect)
    aseco.register_event('onPlayerDisconnect', player_disconnect)
    aseco.register_event('onEndRace',        kick_hirank)
    aseco.register_event('onEndRace',        vote_end)
    aseco.register_event('onEndRace',        info_message)
    aseco.register_event('onCheckpoint',     kick_speconly)
    aseco.register_event('onChat',           novote_handler)
    aseco.register_event('onChat',           bad_words_handler)
    aseco.register_event('onPlayerFinish',   pf_kick)
    aseco.register_event('onPlayerManialinkPageAnswer', event_jfreu)

    aseco.add_chat_command('ranklimit', 'Shows the current rank limit')
    aseco.add_chat_command('password',  "Show server's player/spectator password")
    aseco.add_chat_command('unspec',    'Launches an unSpec vote')
    aseco.add_chat_command('yes',       'Votes Yes for unSpec')
    aseco.add_chat_command('no',        'Votes No for unSpec')
    aseco.add_chat_command('message',   'Shows random informational message')
    aseco.add_chat_command('jfreu',     'Jfreu admin commands (see: /jfreu help)')

    aseco.register_event('onChat_ranklimit', chat_ranklimit)
    aseco.register_event('onChat_password',  chat_password)
    aseco.register_event('onChat_unspec',    chat_unspec)
    aseco.register_event('onChat_yes',       chat_yes)
    aseco.register_event('onChat_no',        chat_no)
    aseco.register_event('onChat_message',   chat_message)
    aseco.register_event('onChat_jfreu',     chat_jfreu)

    aseco.add_chat_command('fake',      'Broadcasts a fake local record message (admin only)')
    
    aseco.register_event('onChat_fake',      chat_fake)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def init_jfreu(aseco: 'Aseco', _param):
    global _state, _base_dir

    _state = JfreuState()

    # File paths
    jfreu_dir = _base_dir / 'plugins' / 'jfreu'
    _state.conf_file = str(jfreu_dir / 'jfreu.config.xml')
    _state.vips_file = str(jfreu_dir / 'jfreu.vips.xml')
    _state.bans_file = str(jfreu_dir / 'jfreu.bans.xml')

    # Load config
    _load_config(aseco)
    _read_lists_xml(aseco)
    await _read_guest_list(aseco)
    _read_bans_xml(aseco)

    # Init colour strings from aseco colours
    _state.white  = aseco.format_colors('$z$s{#highlite}')
    _state.yellow = aseco.format_colors('$z$s{#server}')
    _state.red    = aseco.format_colors('$z$s{#error}')
    _state.blue   = aseco.format_colors('$z$s{#message}')
    _state.green  = aseco.format_colors('$z$s{#record}')
    _state.admin  = aseco.format_colors('$z$s{#logina}')

    # Init playerlist for all currently online players
    for pl in aseco.server.players.all():
        _add_player(pl.login, False, False)

    whi, yel, blu = _state.white, _state.yellow, _state.blue
    msg = f"{yel}>> {whi}Jfreu{blu}'s plugin {_state.green}{VERSION}{blu}: {whi}Loaded{blu}."
    await aseco.client.query_ignore_result('ChatSendServerMessage', msg)

    set_ranklimit(aseco, _state.autolimit, 1 if _state.autorank else 0)


def _load_config(aseco: 'Aseco'):
    try:
        data = parse_xml_file(pathlib.Path(_state.conf_file))
        if not data:
            return
        srv = data.get('CONFIG', {}).get('SERVER', [{}])[0]
        lim = data.get('CONFIG', {}).get('LIMITS', [{}])[0]

        def g(block, key, default=''):
            items = block.get(key.upper(), [default])
            return items[0] if items else default

        def b(block, key, default=False):
            v = g(block, key, 'false')
            return str(v).lower() == 'true'

        _state.servername        = g(srv, 'SERVERNAME', '')
        _state.top               = g(srv, 'SERVERTOP', '')
        _state.autochangename    = b(srv, 'AUTOCHANGENAME')
        _state.infomessages      = int(g(srv, 'INFOMESSAGES', 1))
        _state.badwords          = b(srv, 'BADWORDS')
        _state.badwordsban       = b(srv, 'BADWORDSBAN')
        _state.badwordsnum       = int(g(srv, 'BADWORDSNUM', 3))
        _state.badwordstime      = int(g(srv, 'BADWORDSTIME', 10))
        _state.unspecvote        = b(srv, 'UNSPECVOTE', True)
        _state.novote            = b(srv, 'NOVOTE')

        _state.ranklimit         = b(lim, 'RANKLIMIT')
        _state.limit             = int(g(lim, 'LIMIT', 500000))
        _state.hardlimit         = int(g(lim, 'HARDLIMIT', 0))
        _state.autorank          = b(lim, 'AUTORANK')
        _state.offset            = int(g(lim, 'OFFSET', 0))
        _state.autolimit         = int(g(lim, 'AUTOLIMIT', _state.limit))
        _state.autorankminplayers = int(g(lim, 'AUTORANKMINPLAYERS', 10))
        _state.autorankvip       = b(lim, 'AUTORANKVIP')
        _state.maxplayers        = int(g(lim, 'MAXPLAYERS', 20))
        _state.kickhirank        = b(lim, 'KICKHIRANK')
        _state.pf                = int(g(lim, 'PF', 0))

        # Load random messages from config if present
        _load_messages_from_config(data)

    except Exception as e:
        logger.warning('[Jfreu] Could not load config: %s', e)


def _load_messages_from_config(data: dict):
    """Load join/leave messages and info messages from the config XML."""
    # Default messages if not in XML
    _state.player_join  = '{#server}>> {1}: {#highlite}{2}$z$s{#message} Nation: {#highlite}{3}{#message} Ladder: {#highlite}{4}'
    _state.player_joins = '{#server}>> {1}: {#highlite}{2}$z$s{#message} Nation: {#highlite}{3}{#message} Ladder: {#highlite}{4}{#message} Server: {#highlite}{5}'
    _state.player_left  = '{#server}>> {#highlite}{1}$z$s{#message} has left the game. Played: {#highlite}{2}'
    _state.message_start = '$z$s$ff0>> [$f00INFO$ff0] $fff'

    cfg = data.get('CONFIG', {})
    msg_block = cfg.get('MESSAGES', [{}])[0] if cfg.get('MESSAGES') else {}
    if msg_block:
        def g(key, default=''):
            items = msg_block.get(key.upper(), [default])
            return items[0] if items else default
        _state.player_join  = g('PLAYER_JOIN', _state.player_join)
        _state.player_joins = g('PLAYER_JOINS', _state.player_joins)
        _state.player_left  = g('PLAYER_LEFT', _state.player_left)
        _state.message_start = g('MESSAGE_START', _state.message_start)

        _state.messages = []
        i = 1
        while True:
            msg = g(f'MESSAGE{i}', None)
            if msg is None:
                break
            _state.messages.append(msg)
            i += 1
        _state.nbmessages = len(_state.messages)


def _read_lists_xml(aseco: 'Aseco'):
    try:
        data = parse_xml_file(pathlib.Path(_state.vips_file))
        if not data:
            return
        lists = data.get('LISTS', {})
        vip = lists.get('VIP_LIST', [{}])[0]
        vip_team = lists.get('VIP_TEAM_LIST', [{}])[0]
        for lgn in (vip.get('LOGIN', []) if isinstance(vip, dict) else []):
            if lgn and lgn not in _state.vip_list:
                _state.vip_list.append(lgn)
        for team in (vip_team.get('TEAM', []) if isinstance(vip_team, dict) else []):
            if team and team not in _state.vip_team_list:
                _state.vip_team_list.append(team)
    except Exception as e:
        logger.warning('[Jfreu] Could not read vips file: %s', e)


async def _read_guest_list(aseco: 'Aseco'):
    try:
        guests = await aseco.client.query('GetGuestList', 300, 0)
        for pl in (guests or []):
            lgn = pl.get('Login', '')
            if lgn and lgn not in _state.vip_list:
                _state.vip_list.append(lgn)
    except Exception:
        pass


def _read_bans_xml(aseco: 'Aseco'):
    try:
        data = parse_xml_file(pathlib.Path(_state.bans_file))
        if not data:
            return
        ban_list = data.get('LISTS', {}).get('BAN_LIST', [{}])[0]
        logins = ban_list.get('LOGIN', []) if isinstance(ban_list, dict) else []
        times  = ban_list.get('TIME', [])  if isinstance(ban_list, dict) else []
        now = _time.time()
        for lgn, ts in zip(logins, times):
            try:
                ts = float(ts)
            except (ValueError, TypeError):
                ts = 0
            if ts > now:
                _add_player(lgn, False, False)
                _state.playerlist[lgn].banned = int(ts)
    except Exception as e:
        logger.warning('[Jfreu] Could not read bans file: %s', e)


def _write_lists_xml():
    try:
        lines = ['<?xml version="1.0" encoding="utf-8" ?>', '<lists>', '\t<vip_list>']
        for lgn in _state.vip_list:
            if lgn:
                lines.append(f'\t\t<login>{lgn}</login>')
        lines += ['\t</vip_list>', '', '\t<vip_team_list>']
        for team in _state.vip_team_list:
            if team:
                lines.append(f'\t\t<team>{team}</team>')
        lines += ['\t</vip_team_list>', '</lists>']
        pathlib.Path(_state.vips_file).write_text('\n'.join(lines), encoding='utf-8')
    except Exception as e:
        logger.warning('[Jfreu] Could not write vips file: %s', e)


def _write_config_xml():
    try:
        j = _state
        lines = [
            '<?xml version="1.0" encoding="utf-8" ?>', '<config>', '\t<server>',
            f'\t\t<servername>{j.servername}</servername>',
            f'\t\t<servertop>{j.top}</servertop>',
            f'\t\t<autochangename>{"true" if j.autochangename else "false"}</autochangename>',
            f'\t\t<infomessages>{j.infomessages}</infomessages>',
            f'\t\t<badwords>{"true" if j.badwords else "false"}</badwords>',
            f'\t\t<badwordsban>{"true" if j.badwordsban else "false"}</badwordsban>',
            f'\t\t<badwordsnum>{j.badwordsnum}</badwordsnum>',
            f'\t\t<badwordstime>{j.badwordstime}</badwordstime>',
            f'\t\t<unspecvote>{"true" if j.unspecvote else "false"}</unspecvote>',
            f'\t\t<novote>{"true" if j.novote else "false"}</novote>',
            '\t</server>', '\t<limits>',
            f'\t\t<ranklimit>{"true" if j.ranklimit else "false"}</ranklimit>',
            f'\t\t<limit>{j.limit}</limit>',
            f'\t\t<hardlimit>{j.hardlimit}</hardlimit>',
            f'\t\t<autorank>{"true" if j.autorank else "false"}</autorank>',
            f'\t\t<offset>{j.offset}</offset>',
            f'\t\t<autolimit>{j.autolimit}</autolimit>',
            f'\t\t<autorankminplayers>{j.autorankminplayers}</autorankminplayers>',
            f'\t\t<autorankvip>{"true" if j.autorankvip else "false"}</autorankvip>',
            f'\t\t<maxplayers>{j.maxplayers}</maxplayers>',
            f'\t\t<kickhirank>{"true" if j.kickhirank else "false"}</kickhirank>',
            f'\t\t<pf>{j.pf}</pf>',
            '\t</limits>', '</config>',
        ]
        pathlib.Path(_state.conf_file).write_text('\n'.join(lines), encoding='utf-8')
    except Exception as e:
        logger.warning('[Jfreu] Could not write config file: %s', e)


def _write_bans_xml():
    try:
        now = _time.time()
        lines = ['<?xml version="1.0" encoding="utf-8" ?>', '<lists>', '\t<ban_list>']
        for lgn, entry in _state.playerlist.items():
            if entry.banned > now:
                lines.append(f'\t\t<login>{lgn}</login> <time>{entry.banned}</time>')
        lines += ['\t</ban_list>', '</lists>']
        pathlib.Path(_state.bans_file).write_text('\n'.join(lines), encoding='utf-8')
    except Exception as e:
        logger.warning('[Jfreu] Could not write bans file: %s', e)


# ---------------------------------------------------------------------------
# Player tracking helpers
# ---------------------------------------------------------------------------

def _add_player(login: str, isvip: bool, speconly: bool):
    if login not in _state.playerlist:
        _state.playerlist[login] = PlayerEntry()
    _state.playerlist[login].isvip    = isvip
    _state.playerlist[login].speconly = speconly
    _state.playerlist[login].kicked   = False


def _clean_nick(nick: str) -> str:
    return str(nick or (_state.red + 'ERROR'))


def _is_vip(login: str) -> bool:
    entry = _state.playerlist.get(login)
    if entry and entry.isvip:
        return True
    return login in _state.vip_list


def _is_banned(login: str) -> int:
    """Return minutes remaining in ban, or 0 if not banned."""
    entry = _state.playerlist.get(login)
    if not entry or entry.banned == 0:
        return 0
    now = _time.time()
    if entry.banned > now:
        return round((entry.banned - now) / 60)
    _state.playerlist[login].banned = 0
    return 0


def _ban_for(aseco: 'Aseco', login: str, minutes: int):
    """Apply a temporary ban."""
    import asyncio
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    ban_str = _fmt_ban_time(minutes, whi, red)

    _add_player(login, False, False)
    _state.playerlist[login].banned = int(_time.time()) + minutes * 60
    _state.playerlist[login].kicked = True

    async def _do():
        # Notify + kick if online
        for pl in aseco.server.players.all():
            if pl.login == login:
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessageToLogin',
                    f'{yel}> {red}You have been Banned for {whi}{ban_str}.', login)
                await aseco.client.query_ignore_result('Kick', login)
                break
        aseco.console('[BanFor] player "{1}" banned for {2}', login, strip_colors(ban_str))
        _write_bans_xml()

    asyncio.ensure_future(_do())


def _fmt_ban_time(minutes: int, whi: str, red: str) -> str:
    if minutes > 60:
        h = minutes // 60
        m = minutes % 60
        return f'{h}{red} hour{"s" if h!=1 else ""}  {whi}{m:02d}{red} min{"s" if m!=1 else ""}'
    return f'{minutes}{red} min{"s" if minutes!=1 else ""}'


async def _set_server_name(aseco: 'Aseco'):
    if not _state.autochangename:
        return
    try:
        if _state.ranklimit:
            limit = _state.autolimit if _state.autorank else _state.limit
            sname = _state.servername + _state.top + str(limit)
        else:
            sname = _state.servername + ' NoLimit'
        await aseco.client.query_ignore_result('SetServerName', sname)
    except Exception:
        logger.debug('[Jfreu] Could not update server name', exc_info=True)


def set_ranklimit(aseco: 'Aseco', limit: int, auto: int):
    """Set rank limit and optionally update server name. auto: 0=admin, 1=autorank, 2=forced."""
    import asyncio
    whi, yel, blu = _state.white, _state.yellow, _state.blue

    if not limit:
        return

    if auto == 1:
        _state.autolimit = limit
        msg = f'{yel}>> {blu}Auto-RankLimit: {whi}{limit}'
    elif auto == 0:
        _state.limit = limit
        msg = f'{yel}>> {blu}New RankLimit: {whi}{limit}'
    else:
        _state.autolimit = limit
        msg = f'{yel}>> {blu}Auto-RankLimit: {whi}{limit}{blu} (forced by admin)'

    if not _state.ranklimit:
        msg = f'{yel}>> {blu}RankLimit: {whi}OFF{blu}.'

    async def _do():
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
        if _state.autochangename:
            sname = _state.servername + _state.top + str(limit)
            await aseco.client.query_ignore_result('SetServerName', sname)
    asyncio.ensure_future(_do())


def _autorank(aseco: 'Aseco'):
    """Recalculate the auto rank limit from current players."""
    import asyncio
    whi, yel, blu = _state.white, _state.yellow, _state.blue
    players = aseco.server.players.all()
    nb = len(players)

    if nb == 0 or _state.autorankminplayers > nb:
        msg = (f'{yel}>> {blu}Not enough players: {whi}{nb}{blu}/'
               f'{whi}{_state.autorankminplayers}{blu} (autorank {_state.red}disabled{blu})')
        asyncio.ensure_future(
            aseco.client.query_ignore_result('ChatSendServerMessage', msg))
        set_ranklimit(aseco, _state.limit, 0)
        return

    total = 0
    count = 0
    for pl in players:
        rank = getattr(pl, 'ladderrank', 0)
        if rank > 0 and not _state.playerlist.get(pl.login, PlayerEntry()).speconly:
            if not _state.autorankvip or not _is_vip(pl.login) or rank <= _state.autolimit:
                total += rank
                count += 1

    if total > 0 and count > 0:
        avg = total / count
        newlimit = max(1, round(avg + _state.offset))
        set_ranklimit(aseco, newlimit, 1)


def _wrap_text_lines(text: str, max_len: int = 70) -> list[str]:
    """Split text into multiple lines based on max length (Manialink-safe)."""
    words = text.split()
    lines = []
    current = ""

    for word in words:
        if len(strip_colors(current + " " + word)) > max_len:
            lines.append(current.strip())
            current = word
        else:
            current += " " + word

    if current:
        lines.append(current.strip())

    return lines

# ---------------------------------------------------------------------------
# Player connect / disconnect
# ---------------------------------------------------------------------------

async def player_connect(aseco: 'Aseco', player: 'Player'):
    whi, yel, red, blu, gre, adm = (
        _state.white, _state.yellow, _state.red,
        _state.blue, _state.green, _state.admin)

    nation = player.nation
    if len(nation) > 14:
        from pyxaseco.plugins.plugin_localdatabase import map_country
        nation = map_country(nation)

    ban_mins = _is_banned(player.login)
    if ban_mins:
        ban_str = _fmt_ban_time(ban_mins, whi, red)
        rank_str = format(getattr(player, 'ladderrank', 0), ',').replace(',', '$n $m')
        title = _get_title(aseco, player, adm, blu)
        msg = (f'{yel}>> {title}: {whi}{_clean_nick(player.nickname)}'
               f'{blu} Nation: {whi}{nation}{blu} Ladder: {whi}{rank_str}'
               f'{blu} [{red}Banned for  {whi}{ban_str}{blu}]')
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
        msg2 = f'{yel}> {red}Your ban will be over in  {whi}{ban_str}!'
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', msg2, player.login)
        _state.playerlist.setdefault(player.login, PlayerEntry()).kicked = True
        await aseco.client.query_ignore_result('Kick', player.login)
        return

    if _state.ranklimit:
        kicked = await _autokick(aseco, player)
        if not kicked and _state.autorank and not player.isspectator:
            _autorank(aseco)
    else:
        _add_player(player.login, False, False)
        if aseco.startup_phase:
            return
        await _show_join_message(aseco, player, nation)


async def _autokick(aseco: 'Aseco', player: 'Player') -> bool:
    """Apply rank limiting. Returns True if player was kicked."""
    whi, yel, red, blu, gre, adm = (
        _state.white, _state.yellow, _state.red,
        _state.blue, _state.green, _state.admin)

    nation = player.nation
    if len(nation) > 14:
        from pyxaseco.plugins.plugin_localdatabase import map_country
        nation = map_country(nation)

    rank = getattr(player, 'ladderrank', 0)
    limit = _state.autolimit if _state.autorank else _state.limit

    # Hard limit check
    if _state.hardlimit and (rank > _state.hardlimit or rank <= 0):
        _add_player(player.login, False, False)
        msg = (f'{red}This server is only for players with a rank lower than  '
               f'{whi}{_state.hardlimit}{red} !')
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {msg}', player.login)
        aseco.console('[HardLimit] player "{1}" kicked (rank: {2})', player.login, rank)
        _state.playerlist[player.login].kicked = True
        await aseco.client.query_ignore_result('Kick', player.login, msg + ' $z')
        return True

    if rank > limit or rank <= 0:
        if not player.isspectator:
            # Not VIP -> kick
            if (player.login not in _state.vip_list and
                    player.teamname not in _state.vip_team_list):
                _add_player(player.login, False, False)
                msg = (f'{red}This server is only for players with a rank lower than  '
                       f'{whi}{limit}{red} !')
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessageToLogin', f'{yel}> {msg}', player.login)
                title = _get_title(aseco, player, adm, blu)
                rank_str = format(rank, ',').replace(',', '$n $m')
                msg2 = (f'{yel}>> {title}: {whi}{_clean_nick(player.nickname)}'
                        f'{blu} Nation: {whi}{nation}{blu} Ladder: {red}{rank_str}'
                        f'{blu}  [{red}Kicked{blu}]')
                await aseco.client.query_ignore_result('ChatSendServerMessage', msg2)
                aseco.console('[AutoRank] player "{1}" kicked (rank: {2})', player.login, rank)
                _state.playerlist[player.login].kicked = True
                await aseco.client.query_ignore_result('Kick', player.login, msg + ' $z')
                return True
            # VIP
            else:
                _add_player(player.login, True, False)
                title = _get_title(aseco, player, adm, blu)
                rank_str = format(rank, ',').replace(',', '$n $m')
                msg = (f'{yel}>> {title}: {whi}{_clean_nick(player.nickname)}'
                       f'{blu} Nation: {whi}{nation}{blu} Ladder: {red}{rank_str} '
                       f'{blu} [{gre}VIP{blu}]')
                await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
        else:
            # Spectator, high rank, not VIP -> SpecOnly
            if (player.login not in _state.vip_list and
                    player.teamname not in _state.vip_team_list):
                _add_player(player.login, False, True)
                title = _get_title(aseco, player, adm, blu)
                rank_str = format(rank, ',').replace(',', '$n $m')
                msg = (f'{yel}>> {title}: {whi}{_clean_nick(player.nickname)}'
                       f'{blu} Nation: {whi}{nation}{blu} Ladder: {red}{rank_str}'
                       f'{blu}  [{gre}SpecOnly{blu}]')
                await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
                await _spec_message(aseco, player.login)
            else:
                # VIP spectator
                _add_player(player.login, True, False)
                await _show_join_message(aseco, player, nation)
    else:
        # Normal player
        _add_player(player.login, False, False)
        await _show_join_message(aseco, player, nation)

    return False


async def _show_join_message(aseco: 'Aseco', player: 'Player', nation: str):
    if aseco.startup_phase:
        return
    adm, blu = _state.admin, _state.blue
    title = _get_title(aseco, player, adm, blu)
    rank_str = format(getattr(player, 'ladderrank', 0), ',').replace(',', '$n $m')

    try:
        from pyxaseco.plugins.plugin_rasp import _rasp_messages, feature_ranks
        rank_info = None
        if feature_ranks:
            from pyxaseco.plugins.plugin_localdatabase import get_pool, get_player_id
            pool = await get_pool()
            if pool:
                pid = await get_player_id(player.login)
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute('SELECT avg FROM rs_rank WHERE playerID=%s', (pid,))
                        row = await cur.fetchone()
                        if row:
                            my_avg = row[0]
                            await cur.execute('SELECT COUNT(*) FROM rs_rank WHERE avg < %s', (my_avg,))
                            better = (await cur.fetchone())[0]
                            await cur.execute('SELECT COUNT(*) FROM rs_rank')
                            total = (await cur.fetchone())[0]
                            rank_info = format_text(
                                '{1}/{2} Avg: {3}',
                                better + 1,
                                total,
                                f'{my_avg/10000:4.1f}',
                            )
        if rank_info:
            msg = format_text(_state.player_joins, title,
                              _clean_nick(player.nickname), nation, rank_str, rank_info)
        else:
            msg = format_text(_state.player_join, title,
                              _clean_nick(player.nickname), nation, rank_str)
    except Exception:
        msg = format_text(_state.player_join, title,
                          _clean_nick(player.nickname), nation, rank_str)

    await aseco.client.query_ignore_result(
        'ChatSendServerMessage', aseco.format_colors(msg))


def _get_title(aseco: 'Aseco', player: 'Player', adm: str, blu: str) -> str:
    titles = getattr(aseco, 'titles', {}) or {}

    def _title(key: str, fallback: str) -> str:
        value = titles.get(key, [fallback])
        if isinstance(value, list) and value:
            return str(value[0] or fallback)
        return str(value or fallback)

    if aseco.is_master_admin(player):
        return adm + _title('MASTERADMIN', 'MasterAdmin')
    if aseco.is_admin(player):
        return adm + _title('ADMIN', 'Admin')
    if aseco.is_operator(player):
        return adm + _title('OPERATOR', 'Operator')
    return blu + 'New Player'


async def player_disconnect(aseco: 'Aseco', player: 'Player'):
    entry = _state.playerlist.get(player.login)

    # Cancel any ongoing vote for this player
    if _state.current_vote and _state.vote_item.login == player.login:
        _state.current_vote = False
        _state.vote_item = Vote()
        whi, yel, blu = _state.white, _state.yellow, _state.blue
        msg = f'{yel}>> {whi}{_clean_nick(player.nickname)}{blu}\'s vote cancelled.'
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)

    if entry and not entry.kicked:
        online_secs = player.get_time_online()
        msg = format_text(_state.player_left,
                          _clean_nick(player.nickname),
                          format_time_h(online_secs * 1000, False))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(msg))
        if _state.autorank and entry and not entry.speconly:
            _autorank(aseco)


# ---------------------------------------------------------------------------
# End race events
# ---------------------------------------------------------------------------

async def kick_hirank(aseco: 'Aseco', _params):
    if not _state.kickhirank:
        return
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    nb = len(aseco.server.players.all())
    mx = _state.maxplayers
    diff = nb - mx
    if diff > 0:
        msg = (f'{yel}>> {blu}Server is full ({red}{nb}{blu}/{whi}{mx}{blu}): '
               f'$n{whi}{diff}{blu} Hi-rank player{"s" if diff!=1 else ""} will be kicked.')
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
        await _kick_worst(aseco, diff)
    else:
        msg = (f'{yel}>> {blu}Server is not full ({_state.green}{nb}{blu}/{whi}{mx}{blu}): '
               f'{_state.green}No kick{blu}.')
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)


async def _kick_worst(aseco: 'Aseco', count: int):
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    players = aseco.server.players.all()
    if not players:
        return

    sorted_players = sorted(players,
                            key=lambda p: getattr(p, 'ladderrank', 0) or 10**9,
                            reverse=True)
    kicked_nicks = []
    for pl in sorted_players[:count]:
        nick = _clean_nick(pl.nickname)
        aseco.console('[KickWorst] player "{1}" kicked (rank: {2})',
                      pl.login, getattr(pl, 'ladderrank', 0))
        _state.playerlist.setdefault(pl.login, PlayerEntry()).kicked = True
        kicked_nicks.append(whi + nick)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            f'{yel}> {red}You\'ve been Kicked. Bye!', pl.login)
        await aseco.client.query_ignore_result('Kick', pl.login)

    msg = f'{yel}>> {blu}Players: {", ".join(kicked_nicks)}{red} kicked{blu}.'
    await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
    if _state.autorank:
        _autorank(aseco)


async def vote_end(aseco: 'Aseco', _params):
    if _state.current_vote:
        _state.current_vote = False
        _state.vote_item = Vote()


async def info_message(aseco: 'Aseco', _params):
    if _state.infomessages == 0 or _state.nbmessages == 0:
        return
    idx = random.randint(0, _state.nbmessages - 1)
    if idx < len(_state.messages):
        msg = aseco.format_colors(_state.message_start + _state.messages[idx])
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)


# ---------------------------------------------------------------------------
# Checkpoint / finish events
# ---------------------------------------------------------------------------

async def kick_speconly(aseco: 'Aseco', params: list):
    """Kick SpecOnly players who managed to enter the race."""
    if len(params) < 2:
        return
    login = params[1]
    entry = _state.playerlist.get(login)
    if entry and entry.speconly:
        player = aseco.server.players.get_player(login)
        if player:
            whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
            msg = (f'{yel}>> {blu}SpecOnly {whi}{_clean_nick(player.nickname)}'
                   f'{blu} tried to join the race [{red}Kicked{blu}]')
            await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
            aseco.console('[SpecOnly] player "{1}" kicked (rank: {2})',
                          login, getattr(player, 'ladderrank', 0))
            entry.kicked = True
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                f'{_state.yellow}> {_state.red}You\'ve been Kicked. Bye!', login)
            await aseco.client.query_ignore_result('Kick', login)


async def novote_handler(aseco: 'Aseco', chat: list):
    if not _state.novote or len(chat) < 1:
        return
    if chat[0] == aseco.server.id:
        return
    try:
        await aseco.client.query_ignore_result('CancelVote')
    except Exception:
        pass


async def bad_words_handler(aseco: 'Aseco', chat: list):
    if not _state.badwords or len(chat) < 3:
        return
    if chat[0] == aseco.server.id:
        return

    text = strip_colors(chat[2], for_tm=False).lower()
    # Normalise common substitutions
    subs = {'@':'a','0':'o','!':'i','|':'l','á':'a','à':'a','â':'a','ä':'a',
            'é':'e','è':'e','ë':'e','ê':'e','í':'i','ì':'i','ï':'i','î':'i',
            'ó':'o','ò':'o','ö':'o','ô':'o','ú':'u','ù':'u','ü':'u','û':'u'}
    for k, v in subs.items():
        text = text.replace(k, v)
    text = re.sub(r'[\.\*\-_"\']', '', text)
    text = ''.join(text.split())

    login = chat[1]
    for mot in _state.badwordslist:
        if mot.lower() in text:
            player = aseco.server.players.get_player(login)
            if player:
                await _bad_word_found(aseco, login, player.nickname, mot)
            return


async def _bad_word_found(aseco: 'Aseco', login: str, nick: str, word: str):
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    entry = _state.playerlist.setdefault(login, PlayerEntry())
    entry.badwords += 1
    mx = _state.badwordsnum

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        f'{yel}> {red}[ {whi}"{word}"{red} is a forbidden word]', login)

    if _state.badwordsban and entry.badwords > mx:
        mx2 = mx * 2
        msg = (f'{yel}>> {red}Language plz !{blu} ({whi}{_clean_nick(nick)}{blu}: '
               f'{whi}{entry.badwords}{blu}/{whi}{mx2}{blu} to ban) ')
    else:
        msg = (f'{yel}>> {red}Language plz !{blu} ({whi}{_clean_nick(nick)}{blu}: '
               f'{whi}{entry.badwords}{blu}/{whi}{mx}{blu} to kick) ')

    if entry.badwords % mx == 0:
        if _state.badwordsban and entry.badwords > mx:
            msg += f'[{red}Banned for  {whi}{_state.badwordstime}{red} mins{blu}]'
            await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
            entry.badwords = 0
            _ban_for(aseco, login, _state.badwordstime)
        else:
            msg += f'[{red}Kicked{blu}]'
            await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
            aseco.console('[BadWords] player "{1}" kicked', login)
            entry.kicked = True
            entry.badwords = 0
            await aseco.client.query_ignore_result('Kick', login)
    else:
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)


async def pf_kick(aseco: 'Aseco', params: list):
    if not _state.pf or len(params) < 3:
        return
    score = params[2]
    if score == 0:
        return
    if score < (_state.pf - 10):
        login = params[1]
        player = aseco.server.players.get_player(login)
        if not player:
            return
        whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
        msg = (f'{yel}>> {blu}Player {whi}{_clean_nick(player.nickname)}'
               f'{blu} did not PF. ({red}Kicked{blu})')
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
        aseco.console('[NoPfKick] player "{1}" kicked', login)
        _state.playerlist.setdefault(login, PlayerEntry()).kicked = True
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            f'{yel}> {red}You\'ve been Kicked. Bye!', login)
        await aseco.client.query_ignore_result('Kick', login)


# ---------------------------------------------------------------------------
# Vote system
# ---------------------------------------------------------------------------

async def _spec_message(aseco: 'Aseco', login: str):
    whi, yel, blu = _state.white, _state.yellow, _state.blue
    msg = (f'{yel}> {blu}You are {whi}SpecOnly{blu}, ask an admin to be unSpec.\n'
           f'{yel}> {blu}Or use the {whi}/unspec{blu} command to launch a vote.')
    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)


async def _new_vote(aseco: 'Aseco', vote_type: str, login: str):
    whi, yel, red, blu, gre = (_state.white, _state.yellow, _state.red,
                                _state.blue, _state.green)
    _state.vote_item = Vote()
    _state.vote_item.login = login
    _state.vote_item.type  = vote_type
    _state.current_vote    = True
    nb = len(aseco.server.players.all())
    _state.vote_item.nb_votes_needed = max(1, round(nb / 4))

    for pl in aseco.server.players.all():
        _state.playerlist.setdefault(pl.login, PlayerEntry()).hasvoted = 0

    player = aseco.server.players.get_player(login)
    if player and vote_type == 'unspec':
        rank_str = format(getattr(player, 'ladderrank', 0), ',').replace(',', '$n $m')
        msg = (f'{yel}>> {blu}SpecOnly {whi}{_clean_nick(player.nickname)}'
               f'{blu} (Rank: {whi}{rank_str}{blu}) wants to join the race.\n'
               f'{yel}>> {blu}({gre}/yes{blu} | {red}$i/no{blu}): '
               f'{whi}{_state.vote_item.nb_votes_needed}{blu} votes needed.')
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)


async def _vote_yes_no(aseco: 'Aseco', yes: bool, change: bool):
    whi, yel, red, blu, gre = (_state.white, _state.yellow, _state.red,
                                _state.blue, _state.green)
    v = _state.vote_item
    if v.nb_votes_needed == 0:
        await _vote_finish(aseco)
        return
    if yes:
        v.yes += 1
        if change:
            v.no -= 1
    else:
        v.no += 1
        if change:
            v.yes -= 1
    if not change:
        v.total += 1

    if v.total >= v.nb_votes_needed:
        await _vote_finish(aseco)
        return

    remaining = v.nb_votes_needed - v.total
    if remaining > 0 and v.type == 'unspec':
        player = aseco.server.players.get_player(v.login)
        if player:
            msg = (f'{yel}>> {whi}{remaining}{blu} vote{"s" if remaining!=1 else ""}'
                   f' left to unSpec {whi}{_clean_nick(player.nickname)}'
                   f'{blu}$n [ {gre}$n/yes{blu}$n | {red}$n/no{blu}$n ]')
            await aseco.client.query_ignore_result('ChatSendServerMessage', msg)


async def _vote_finish(aseco: 'Aseco'):
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    v = _state.vote_item
    if v.type == 'unspec':
        login = v.login
        player = aseco.server.players.get_player(login)
        if player:
            msg = (f'{yel}>> {blu}Vote result to unSpec {whi}{_clean_nick(player.nickname)}'
                   f'{blu}: {whi}{v.yes}{blu} yes, {whi}{v.no}{blu} no.')
            await aseco.client.query_ignore_result('ChatSendServerMessage', msg)
            if v.yes > v.no:
                _state.playerlist.setdefault(login, PlayerEntry()).speconly = False
                _state.playerlist[login].isvip = True
                msg2 = (f'{yel}>> {blu}The server unSpecs '
                        f'{whi}{_clean_nick(player.nickname)}{blu}.')
                await aseco.client.query_ignore_result('ChatSendServerMessage', msg2)
                if _state.autorank:
                    _autorank(aseco)
            else:
                msg2 = (f'{yel}>> {blu}The server banned '
                        f'{whi}{_clean_nick(player.nickname)}{blu} for {whi}5{blu} mins.')
                await aseco.client.query_ignore_result('ChatSendServerMessage', msg2)
                _ban_for(aseco, login, 5)

    _state.current_vote = False
    _state.vote_item = Vote()
    for pl in aseco.server.players.all():
        _state.playerlist.setdefault(pl.login, PlayerEntry()).hasvoted = 0


# ---------------------------------------------------------------------------
# Player chat commands
# ---------------------------------------------------------------------------

async def chat_ranklimit(aseco: 'Aseco', command: dict):
    whi, yel, blu = _state.white, _state.yellow, _state.blue
    login = command['author'].login
    if _state.ranklimit:
        lmt = _state.autolimit if _state.autorank else _state.limit
        mode = 'Auto-RankLimit' if _state.autorank else 'RankLimit'
        msg = f'{yel}> {blu}{mode}: {whi}{lmt}'
    else:
        msg = f'{yel}> {blu}RankLimit: {whi}OFF{blu}.'
    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)


async def chat_password(aseco: 'Aseco', command: dict):
    whi, yel, blu = _state.white, _state.yellow, _state.blue
    login = command['author'].login
    player = command['author']
    try:
        opts = await aseco.client.query('GetServerOptions')
        if player.isspectator or (_state.playerlist.get(login, PlayerEntry()).speconly):
            pw = opts.get('PasswordForSpectator', '')
            msg = f'{yel}> {blu}Spectator password is: {whi}{pw}{blu}.'
        else:
            pw = opts.get('Password', '')
            msg = f'{yel}> {blu}Player password is: {whi}{pw}{blu}.'
    except Exception:
        msg = f'{yel}> {_state.red}Could not retrieve password.'
    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)


async def chat_unspec(aseco: 'Aseco', command: dict):
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    login = command['author'].login
    entry = _state.playerlist.get(login, PlayerEntry())
    if _state.unspecvote:
        if entry.speconly:
            if not _state.current_vote:
                await _new_vote(aseco, 'unspec', login)
            else:
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessageToLogin',
                    f'{yel}> {blu}Wait until the end of the current vote.', login)
        else:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                f'{yel}> {blu}This command is only for SpecOnly players.', login)
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            f'{yel}> {whi}/unspec{blu} is not currently enabled on this server.', login)


async def chat_yes(aseco: 'Aseco', command: dict):
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    login = command['author'].login
    entry = _state.playerlist.setdefault(login, PlayerEntry())
    if not _state.current_vote:
        return await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}No current vote.', login)
    if entry.speconly:
        return await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}SpecOnly can\'t vote.', login)
    if entry.hasvoted == 0:
        await _vote_yes_no(aseco, True, False)
        entry.hasvoted = 1
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}You have voted {whi}yes{blu}.', login)
    elif entry.hasvoted == 1:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}You have already voted {whi}yes{blu}.', login)
    else:
        await _vote_yes_no(aseco, True, True)
        entry.hasvoted = 1
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}You change your vote to {whi}yes{blu}.', login)


async def chat_no(aseco: 'Aseco', command: dict):
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue
    login = command['author'].login
    entry = _state.playerlist.setdefault(login, PlayerEntry())
    if not _state.current_vote:
        return await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}No current vote.', login)
    if entry.speconly:
        return await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}SpecOnly can\'t vote.', login)
    if entry.hasvoted == 0:
        await _vote_yes_no(aseco, False, False)
        entry.hasvoted = -1
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}You have voted {whi}no{blu}.', login)
    elif entry.hasvoted == -1:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}You have already voted {whi}no{blu}.', login)
    else:
        await _vote_yes_no(aseco, False, True)
        entry.hasvoted = -1
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', f'{yel}> {blu}You change your vote to {whi}no{blu}.', login)


async def chat_message(aseco: 'Aseco', command: dict):
    await info_message(aseco, None)

async def chat_fake(aseco: 'Aseco', command: dict):
    """Kept as a small admin-only testing helper with compact output."""
    player = command['author']
    login = player.login

    if not aseco.is_any_admin(player):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(aseco.get_chat_message('NO_ADMIN')),
            login,
        )
        return

    whi, yel, gre = _state.white, _state.yellow, _state.green
    rank = 1
    time1 = random.randint(20, 30)
    time2 = random.randint(10, 99)

    message = (
        f'{yel}>> {whi}{_clean_nick(player.nickname)}{gre} took the '
        f'{whi}{rank}.{gre} Local Record with a time of '
        f'{whi}00:{time1}.{time2}{gre}! $000(fake)'
    )
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage',
        aseco.format_colors(message),
    )


async def on_player_vote(aseco: 'Aseco', vote_data):
    """Unused compatibility stub; onPlayerVote stays disabled here as well."""
    return


# ---------------------------------------------------------------------------
# /jfreu admin command
# ---------------------------------------------------------------------------

def _wrap_ml_text(text: str, max_len: int = 200) -> list[str]:
    """Wrap Manialink text by visible length."""
    words = text.split()
    if not words:
        return ['']

    lines = []
    current = words[0]

    for word in words[1:]:
        test = f'{current} {word}'
        if len(strip_colors(test)) > max_len:
            lines.append(current)
            current = word
        else:
            current = test

    lines.append(current)
    return lines


async def chat_jfreu(aseco: 'Aseco', command: dict):
    admin = command['author']
    login = admin.login
    whi, yel, red, blu = _state.white, _state.yellow, _state.red, _state.blue

    # Auth check
    if aseco.is_master_admin(admin):
        logtitle = 'MasterAdmin'
        chattitle = 'MasterAdmin'
    elif aseco.is_admin(admin):
        logtitle = 'Admin'
        chattitle = 'Admin'
    elif aseco.is_operator(admin):
        logtitle = 'Operator'
        chattitle = 'Operator'
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            f'{red}You don\'t have the required admin rights to do that!', login)
        return

    raw = command['params'].strip()
    parts = raw.split(None, 1)
    sub   = parts[0].lower() if parts else ''
    arg   = parts[1] if len(parts) > 1 else ''
    args  = arg.split() if arg else []

    async def _reply(msg: str):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)

    async def _broadcast(msg: str):
        await aseco.client.query_ignore_result('ChatSendServerMessage', msg)

    async def _get_target(param: str, offline: bool = False):
        if not param:
            return None
        p = aseco.server.players.get_player(param)
        if p:
            return p
        if offline:
            # Create a stub for offline player lookups
            from pyxaseco.models import Player as _P
            stub = _P()
            stub.login    = param
            stub.nickname = param
            stub.teamname = ''
            stub.ladderrank = 0
            return stub
        await _reply(f'{{#server}}> {{#error}}Player {param!r} not found!')
        return None

    def _bool_val(s: str, on_val='ON', off_val='OFF'):
        su = s.upper()
        if su == on_val:
            return True
        if su == off_val:
            return False
        return None

    # ---- sub-command dispatch ----

    if sub == 'help':
        await _reply(f'{yel}> {blu}Jfreu admin commands: helpall, autochangename, setrank, setlimit, autorank, '
                     f'offset, hardlimit, autorankminplayers, autorankvip, maxplayers, kickhirank, '
                     f'listlimits, kickworst, players, unspec, addvip, removevip, listvips, '
                     f'addvipteam, removevipteam, listvipteams, writelists, readlists, '
                     f'badwords, badwordsban, badwordsnum, badwordstime, badword, '
                     f'banfor, unban, listbans, message, player, nopfkick, cancel, '
                     f'novote, unspecvote, infomessages, writeconfig, readconfig')

    elif sub == 'helpall':
        header = 'Jfreu admin command groups:'
        groups = [
            ('General', 'help, helpall, autochangename, setrank, setlimit, autorank, offset, hardlimit'),
            ('Autorank', 'autorankminplayers, autorankvip, maxplayers, kickhirank, listlimits, kickworst'),
            ('Players', 'players, unspec, message, player, nopfkick, cancel'),
            ('VIP', 'addvip, removevip, listvips, addvipteam, removevipteam, listvipteams, writelists, readlists'),
            ('BadWords/Bans', 'badwords, badwordsban, badwordsnum, badwordstime, badword, banfor, unban, listbans'),
            ('Other', 'novote, unspecvote, infomessages, writeconfig, readconfig'),
        ]
    
        help_rows = []
        for group_name, cmd_text in groups:
            wrapped = _wrap_ml_text(cmd_text, 100)
            help_rows.append([group_name, '{#black}' + wrapped[0]])
            for extra_line in wrapped[1:]:
                help_rows.append(['', '{#black}' + extra_line])
    
        display_manialink(
            aseco,
            login,
            header,
            ['Icons128x128_1', 'ProfileAdvanced', 0.02],
            help_rows,
            [1.35, 0.30, 1.00],
            'OK'
        )

    elif sub == 'autochangename':
        val = _bool_val(arg)
        if val is not None:
            _state.autochangename = val
            aseco.console('{1} [{2}] set autochangename: {3}', logtitle, login, 'ON' if val else 'OFF')
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set AutoChangeName: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
            await _set_server_name(aseco)
        else:
            await _reply(f'{yel}> {blu}AutoChangeName is: {whi}{"ON" if _state.autochangename else "OFF"}{blu}.')

    elif sub == 'setrank':
        val = _bool_val(arg)
        if val is not None:
            _state.ranklimit = val
            aseco.console('{1} [{2}] set rank limiting: {3}', logtitle, login, 'ON' if val else 'OFF')
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set RankLimit: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}RankLimit is: {whi}{"ON" if _state.ranklimit else "OFF"}{blu}.')

    elif sub == 'setlimit':
        if arg and arg.isdigit() and 0 < int(arg) < 2000000:
            v = int(arg)
            auto_mode = 2 if _state.autorank else 0
            set_ranklimit(aseco, v, auto_mode)
            _write_config_xml()
            aseco.console('{1} [{2}] set (auto)ranklimit: {3}', logtitle, login, v)
            await _set_server_name(aseco)
        else:
            await _reply(f'{yel}> {blu}RankLimit value is: {whi}{_state.limit}{blu}.')

    elif sub == 'autorank':
        val = _bool_val(arg)
        if val is not None:
            _state.autorank = val
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set AutoRank: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            if val:
                _autorank(aseco)
            else:
                set_ranklimit(aseco, _state.limit, 0)
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}AutoRank is: {whi}{"ON" if _state.autorank else "OFF"}{blu}.')

    elif sub == 'offset':
        if arg and arg.lstrip('-').isdigit() and -1000 < int(arg) < 1000:
            _state.offset = int(arg)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set AutoRank Offset to: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _state.offset)
            await _broadcast(aseco.format_colors(msg))
            _autorank(aseco)
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}AutoRank Offset: {whi}{_state.offset}{blu}.')

    elif sub == 'hardlimit':
        if arg and arg.isdigit():
            _state.hardlimit = int(arg)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set HardLimit to: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _state.hardlimit)
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            if _state.hardlimit:
                await _reply(f'{yel}> {blu}HardLimit: {whi}{_state.hardlimit}{blu}.')
            else:
                await _reply(f'{yel}> {blu}HardLimit is: {whi}OFF{blu}.')

    elif sub == 'autorankminplayers':
        if arg and arg.isdigit() and 0 <= int(arg) < 50:
            _state.autorankminplayers = int(arg)
            aseco.console('{1} [{2}] set autorankminplayers: {3}', logtitle, login, _state.autorankminplayers)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set AutoRankMinPlayer to: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _state.autorankminplayers)
            await _broadcast(aseco.format_colors(msg))
            _autorank(aseco)
            _write_config_xml()
        elif arg:
            await _reply(aseco.format_colors('{#server}> {#highlite}' + arg + '{#error} is not a valid minplayers value!'))
        else:
            await _reply(f'{yel}> {blu}AutoRankMinPlayer value is: {whi}{_state.autorankminplayers}{blu}.')

    elif sub == 'autorankvip':
        val = _bool_val(arg)
        if val is not None:
            _state.autorankvip = val
            aseco.console('{1} [{2}] set autorankvip: {3}', logtitle, login, 'ON' if val else 'OFF')
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set AutoRankVIP: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}AutoRankVIP is: {whi}{"ON" if _state.autorankvip else "OFF"}{blu}.')

    elif sub == 'maxplayers':
        if arg and arg.isdigit() and 0 <= int(arg) < 150:
            _state.maxplayers = int(arg)
            aseco.console('{1} [{2}] set maxplayers: {3}', logtitle, login, _state.maxplayers)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set MaxPlayers to: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _state.maxplayers)
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        elif arg:
            await _reply(aseco.format_colors('{#server}> {#highlite}' + arg + '{#error} is not a valid maxplayers value!'))
        else:
            await _reply(f'{yel}> {blu}MaxPlayers value is: {whi}{_state.maxplayers}{blu}.')

    elif sub == 'kickhirank':
        val = _bool_val(arg)
        if val is not None:
            _state.kickhirank = val
            aseco.console('{1} [{2}] set kickhirank: {3}', logtitle, login, 'ON' if val else 'OFF')
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set KickHiRank: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}KickHiRank is: {whi}{"ON" if _state.kickhirank else "OFF"}{blu}.')

    elif sub == 'listlimits':
        header = 'Current rank limit settings:'
        rows = [
            ['Rank limiting',      '{#black}' + ('ON' if _state.ranklimit else 'OFF')],
            ['Rank limit',         '{#black}' + str(_state.limit)],
            ['Hard limit',         '{#black}' + str(_state.hardlimit)],
            ['Auto ranking',       '{#black}' + ('ON' if _state.autorank else 'OFF')],
            ['Autorank offset',    '{#black}' + str(_state.offset)],
            ['Autorank limit',     '{#black}' + str(_state.autolimit)],
            ['Autorank minplayers','{#black}' + str(_state.autorankminplayers)],
            ['Autorank VIP',       '{#black}' + ('ON' if _state.autorankvip else 'OFF')],
            ['Maxplayers HiRank',  '{#black}' + str(_state.maxplayers)],
            ['KickHiRank',         '{#black}' + ('ON' if _state.kickhirank else 'OFF')],
        ]
        display_manialink(aseco, login, header,
                          ['Icons128x128_1', 'ProfileAdvanced', 0.02],
                          rows, [0.8, 0.4, 0.4], 'OK')

    elif sub == 'kickworst':
        if arg and arg.isdigit() and 0 < int(arg) < 50:
            n = int(arg)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} kicks the {#highlite}{3}{#message} worst ranked player{4}.',
                              chattitle, admin.nickname, n, 's' if n != 1 else '')
            await _broadcast(aseco.format_colors(msg))
            await _kick_worst(aseco, n)

    elif sub == 'players':
        search = arg.strip()
        onlineonly = search.lower() == 'live'
        if not hasattr(admin, 'panels') or not isinstance(admin.panels, dict):
            admin.panels = {}
        admin.panels['plyparam'] = search
        admin.playerlist = []

        online_map = {}
        try:
            plist = await aseco.client.query('GetPlayerList', 300, 0, 1)
        except TypeError:
            plist = await aseco.client.query('GetPlayerList', 300, 0)
        except Exception:
            plist = []
        for pl in (plist or []):
            login2 = pl.get('Login', '')
            if login2:
                online_map[login2] = {'login': login2, 'spec': bool(pl.get('SpectatorStatus') or pl.get('IsSpectator'))}

        playerlist = {}
        if onlineonly:
            for pl_login, entry in _state.playerlist.items():
                if pl_login in online_map:
                    playerlist[pl_login] = entry
        else:
            for pl_login, entry in _state.playerlist.items():
                if not search or search.lower() in pl_login.lower():
                    playerlist[pl_login] = entry
            for vip_login in _state.vip_list:
                if vip_login and vip_login not in playerlist and (not search or search.lower() in vip_login.lower()):
                    _add_player(vip_login, True, False)
                    playerlist[vip_login] = _state.playerlist[vip_login]

        if not playerlist:
            await _reply(aseco.format_colors('{#server}> {#error}No player(s) found!'))
            return

        head = ('Online' if onlineonly else 'Known') + ' Players On This Server:'
        rows = []
        if _state.badwords:
            rows.append(['Id', '{#nick}Nick $g/{#login} Login', '$nCount', 'BadW', 'Ban', 'Ban', 'Left', 'UnBan', 'VIP', 'Spec'])
        else:
            rows.append(['Id', '{#nick}Nick $g/{#login} Login', 'Ban', 'Ban', 'Left', 'UnBan', 'VIP', 'Spec'])

        now = _time.time()
        for pid, (pl_login, entry) in enumerate(playerlist.items(), 1):
            admin.playerlist.append({'login': pl_login})
            nick = strip_colors(_get_player_nick(aseco, pl_login))
            is_admin_login = False
            try:
                is_admin_login = aseco.is_any_admin_login(pl_login)
            except Exception:
                is_admin_login = False
            ply = '{#black}' + nick + '$z / ' + ('{#logina}' if is_admin_login else '{#login}') + pl_login
            bdw = '$ff3+1'
            bn1 = '$f301Hour'
            bn2 = '$f0324H'
            ubn = '$c3fUnBan'
            gst = '$3c3Add'
            ugt = '$393Remove'
            usp = '$09fUnSpec'
            off = '$09cOffln'
            plr = '$09cPlayer'
            spc = '$09cSpec'
            remain = False
            if entry.banned > now:
                remain_m = round((entry.banned - now) / 60)
                remain = f'{remain_m//60}h{remain_m%60:02d}' if remain_m > 60 else str(remain_m)
            if pid <= 200:
                ply = [ply, pid + 2000]
                if pl_login in online_map:
                    bdw = [bdw, -4000 - pid]
                    bn1 = [bn1, -4200 - pid]
                    bn2 = [bn2, -4400 - pid]
                    if remain is not False:
                        ubn = [ubn, -4600 - pid]
                    gst = [ugt if pl_login in _state.vip_list else gst, -5000 - pid]
                    if entry.speconly:
                        spc = [usp, -5200 - pid]
                    elif not online_map[pl_login]['spec']:
                        spc = plr
                else:
                    bn1 = [bn1, -4200 - pid]
                    bn2 = [bn2, -4400 - pid]
                    if remain is not False:
                        ubn = [ubn, -4600 - pid]
                    gst = [ugt if pl_login in _state.vip_list else gst, -5000 - pid]
                    spc = off
            else:
                if pl_login in _state.vip_list:
                    gst = ugt
                if pl_login in online_map:
                    if entry.speconly:
                        spc = usp
                    elif not online_map[pl_login]['spec']:
                        spc = plr
                else:
                    spc = off
            if _state.badwords:
                rows.append([f'{pid:02d}.', ply, entry.badwords, bdw, bn1, bn2, (remain if remain is not False else 'none'), ubn, gst, spc])
            else:
                rows.append([f'{pid:02d}.', ply, bn1, bn2, (remain if remain is not False else 'none'), ubn, gst, spc])

        pages = [rows[i:i+15] for i in range(0, len(rows), 15)]
        admin.msgs = [[1, head,
                       [1.591, 0.15, 0.5, 0.10, 0.12, 0.12, 0.12, 0.12, 0.121, 0.12, 0.12] if _state.badwords else
                       [1.371, 0.15, 0.5, 0.12, 0.12, 0.12, 0.121, 0.12, 0.12],
                       ['Icons128x128_1', 'Buddies']]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub == 'unspec':
        if not arg:
            return
        target = await _get_target(arg)
        if not target:
            return
        entry = _state.playerlist.get(target.login)
        if entry and entry.speconly:
            entry.speconly = False
            entry.isvip    = True
            aseco.console('{1} [{2}] unSpec-ed [{3}]', logtitle, login, target.login)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} unSpecs {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _clean_nick(target.nickname))
            await _broadcast(aseco.format_colors(msg))
            if _state.autorank:
                _autorank(aseco)
        else:
            await _reply(f'{yel}> {red}Login: {whi}{target.login}{red} is not SpecOnly!')

    elif sub == 'addvip':
        target = await _get_target(arg)
        if not target:
            return
        if target.login in _state.vip_list:
            await _reply(f'{yel}> {blu}Login: {whi}{target.login}{blu} is already in VIP list.')
            return
        _state.vip_list.append(target.login)
        _write_lists_xml()
        aseco.console('{1} [{2}] adds VIP [{3}]', logtitle, login, target.login)
        await _broadcast(f'{yel}>> {blu}New VIP: {whi}{target.login}{blu} / {whi}{_clean_nick(target.nickname)}.')
        _state.playerlist.setdefault(target.login, PlayerEntry()).isvip = True

    elif sub == 'removevip':
        target = await _get_target(arg, offline=True)
        if not target:
            return
        if target.login not in _state.vip_list:
            await _reply(f'{yel}> {blu}Login: {whi}{target.login}{blu} is not in VIP list.')
            return
        _state.vip_list.remove(target.login)
        _write_lists_xml()
        aseco.console('{1} [{2}] removes VIP [{3}]', logtitle, login, target.login)
        await _broadcast(f'{yel}>> {blu}Login: {whi}{target.login}{blu} removed from VIP list.')
        if target.login in _state.playerlist:
            _state.playerlist[target.login].isvip = False

    elif sub == 'listvips':
        head = 'Current VIPs:'
        rows = [['Id', '{#nick}Nick $g/{#login} Login']]
        admin.playerlist = []
        for i, lgn in enumerate([v for v in _state.vip_list if v], 1):
            admin.playerlist.append({'login': lgn})
            nick = _get_player_nick(aseco, lgn)
            ply = f'{{#black}}{strip_colors(nick)}$z / {{#login}}{lgn}'
            rows.append([f'{i:02d}.', ply])
        pages = [rows[i:i+15] for i in range(0, max(len(rows),1), 15)]
        admin.msgs = [[1, head, [0.9, 0.1, 0.8], ['Icons128x128_1', 'Invite']]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub == 'addvipteam':
        team = arg.strip()
        if not team:
            return
        if team in _state.vip_team_list:
            await _reply(f'{yel}> {blu}Team: {whi}{team}{blu} is already in VIP_Team list.')
            return
        _state.vip_team_list.append(team)
        _write_lists_xml()
        await _broadcast(f'{yel}>> {blu}New VIP_Team: {whi}{team}{blu}.')

    elif sub == 'removevipteam':
        team = arg.strip()
        if team not in _state.vip_team_list:
            await _reply(f'{yel}> {blu}Team: {whi}{team}{blu} is not in VIP_Team list.')
            return
        _state.vip_team_list.remove(team)
        _write_lists_xml()
        await _broadcast(f'{yel}>> {blu}Team: {whi}{team}{blu} removed from VIP_Team list.')

    elif sub == 'listvipteams':
        head = 'Current VIP_Teams:'
        rows = [['Id', '{#nick}Team$g (click to Remove)' if aseco.settings.clickable_lists else '{#nick}Team']]
        admin.playerlist = []
        for i, team in enumerate([t for t in _state.vip_team_list if t], 1):
            admin.playerlist.append({'login': team})
            team_cell = ['{#black}' + team, -5800 - i] if aseco.settings.clickable_lists else '{#black}' + team
            rows.append([f'{i:02d}.', team_cell])
        if len(rows) == 1:
            await _reply(aseco.format_colors('{#server}> {#error}No VIP_Team(s) found!'))
            return
        pages = [rows[i:i+15] for i in range(0, len(rows), 15)]
        admin.msgs = [[1, head, [0.8, 0.1, 0.7], ['Icons128x128_1', 'Invite']]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub == 'writelists':
        _write_lists_xml()
        await _reply(f'{yel}> {whi}Jfreu lists{yel} written.')

    elif sub == 'readlists':
        _state.vip_list = []
        _state.vip_team_list = []
        _read_lists_xml(aseco)
        await _read_guest_list(aseco)
        await _reply(f'{yel}> {whi}Jfreu lists{yel} read.')

    elif sub == 'badwords':
        val = _bool_val(arg)
        if val is not None:
            _state.badwords = val
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set BadWords bot: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}BadWords is: {whi}{"ON" if _state.badwords else "OFF"}{blu}.')

    elif sub == 'badwordsban':
        val = _bool_val(arg)
        if val is not None:
            _state.badwordsban = val
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set BadWordsBan: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}BadWordsBan is: {whi}{"ON" if _state.badwordsban else "OFF"}{blu}.')

    elif sub == 'badwordsnum':
        if arg and arg.isdigit() and 0 < int(arg) < 10:
            _state.badwordsnum = int(arg)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set BadWordsNum to: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _state.badwordsnum)
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}BadWordsNum: {whi}{_state.badwordsnum}{blu}.')

    elif sub == 'badwordstime':
        if arg and arg.isdigit() and 0 < int(arg) <= 24*60:
            _state.badwordstime = int(arg)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set BadWordsTime to: {#highlite}{3}{#message} mins.',
                              chattitle, admin.nickname, _state.badwordstime)
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}BadWordsTime: {whi}{_state.badwordstime}{blu} mins.')

    elif sub == 'badword':
        target = await _get_target(arg)
        if target:
            await _bad_word_found(aseco, target.login, target.nickname, '')

    elif sub == 'banfor':
        if len(args) < 2:
            return
        time_str, target_str = args[0], args[1]
        target = await _get_target(target_str, offline=True)
        if not target:
            return
        if time_str.lower().endswith('h'):
            try:
                minutes = int(time_str[:-1]) * 60
            except ValueError:
                await _reply(f'{yel}> {whi}{time_str}{red} is not a valid time!')
                return
        else:
            try:
                minutes = int(time_str)
            except ValueError:
                await _reply(f'{yel}> {whi}{time_str}{red} is not a valid time!')
                return
        ban_str = _fmt_ban_time(minutes, whi, red)
        msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} bans {#highlite}{3}{#message} for {#highlite}{4}.',
                          chattitle, admin.nickname, _clean_nick(target.nickname), ban_str)
        await _broadcast(aseco.format_colors(msg))
        _ban_for(aseco, target.login, minutes)

    elif sub == 'unban':
        target = await _get_target(arg, offline=True)
        if not target:
            return
        entry = _state.playerlist.get(target.login)
        if entry and entry.banned > 0:
            entry.banned = 0
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} unbans {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _clean_nick(target.nickname))
            await _broadcast(aseco.format_colors(msg))
            _write_bans_xml()
        else:
            await _reply(f'{yel}> {whi}{target.login}{red} is not a banned player!')

    elif sub == 'listbans':
        now = _time.time()
        head = 'Temporarily Banned Players:'
        rows = [['Id', '{#nick}Nick $g/{#login} Login$g (click to UnBan)', '{#black}Time']]
        admin.playerlist = []
        i = 1
        for lgn, entry in _state.playerlist.items():
            if entry.banned > now:
                remain = round((entry.banned - now) / 60)
                remain_str = f'{remain//60}h{remain%60:02d}' if remain > 60 else str(remain)
                admin.playerlist.append({'login': lgn})
                nick = _get_player_nick(aseco, lgn)
                ply = f'{{#black}}{strip_colors(nick)}$z / {{#login}}{lgn}'
                if aseco.settings.clickable_lists and i <= 200:
                    ply = [ply, -5400 - i]
                rows.append([f'{i:02d}.', ply, '{#black}' + remain_str])
                i += 1
        pages = [rows[j:j+15] for j in range(0, max(len(rows),1), 15)]
        admin.msgs = [[1, head, [1.1, 0.1, 0.8, 0.2], ['Icons64x64_1', 'NotBuddy']]]
        admin.msgs.extend(pages)
        display_manialink_multi(aseco, admin)

    elif sub == 'message' and arg:
        msg = f'{whi}[{aseco.server.name}{whi}] $z$s{arg}'
        await _broadcast(msg)

    elif sub == 'player' and arg:
        target = _get_player_param(aseco, admin, args[0] if args else '', False)
        if not target:
            await _reply(f'{{#server}}> {{#error}}Player {(args[0] if args else "")!r} not found!')
            return
        text_msg = arg.split(' ', 1)
        if len(text_msg) < 2 or not text_msg[1]:
            await _reply(f'{{#server}}> {{#error}}Unknown Jfreu command or missing params: {{#highlite}}$i {raw}')
            return
        await _broadcast(f'$z[{target.nickname}$z] {text_msg[1]}')

    elif sub == 'nopfkick':
        if arg:
            au = arg.upper()
            if au in ('OFF', '0'):
                _state.pf = 0
                msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set NoPfKick: {#highlite}{3}{#message}.',
                                  chattitle, admin.nickname, 'OFF')
                await _broadcast(aseco.format_colors(msg))
                _write_config_xml()
            elif arg.isdigit() and 0 < int(arg) < 600000:
                _state.pf = int(arg)
                msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set NoPfKick time: {#highlite}{3}{#message}.',
                                  chattitle, admin.nickname, _state.pf)
                await _broadcast(aseco.format_colors(msg))
                _write_config_xml()
            else:
                await _reply(f'{yel}> {blu}Map {whi}{arg}{blu} is not in PF list.')
                return
            aseco.console('{1} [{2}] set NoPfKick: {3}', logtitle, login, _state.pf)
        else:
            await _reply(f'{yel}> {blu}NoPfKick is: {whi}{"OFF" if _state.pf == 0 else "ON"}{blu}.')

    elif sub == 'cancel':
        try:
            await aseco.client.query_ignore_result('CancelVote')
            await _broadcast(f'{yel}>> {blu}Vote canceled.')
        except Exception:
            pass

    elif sub == 'novote':
        val = _bool_val(arg)
        if val is not None:
            _state.novote = val
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set NoVote: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}NoVote is: {whi}{"ON" if _state.novote else "OFF"}{blu}.')

    elif sub == 'unspecvote':
        val = _bool_val(arg)
        if val is not None:
            _state.unspecvote = val
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set UnSpecVote: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, 'ON' if val else 'OFF')
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}UnSpecVote is: {whi}{"ON" if _state.unspecvote else "OFF"}{blu}.')

    elif sub == 'infomessages':
        if arg and arg.isdigit() and 0 <= int(arg) <= 2:
            _state.infomessages = int(arg)
            msg = format_text('{#server}>> {#message}{1}$z$s {#highlite}{2}$z$s{#message} set InfoMessages: {#highlite}{3}{#message}.',
                              chattitle, admin.nickname, _state.infomessages)
            await _broadcast(aseco.format_colors(msg))
            _write_config_xml()
        else:
            await _reply(f'{yel}> {blu}InfoMessages is: {whi}{_state.infomessages}{blu}.')

    elif sub == 'writeconfig':
        _write_config_xml()
        await _reply(f'{yel}> {whi}Jfreu config{yel} written.')

    elif sub == 'readconfig':
        _load_config(aseco)
        await _reply(f'{yel}> {whi}Jfreu config{yel} read.')

    else:
        await _reply(f'{{#server}}> {{#error}}Unknown Jfreu command or missing params: {{#highlite}}$i {raw}')


# ---------------------------------------------------------------------------
# ManiaLink click handler for /jfreu player list buttons
# ---------------------------------------------------------------------------

async def event_jfreu(aseco: 'Aseco', answer: list):
    if len(answer) < 3:
        return
    action = int(answer[2])

    # Action ranges for jfreu buttons: -6000 to -4001
    if not (-6000 <= action <= -4001):
        return

    login  = answer[1]
    player = aseco.server.players.get_player(login)
    if not player:
        return

    param = getattr(getattr(player, 'panels', {}), 'get', lambda k, d='': d)('plyparam', '') \
            if hasattr(player, 'panels') and isinstance(player.panels, dict) \
            else ''

    async def _dispatch(params_str: str):
        await chat_jfreu(aseco, {'author': player, 'params': params_str})

    async def _refresh():
        await _dispatch(f'players {param}')

    if -4200 <= action <= -4001:
        idx = abs(action) - 4001
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            aseco.console('player {1} clicked /jfreu badword {2}', login, target)
            await _dispatch(f'badword {target}')
            await _refresh()

    elif -4400 <= action <= -4201:
        idx = abs(action) - 4201
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'banfor 1H {target}')
            await _refresh()

    elif -4600 <= action <= -4401:
        idx = abs(action) - 4401
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'banfor 24H {target}')
            await _refresh()

    elif -4800 <= action <= -4601:
        idx = abs(action) - 4601
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'unban {target}')
            await _refresh()

    elif -5000 <= action <= -4801:
        idx = abs(action) - 4801
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'addvip {target}')
            await _refresh()

    elif -5200 <= action <= -5001:
        idx = abs(action) - 5001
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'removevip {target}')
            await _refresh()

    elif -5400 <= action <= -5201:
        idx = abs(action) - 5201
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'unspec {target}')
            await _refresh()

    elif -5600 <= action <= -5401:
        idx = abs(action) - 5401
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'unban {target}')
            # Check if bans remain
            now = _time.time()
            if any(e.banned > now for e in _state.playerlist.values()):
                await _dispatch('listbans')

    elif -5800 <= action <= -5601:
        idx = abs(action) - 5601
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'removevip {target}')
            if any(v for v in _state.vip_list if v):
                await _dispatch('listvips')

    elif -6000 <= action <= -5801:
        idx = abs(action) - 5801
        if idx < len(player.playerlist):
            target = player.playerlist[idx]['login']
            await _dispatch(f'removevipteam {target}')
            if any(t for t in _state.vip_team_list if t):
                await _dispatch('listvipteams')


def _get_player_nick(aseco: 'Aseco', login: str) -> str:
    pl = aseco.server.players.get_player(login)
    return pl.nickname if pl else login


def _get_player_param(aseco, requester, param: str, offline: bool = False):
    """Find a player by login or numeric ID from a parameter string."""
    if not param or not param.strip():
        return None
    param = param.strip()
    # Numeric ID -> look up in requester's playerlist
    if param.isdigit():
        pid = int(param) - 1
        pl_list = getattr(requester, 'playerlist', [])
        if 0 <= pid < len(pl_list):
            entry = pl_list[pid]
            param = entry.get('login', '') if isinstance(entry, dict) else str(entry)
    # Try online players
    player = aseco.server.players.get_player(param)
    if player:
        return player
    if offline:
        from pyxaseco.models import Player as _P
        stub = _P()
        stub.login    = param
        stub.nickname = param
        stub.teamname = ''
        stub.ladderrank = 0
        return stub
    return None
