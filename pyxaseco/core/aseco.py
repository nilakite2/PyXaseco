"""
Aseco — the main controller for PyXaseco.

Port of the Aseco class in aseco.php.

Responsibilities:
  - Connect to the dedicated server
  - Load config, plugins, admin lists
  - Run the main async event loop
  - Dispatch GbxRemote callbacks to registered plugin handlers
  - Manage player connect/disconnect, challenge changes, chat commands
  - Provide helper API used by plugins

TMF-only.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from pyxaseco.core.gbx_client import GbxClient, GbxError
from pyxaseco.core.event_bus import EventBus
from pyxaseco.core.config import (
    Settings, load_config, load_adminops, load_bannedips, load_plugins_list
)
from pyxaseco.core.plugin_loader import PluginLoader
from pyxaseco.models import (
    Player, PlayerList, Challenge, Gameinfo, Server, ChatCommand,
    Record, RecordList
)

logger = logging.getLogger(__name__)

PYXASECO_VERSION = '1.0-Alpha'
TMF_BUILD = '2011-02-21'   # minimum required TMF dedicated server build

# Dedicated server callbacks we handle
_CALLBACK_MAP: dict[str, str] = {
    'TrackMania.PlayerConnect':               '_cb_player_connect',
    'TrackMania.PlayerDisconnect':            '_cb_player_disconnect',
    'TrackMania.PlayerChat':                  '_cb_player_chat',
    'TrackMania.PlayerFinish':                '_cb_player_finish',
    'TrackMania.PlayerCheckpoint':            '_cb_player_checkpoint',
    'TrackMania.PlayerInfoChanged':           '_cb_player_info_changed',
    'TrackMania.PlayerServerMessageAnswer':   '_cb_player_server_msg_answer',
    'TrackMania.PlayerManialinkPageAnswer':   '_cb_manialink_answer',
    'TrackMania.BeginChallenge':              '_cb_begin_challenge',
    'TrackMania.EndChallenge':                '_cb_end_challenge',
    'TrackMania.EndRound':                    '_cb_end_round',
    'TrackMania.BeginRound':                  '_cb_begin_round',
    'TrackMania.StatusChanged':               '_cb_status_changed',
    'TrackMania.BillUpdated':                 '_cb_bill_updated',
    'TrackMania.ChallengeListModified':       '_cb_challenge_list_modified',
    'TrackMania.PlayerIncoherence':           '_cb_player_incoherence',
    'TrackMania.VoteUpdated':                 '_cb_vote_updated',
    'TrackMania.Echo':                        '_cb_echo',
    'TrackMania.TunnelDataReceived':          '_cb_tunnel_data',
    'TrackMania.ManualFlowControlTransition': '_cb_flow_transition',
    'TrackMania.ChallengeRestart':              '_cb_challenge_restart',
}


class Aseco:
    """Main Xaseco controller."""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.client = GbxClient()
        self.events = EventBus()
        self.settings = Settings()
        self.server = Server('127.0.0.1', 5000, 'SuperAdmin', 'SuperAdmin')

        # Runtime state
        self.startup_phase: bool = True
        self.warmup_phase: bool = False
        self.restarting: int = 0       # 0=no, 1=instant, 2=chattime
        self.changingmode: bool = False
        self.currstatus: int = 0
        self.prevstatus: int = 0
        self.uptime: int = int(time.time())
        self._shutdown_requested: bool = False
        self._shutdown_stop_server: bool = False
        self._restart_requested: bool = False

        # Chat commands: name → ChatCommand
        self._chat_commands: dict[str, ChatCommand] = {}

        # Plugins
        self._plugins: list[str] = []

        # Logging
        self._logfile: Optional[Any] = None
        self._chatlogfile: Optional[Any] = None

        # Plugin loader
        self._plugin_loader: Optional[PluginLoader] = None

        logger.info('PyXaseco %s initialising', PYXASECO_VERSION)

    # ------------------------------------------------------------------
    # Public plugin API
    # ------------------------------------------------------------------

    def register_event(self, event_type: str, handler):
        """Register a handler for a named event (e.g. 'onChat')."""
        self.events.register(event_type, handler)

    def release_event(self, event_type: str, param: Any = None):
        """Schedule an event fire. Returns a coroutine — must be awaited."""
        return self.events.fire(event_type, self, param)

    def add_chat_command(self, name: str, help_text: str, is_admin: bool = False):
        """Register a chat command (e.g. '/help')."""
        cmd = ChatCommand(name, help_text, is_admin)
        self._chat_commands[name] = cmd
        if self.debug:
            logger.debug('ChatCommand registered: /%s', name)

    def get_chat_message(self, name: str) -> str:
        """Return a configured chat message by key."""
        msgs = self.settings.chat_messages
        items = msgs.get(name.upper(), [''])
        raw = items[0] if items else ''
        return self.format_colors(html.unescape(raw))

    # -- Admin checks --

    def ip_match(self, playerip: str, listip: str) -> bool:
        """
        Check if playerip matches listip (exact, class C wildcard .*, or class B wildcard .*.*).
        Comma-separated IPs are supported.
        """
        if playerip == '':
            return True  # offline player
        for ip in listip.split(','):
            ip = ip.strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                if playerip == ip:
                    return True
            elif ip.endswith('.*.*'):
                prefix = ip[:-4]
                if re.sub(r'\.\d+\.\d+$', '', playerip) == prefix:
                    return True
            elif ip.endswith('.*'):
                prefix = ip[:-2]
                if re.sub(r'\.\d+$', '', playerip) == prefix:
                    return True
        return False

    def _check_in_list(self, player: Player, login_list: list, ip_list: list,
                       list_name: str) -> bool:
        if not player.login:
            return False
        try:
            idx = login_list.index(player.login)
        except ValueError:
            return False
        ip = ip_list[idx] if idx < len(ip_list) else ''
        if ip and not self.ip_match(player.ip, ip):
            logger.warning("Attempt to use %s login '%s' from IP %s",
                           list_name, player.login, player.ip)
            return False
        return True

    def is_master_admin(self, player: Player) -> bool:
        ma = self.settings.masteradmin_list
        return self._check_in_list(player, ma.get('TMLOGIN', []),
                                   ma.get('IPADDRESS', []), 'MasterAdmin')

    def is_admin(self, player: Player) -> bool:
        al = self.settings.admin_list
        return self._check_in_list(player, al.get('TMLOGIN', []),
                                   al.get('IPADDRESS', []), 'Admin')

    def is_operator(self, player: Player) -> bool:
        ol = self.settings.operator_list
        return self._check_in_list(player, ol.get('TMLOGIN', []),
                                   ol.get('IPADDRESS', []), 'Operator')

    def is_any_admin(self, player: Player) -> bool:
        return self.is_master_admin(player) or self.is_admin(player) or self.is_operator(player)

    def is_master_admin_login(self, login: str) -> bool:
        return login in self.settings.masteradmin_list.get('TMLOGIN', [])

    def is_admin_login(self, login: str) -> bool:
        return login in self.settings.admin_list.get('TMLOGIN', [])

    def is_operator_login(self, login: str) -> bool:
        return login in self.settings.operator_list.get('TMLOGIN', [])

    def allow_admin_ability(self, ability: str) -> bool:
        key = ability.upper()
        items = self.settings.adm_abilities.get(key, []) if isinstance(
            self.settings.adm_abilities, dict) else []
        return bool(items[0]) if items else False

    def allow_op_ability(self, ability: str) -> bool:
        key = ability.upper()
        items = self.settings.op_abilities.get(key, []) if isinstance(
            self.settings.op_abilities, dict) else []
        return bool(items[0]) if items else False

    def allow_ability(self, player: Player, ability: str) -> bool:
        if self.settings.lock_password and not player.unlocked:
            return False
        if self.is_master_admin(player):
            return True
        if self.is_admin(player):
            return self.allow_admin_ability(ability)
        if self.is_operator(player):
            return self.allow_op_ability(ability)
        return False

    # -- Color formatting --

    def format_colors(self, text: str) -> str:
        if not text:
            return text
    
        colors = self.settings.chat_colors if isinstance(self.settings.chat_colors, dict) else {}
    
        def repl(match):
            key = match.group(1)
            val = colors.get(key)
            if isinstance(val, list):
                val = val[0] if val else ''
            return str(val) if val else match.group(0)
    
        return re.sub(r'\{#?(\w+)\}', repl, text)

    def strip_colors(self, text: str) -> str:
        """Strip Maniaplanet colour codes ($xxx) from a string."""
        return re.sub(r'\$(?:[0-9a-fA-F]{1,3}|[lLsShHiIoOpP]|<|>|\[|\])', '', text)

    def format_time(self, ms: int) -> str:
        """Format milliseconds as M:SS.mmm"""
        if ms < 0:
            return '-' + self.format_time(-ms)
        minutes = ms // 60000
        seconds = (ms % 60000) // 1000
        millis = ms % 1000
        return f'{minutes}:{seconds:02d}.{millis:03d}'

    # -- Console output --

    def console(self, message: str, *args):
        """Log a message to stdout and logfile."""
        for i, arg in enumerate(args, 1):
            message = message.replace('{' + str(i) + '}', str(arg))
        print(message)
        self._do_log(message + '\n')

    def console_text(self, message: str, *args):
        """Alias for console()."""
        self.console(message, *args)

    def _do_log(self, text: str):
        """Write to the log file."""
        try:
            Path('logfile.txt').open('a').write(text)
        except Exception:
            pass

    async def shutdown(self, stop_server: bool = False):
        """
        Request a graceful shutdown of PyXaseco.
        If stop_server=True, also try to stop the dedicated server.
        """
        self._shutdown_requested = True
        self._shutdown_stop_server = bool(stop_server)

        logger.info('Shutdown requested (stop_server=%s)', stop_server)

        # Let plugins react if they want to.
        try:
            await self.release_event('onShutdown', {'stop_server': stop_server})
        except Exception as e:
            logger.warning('onShutdown event failed: %s', e)

    async def restart(self):
        """
        Request a full controller restart.
        The process re-exec is handled by main.py after the run loop exits.
        """
        self._restart_requested = True
        self._shutdown_requested = True
        self._shutdown_stop_server = False

        logger.info('Restart requested')

        try:
            await self.release_event('onShutdown', {
                'stop_server': False,
                'restart': True,
            })
        except Exception as e:
            logger.warning('onShutdown event failed during restart: %s', e)

    @property
    def restart_requested(self) -> bool:
        return bool(self._restart_requested)

    async def _perform_shutdown(self):
        """
        Final shutdown sequence after main loop exits.
        """
        logger.info('Performing shutdown sequence')

        if self._shutdown_stop_server:
            for method_name in ('StopServer', 'QuitServer'):
                try:
                    await self.client.query_ignore_result(method_name)
                    logger.info('Dedicated server stop requested via %s', method_name)
                    break
                except Exception:
                    continue

        # Best-effort disconnect
        try:
            close_fn = getattr(self.client, 'close', None)
            if callable(close_fn):
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.warning('Client close failed: %s', e)

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def run(self, config_file: str = 'config.xml'):
        """Main entry point. Loads config, connects, runs event loop."""
        print('# initialize PyXaseco ' + '=' * 60)
        logger.info('PyXaseco %s starting', PYXASECO_VERSION)

        # Resolve the config file path; if relative, make it absolute
        # relative to the current working directory (where the user runs from).
        config_path = Path(config_file).resolve()
        # All other config-relative files live in the same directory as config.xml
        self._base_dir = config_path.parent

        # Load config
        self.console_text('[PyXaseco] Loading settings [{1}]', str(config_path))
        if not load_config(config_path, self.settings):
            raise RuntimeError(f'Could not read/parse config file {config_path}')

        # Apply server connection settings from config
        self.server.ip       = self.settings.server_ip
        self.server.port     = self.settings.server_port
        self.server.login    = self.settings.server_login
        self.server.password = self.settings.server_password
        self.server.timeout  = self.settings.server_timeout

        def _resolve(filename: str) -> Path:
            """Resolve a config-relative filename to an absolute path."""
            p = Path(filename)
            if p.is_absolute():
                return p
            return self._base_dir / p

        # Load admin/op lists
        adminops_path = _resolve(self.settings.adminops_file)
        self.console_text('[PyXaseco] Loading admin/ops lists [{1}]', str(adminops_path))
        load_adminops(adminops_path, self.settings)

        # Load banned IPs
        bannedips_path = _resolve(self.settings.bannedips_file)
        self.console_text('[PyXaseco] Loading banned IPs [{1}]', str(bannedips_path))
        load_bannedips(bannedips_path, self.settings)

        # Load plugins
        plugins_xml = self._base_dir / 'plugins.xml'
        self.console_text('[PyXaseco] Loading plugins list [{1}]', str(plugins_xml))
        plugin_files = load_plugins_list(plugins_xml)
        plugins_dir  = self._base_dir / 'plugins'
        self._plugin_loader = PluginLoader(plugins_dir)
        self._plugin_loader.load_all(plugin_files, self)

        # Connect to dedicated server
        self.console('[PyXaseco] Connecting to {1}:{2}', self.server.ip, self.server.port)
        await self._connect()
        self.console('[PyXaseco] Connection established!')

        # Get version info
        version = await self.client.query('GetVersion')
        self.server.game    = version.get('Name', '')
        self.server.version = version.get('Version', '')
        self.server.build   = version.get('Build', '')

        if self.server.get_game() != 'TMF':
            raise RuntimeError(
                f"This is a TMF-only build but server reports game: {self.server.game}")

        # Register core ManiaLink page-navigation handler
        from pyxaseco.helpers import setup_manialink_events
        setup_manialink_events(self)

        # Fire startup event
        await self.release_event('onStartup', None)

        # Sync with server state
        await self._server_sync()

        # Send visual header to in-game chat
        await self._send_header()

        # Main loop
        self.startup_phase = False
        await self._main_loop()
        await self._perform_shutdown()

    async def _connect(self):
        """Authenticate with the dedicated server and enable callbacks."""
        await self.client.connect(
            self.server.ip, self.server.port,
            timeout=float(self.server.timeout or 10)
        )
        if self.settings.server_password == 'SuperAdmin':
            logger.warning("Insecure password 'SuperAdmin' — change it in dedicated config!")

        await self.client.authenticate(self.server.login, self.server.password)
        await self.client.query('EnableCallbacks', True)

        # Wait for server to reach Running state
        await self._wait_server_ready()

    async def _wait_server_ready(self):
        """Poll GetStatus until server is Running - Play (code 4)."""
        status = await self.client.query('GetStatus')
        if status.get('Code') != 4:
            self.console('[PyXaseco] Waiting for server to reach Running - Play...')
            last = status.get('Name', '')
            deadline = time.time() + (self.server.timeout or 120)
            while status.get('Code') != 4:
                await asyncio.sleep(1)
                status = await self.client.query('GetStatus')
                name = status.get('Name', '')
                if name != last:
                    self.console('[PyXaseco] Server status: {1}', name)
                    last = name
                if time.time() > deadline:
                    raise RuntimeError('Timed out waiting for dedicated server to be ready')

    async def _server_sync(self):
        """Sync server state."""
        # Server identity
        sys_info = await self.client.query('GetSystemInfo')
        self.server.serverlogin = sys_info.get('ServerLogin', '')

        player_info = await self.client.query('GetDetailedPlayerInfo', self.server.serverlogin)
        self.server.id       = player_info.get('PlayerId', 0)
        self.server.nickname = player_info.get('NickName', '')
        path = player_info.get('Path', '')
        self.server.zone   = path[6:] if path.startswith('World|') else path
        self.server.rights = (player_info.get('OnlineRights', 0) == 3)

        ladder = await self.client.query('GetLadderServerLimits')
        self.server.laddermin = ladder.get('LadderServerLimitMin', 0.0)
        self.server.laddermax = ladder.get('LadderServerLimitMax', 0.0)

        relay_count = await self.client.query('IsRelayServer')
        self.server.isrelay = relay_count > 0
        if self.server.isrelay:
            self.server.relaymaster = await self.client.query('GetMainServerPlayerInfo', 1)

        self.server.packmask = await self.client.query('GetServerPackMask')

        # Clear leftover ManiaLinks
        await self.client.query_ignore_result('SendHideManialinkPage')

        # Game info
        gameinfo_raw = await self.client.query('GetCurrentGameInfo', 1)
        self.server.gameinfo = Gameinfo(gameinfo_raw)

        # Status
        status = await self.client.query('GetStatus')
        self.currstatus = status.get('Code', 0)

        # Directories
        self.server.gamedir  = await self.client.query('GameDataDirectory')
        self.server.trackdir = await self.client.query('GetTracksDirectory')

        # Server options
        await self._get_server_options()
        await self._enforce_runtime_server_options()
        
        # Fire sync event
        await self.release_event('onSync', None)

        # Populate current player list
        player_list = await self.client.query('GetPlayerList', 300, 0, 2)
        if player_list:
            for pinfo in player_list:
                login = pinfo.get('Login', '')
                if login and login.lower() != self.server.serverlogin.lower():
                    await self._player_connect([login, ''])

        # If already in race, load current challenge
        if self.currstatus != 100:
            await self._begin_race(None)

    async def _get_server_options(self):
        """Fetch and cache server options."""
        opts = await self.client.query('GetServerOptions')
        self.server.name    = opts.get('Name', '')
        self.server.maxplay = opts.get('CurrentMaxPlayers', 0)
        self.server.maxspec = opts.get('CurrentMaxSpectators', 0)

    async def _enforce_runtime_server_options(self):
        """
        Apply controller-owned dedicated-server runtime options.

        Keep VehicleNetQuality pinned to 1 so reconnects / restarts restore
        the expected networking behavior automatically.
        """
        try:
            await self.client.query_ignore_result('SetVehicleNetQuality', 1)
        except Exception as e:
            logger.warning('Could not enforce SetVehicleNetQuality(1): %s', e)

    async def _send_header(self):
        """Send a version header to in-game server chat."""
        msg = f'$z$s$fffPyXaseco $f80{PYXASECO_VERSION}$fff started successfully!'
        await self.client.query_ignore_result('ChatSendServerMessage', msg)

    # ------------------------------------------------------------------
    # Main async event loop
    # ------------------------------------------------------------------

    async def _main_loop(self):
        """
        Continuously poll callbacks from the GbxRemote client and dispatch them.
        """
        prev_second = int(time.time())
        while not self._shutdown_requested:
            loop_start = time.monotonic()

            # Dispatch any buffered callbacks
            await self._execute_callbacks()

            # Fire main loop event
            await self.release_event('onMainLoop', None)

            # Fire per-second event
            now = int(time.time())
            if now != prev_second:
                prev_second = now
                await self.release_event('onEverySecond', None)

            # Maintain ~20ms loop cadence
            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.0, 0.02 - elapsed)
            await asyncio.sleep(sleep_time)

    async def _execute_callbacks(self):
        """Drain the GbxClient callback queue and dispatch each."""
        callbacks = self.client.get_cb_responses()
        for method, params in callbacks:
            handler_name = _CALLBACK_MAP.get(method)
            if handler_name:
                handler = getattr(self, handler_name, None)
                if handler:
                    try:
                        await handler(params)
                    except Exception as e:
                        logger.error('Callback error in %s: %s', handler_name, e, exc_info=True)
            else:
                if self.debug:
                    logger.debug('Unhandled callback: %s', method)

    # ------------------------------------------------------------------
    # Dedicated server callback handlers
    # ------------------------------------------------------------------

    async def _cb_player_connect(self, params: list):
        """TrackMania.PlayerConnect: [login, is_spectator]"""
        await self._player_connect(params)

    async def _cb_player_disconnect(self, params: list):
        """TrackMania.PlayerDisconnect: [login]"""
        login = params[0] if params else ''
        player = self.server.players.remove_player(login)
        if player:
            await self.release_event('onPlayerDisconnect', player)
            self.console_text('[PyXaseco] Player disconnected: {1}', login)

    async def _cb_player_chat(self, params: list):
        """TrackMania.PlayerChat: [uid, login, text, is_registered_cmd]"""
        await self.release_event('onChat', params)
        await self._handle_chat_command(params)

    async def _cb_player_finish(self, params: list):
        """TrackMania.PlayerFinish: [uid, login, time_or_score]"""
        await self._player_finish(params)

    async def _cb_player_checkpoint(self, params: list):
        """TrackMania.PlayerCheckpoint"""
        if not self.server.isrelay:
            await self.release_event('onCheckpoint', params)

    async def _cb_player_info_changed(self, params: list):
        """TrackMania.PlayerInfoChanged: [player_info]"""
        info = params[0] if params else {}
        login = info.get('Login', '')
        player = self.server.players.get_player(login)
        if player:
            player.isspectator    = info.get('IsSpectator', player.isspectator)
            player.isofficial     = info.get('IsInOfficialMode', player.isofficial)
            player.teamid         = int(info.get('TeamId', player.teamid) or 0)
            player.teamname       = info.get('TeamName', player.teamname)
            # Store the packed SpectatorStatus so plugins can decode target/auto info
            # without an extra GetPlayerInfo round-trip.
            player.spectatorstatus = int(info.get('SpectatorStatus', 0) or 0)
            await self.release_event('onPlayerInfoChanged', player)

    async def _cb_player_server_msg_answer(self, params: list):
        """TrackMania.PlayerServerMessageAnswer: [uid, login, answer]"""
        await self.release_event('onPlayerServerMessageAnswer', params)

    async def _cb_manialink_answer(self, params: list):
        """TrackMania.PlayerManialinkPageAnswer: [uid, login, answer]"""
        await self.release_event('onPlayerManialinkPageAnswer', params)

    async def _cb_begin_challenge(self, params: list):
        """TrackMania.BeginChallenge: [challenge, warmup, match_continuation]"""
        await self._begin_race(params)

    async def _cb_end_challenge(self, params: list):
        """TrackMania.EndChallenge: [rankings, challenge, was_warmup, ...]"""
        await self._end_race(params)

    async def _cb_end_round(self, params: list):
        """TrackMania.EndRound"""
        await self.release_event('onEndRound', None)

    async def _cb_begin_round(self, params: list):
        """TrackMania.BeginRound"""
        await self.release_event('onBeginRound', None)

    async def _cb_status_changed(self, params: list):
        """TrackMania.StatusChanged: [code, name]"""
        self.prevstatus = self.currstatus
        self.currstatus = params[0] if params else 0

        # Check warmup state on Sync/Finish
        if self.currstatus in (3, 5):
            try:
                self.warmup_phase = await self.client.query('GetWarmUp')
            except GbxError:
                self.warmup_phase = False

        await self.release_event(f'onStatusChangeTo{self.currstatus}', params)

    async def _cb_bill_updated(self, params: list):
        await self.release_event('onBillUpdated', params)

    async def _cb_challenge_list_modified(self, params: list):
        await self.release_event('onChallengeListModified', params)

    async def _cb_player_incoherence(self, params: list):
        await self.release_event('onPlayerIncoherence', params)

    async def _cb_vote_updated(self, params: list):
        await self.release_event('onVoteUpdated', params)

    async def _cb_echo(self, params: list):
        await self.release_event('onEcho', params)

    async def _cb_tunnel_data(self, params: list):
        await self.release_event('onTunnelDataReceived', params)

    async def _cb_flow_transition(self, params: list):
        await self.release_event('onManualFlowControlTransition', params)

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------

    async def _player_connect(self, params: list):
        """
        Handle a new player connecting.
        params: [login, is_spectator_str_or_bool]
        """
        login = params[0] if params else ''
        if not login:
            return

        # Don't add the server's own dedicated account
        if (hasattr(self.server, 'serverlogin') and
                login.lower() == self.server.serverlogin.lower()):
            return

        # Fetch detailed player info
        try:
            info = await self.client.query('GetDetailedPlayerInfo', login)
        except GbxError as e:
            logger.warning('GetDetailedPlayerInfo failed for %s: %s', login, e)
            # Create minimal player
            info = {'Login': login, 'NickName': login,
                    'IPAddress': '', 'IsSpectator': False,
                    'IsInOfficialMode': False, 'LadderStats': {'TeamName': '', 'PlayerRankings': [{}]},
                    'Path': 'World|Unknown', 'ClientVersion': '',
                    'OnlineRights': 0, 'Language': '', 'Avatar': {}, 'TeamId': 0}

        player = Player(info)

        # Check if IP is banned
        for banned_ip in self.settings.bannedips:
            if self.ip_match(player.ip, banned_ip):
                logger.warning('Banned IP %s tried to connect as %s', player.ip, login)
                await self.client.query_ignore_result('Kick', login, 'Your IP is banned.')
                return

        self.server.players.add_player(player)
        self.console_text('[PyXaseco] Player connected: {1} ({2})', player.nickname, login)

        await self.release_event('onPlayerConnect', player)
        await self.release_event('onPlayerConnect2', player)

    async def _player_finish(self, params: list):
        """
        Handle player finishing a lap/challenge.
        params: [uid, login, time_or_score]
        """
        if len(params) < 3:
            return
        _uid, login, score = params[0], params[1], params[2]
        player = self.server.players.get_player(login)
        if score == 0:
            if player:
                player.retired = True
                player.finished_waiting = False
                await self.release_event('onPlayerRetire', player)
            return  # retired / DNF

        if not player:
            return
        player.retired = False
        player.finished_waiting = True

        # Build the finish_item object used by downstream race handlers.
        from pyxaseco.models import Record, Challenge as _Ch
        import time as _t, datetime as _dt
        finish_item = Record()
        finish_item.player = player
        finish_item.score  = score
        finish_item.date   = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        finish_item.challenge = self.server.challenge
        finish_item.new = False
        await self.release_event('onPlayerFinish1', finish_item)  # rich object event
        await self.release_event('onPlayerFinish', params)        # legacy compatibility event

    # ------------------------------------------------------------------
    # Challenge / race management
    # ------------------------------------------------------------------

    async def _begin_race(self, params):
        """
        Handle beginning of a new challenge.
        params: [challenge_info, warmup, match_continuation]  or None (startup).
        """
        if params:
            self.warmup_phase = bool(params[1]) if len(params) > 1 else False

        # Refresh game mode before firing challenge events so plugins see the
        # actual next-mode state after /admin setgamemode + skip/restart flows.
        try:
            gameinfo_raw = await self.client.query('GetCurrentGameInfo', 1)
            self.server.gameinfo = Gameinfo(gameinfo_raw)
            if getattr(self, 'changingmode', False):
                self.changingmode = False
        except GbxError as e:
            logger.warning('GetCurrentGameInfo refresh before begin race failed: %s', e)

        # Fetch current challenge info
        try:
            challenge_info = await self.client.query('GetCurrentChallengeInfo')
        except GbxError as e:
            logger.error('GetCurrentChallengeInfo failed: %s', e)
            return

        self.server.challenge = Challenge(challenge_info)
        self.server.records.clear()

        await self.release_event('onNewChallenge', self.server.challenge)
        await self.release_event('onBeginRace', self.server.challenge)
        await self.release_event('onNewChallenge2', self.server.challenge)

        self.console('[PyXaseco] New challenge: {1}', self.server.challenge.name)

    async def _end_race(self, params: list):
        """TrackMania.EndChallenge: params[0]=rankings, params[1]=challenge"""
        rankings = params[0] if params else []
        await self.release_event('onEndRace1', params)  # pre-event (votes reset)
        await self.release_event('onEndRace', params)
        await self.release_event('onEndRaceRanking', rankings)

    async def _cb_challenge_restart(self, params: list):
        """TrackMania.ChallengeRestart"""
        await self.release_event('onRestartChallenge', params)
        await self.release_event('onRestartChallenge2', params)

    # ------------------------------------------------------------------
    # Chat command dispatcher
    # ------------------------------------------------------------------

    async def _handle_chat_command(self, params: list):
        """
        Parse a PlayerChat callback for slash-commands.
        params: [uid, login, text, is_registered_cmd]
        """
        if len(params) < 3:
            return

        _uid, login, text = params[0], params[1], params[2]
        await self.dispatch_chat_command(login, text)

    async def dispatch_chat_command(self, login: str, text: str) -> bool:
        """
        Dispatch a slash command internally without needing a public chat callback.

        Returns True when a registered slash command was recognized and dispatched,
        otherwise False.
        """
        if not text or not str(text).startswith('/'):
            return False

        # Split command name and args
        parts = str(text)[1:].split(None, 1)
        cmd_name = parts[0].lower() if parts else ''
        cmd_args = parts[1] if len(parts) > 1 else ''

        cmd = self._chat_commands.get(cmd_name)
        if not cmd:
            return False

        player = self.server.players.get_player(login)

        # Allow dedicated server login to act as a synthetic command author.
        if not player:
            server_login = getattr(self.server, 'serverlogin', '')
            if not server_login or login.lower() != server_login.lower():
                return False

            from pyxaseco.models import Player

            player = Player({
                'Login': login,
                'NickName': login,
                'IPAddress': '',
                'IsSpectator': False,
                'IsInOfficialMode': False,
                'LadderStats': {'TeamName': '', 'PlayerRankings': [{}]},
                'Path': 'World|Server',
                'ClientVersion': '',
                'OnlineRights': 0,
                'Avatar': {},
                'TeamId': 0,
            })

        command = {
            'author': player,
            'params': cmd_args,
        }

        # Fire the chat command event
        event_name = 'onChat_' + cmd_name
        if self.events.has_handlers(event_name):
            await self.release_event(event_name, command)
        else:

            handler_name = 'chat_' + cmd_name
            await self.release_event('onChatCommand', {
                'name': cmd_name,
                'handler': handler_name,
                'command': command,
            })
        return True
