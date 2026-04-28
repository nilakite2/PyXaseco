"""
plugin_freezone.py — Port of plugins/plugin.freezone.php

Manages Freezone access rules.
Requires freezone.xml config and a password from freezone:servers.

Free players are limited to 5 tracks in a row before a spectator round.

Note: if the API is unreachable it degrades gracefully (test-mode fallback).
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

FREEZONE_VERSION = '1.4'
MAX_PLAYER_GAME = 5
MAX_SPECTATOR_GAME = 1
CHAT_PREFIX = '$<$0f0$oFreeZone:$> '

_fz: 'FreezoneState | None' = None


class FreezoneState:
    def __init__(self, aseco: 'Aseco', config: dict):
        self.aseco = aseco
        self.ws_user     = config.get('ws_user', aseco.server.serverlogin)
        self.ws_password = config.get('ws_password', '')
        self.testmode    = config.get('testmode', True)
        self.debugmode   = config.get('debugmode', False)
        self.notify      = config.get('notify', 0)
        self.notify_mute   = config.get('notify_mute', '{1} has been forced to spectator (FreeZone).')
        self.notify_unmute = config.get('notify_unmute', '{1} is now allowed to play (FreeZone).')

        self.players: dict = {}       # {login: game_count}
        self.spectators: dict = {}    # {login: game_count}
        self.retired: dict = {}       # {login: bool}
        self.banned: list = []
        self.forced: dict = {}        # {login: force_mode}
        self.slang_words: list = []
        self.slang_users: dict = {}
        self.gamestate: int = 0       # 0=race, 1=score

        self.interval: dict = {
            'ban_slang': 0,
            'stats': 0,
            'rules': 0,
            'free': 0,
        }

    @staticmethod
    def _api_number(value, default: int = 0) -> int:
        """Coerce freezone API payloads into an integer value."""
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value.strip()))
            except Exception:
                return default
        if isinstance(value, (list, tuple)):
            if not value:
                return default
            return FreezoneState._api_number(value[0], default)
        if isinstance(value, dict):
            for key in ('count', 'value', 'result', 'status'):
                if key in value:
                    return FreezoneState._api_number(value[key], default)
        return default

    @staticmethod
    def _is_spectator(player_or_info) -> bool:
        raw = getattr(player_or_info, 'spectatorstatus', None)
        if raw is None and isinstance(player_or_info, dict):
            raw = player_or_info.get('SpectatorStatus', player_or_info.get('spectatorstatus'))
        if raw is not None:
            try:
                return (int(raw) % 10) != 0
            except Exception:
                pass
        raw_flag = getattr(player_or_info, 'isspectator', None)
        if raw_flag is None and isinstance(player_or_info, dict):
            raw_flag = player_or_info.get('IsSpectator', player_or_info.get('isspectator', False))
        return bool(raw_flag)

    async def _show_freezone_button(self, login: str | None = None):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<manialinks>'
            '<manialink id="1073741824">'
            f'<frame posn="53 {"42" if self.gamestate == 1 else "47"} -32">'
            '<quad sizen="27 4" style="BgsPlayerCard" substyle="BgCard1" manialink="freezone"/>'
            '<label posn="13.5 -1 0.1" sizen="27 3" halign="center" '
            'style="TextStaticSmall" text="FreeZone"/>'
            '</frame>'
            '</manialink>'
            '</manialinks>'
        )

        if login:
            player = self.aseco.server.players.get_player(login)
            if player and not getattr(player, 'rights', False):
                await self.aseco.client.query_ignore_result(
                    'SendDisplayManialinkPageToLogin', login, xml, 0, False
                )
            return

        logins = [pl.login for pl in self.aseco.server.players.all() if not getattr(pl, 'rights', False)]
        if logins:
            await self.aseco.client.query_ignore_result(
                'SendDisplayManialinkPageToLogin', ','.join(logins), xml, 0, False
            )

    def get_free_players(self) -> list:
        return [pl.login for pl in self.aseco.server.players.all()
                if not getattr(pl, 'rights', False)]

    async def _api(self, method: str, path: str, data=None):
        if self.testmode:
            return None
        try:
            import aiohttp
            url = f'http://ws.manialive.com{path}'
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                if method == 'GET':
                    async with sess.get(url, auth=aiohttp.BasicAuth(
                            self.ws_user, self.ws_password)) as r:
                        return await r.json(content_type=None)
                elif method == 'PUT':
                    async with sess.put(url, json=data, auth=aiohttp.BasicAuth(
                            self.ws_user, self.ws_password)) as r:
                        return await r.json(content_type=None)
        except Exception as e:
            logger.debug('[Freezone] API error: %s', e)
        return None

    async def player_connect(self, player):
        login = player.login
        if getattr(player, 'rights', False):
            return
        # Check ban
        ban_status = self._api_number(await self._api('GET', f'/freezone/ban/status/{login}/index.json'))
        if ban_status == 2:
            await self.aseco.client.query_ignore_result('Kick', login)
            self.banned.append(login)
            return

        # Restore in-memory state first when reconnecting during the same session.
        if login in self.retired:
            if login in self.players:
                if self._is_spectator(player):
                    self.spectators[login] = self.players[login]
                else:
                    await self.aseco.client.query_ignore_result('ForceSpectator', login, 2)
                    self.forced[login] = 2
            elif login in self.spectators:
                if self._is_spectator(player):
                    await self._force_spectator(login, max(int(self.spectators.get(login, MAX_PLAYER_GAME) or 0), MAX_PLAYER_GAME))
                elif int(self.spectators.get(login, 0) or 0) > MAX_PLAYER_GAME:
                    await self._force_spectator(login, int(self.spectators.get(login, MAX_PLAYER_GAME) or MAX_PLAYER_GAME))
                else:
                    self.players[login] = self.spectators[login]
                    self.spectators.pop(login, None)
            await self._show_freezone_button(login)
            return

        # Check rules count
        count = self._api_number(await self._api('GET', f'/freezone/rules/{login}/index.json'))
        if count >= MAX_PLAYER_GAME:
            await self._force_spectator(login, count)
        else:
            if not self._is_spectator(player):
                self.players[login] = count
                await self.aseco.client.query_ignore_result('ForceSpectator', login, 2)
                self.forced[login] = 2
            else:
                self.spectators[login] = count
        await self._show_freezone_button(login)

    async def player_disconnect(self, player):
        login = player.login
        count = self.players.get(login, self.spectators.get(login, MAX_PLAYER_GAME))
        await self._api('PUT', f'/freezone/rules/{login}/index.json', [count])
        if self.forced.get(login):
            self.retired[login] = True
        self.forced.pop(login, None)
        self.players.pop(login, None)
        self.spectators.pop(login, None)

    async def _force_spectator(self, login: str, count: int):
        self.spectators[login] = count
        await self.aseco.client.query_ignore_result('ForceSpectator', login, 1)
        self.forced[login] = 1

    async def new_challenge(self, challenge):
        # Increment counters and check limits
        for login, value in list(self.spectators.items()):
            self.spectators[login] += 1
            if value >= MAX_PLAYER_GAME + MAX_SPECTATOR_GAME:
                await self.aseco.client.query_ignore_result('ForceSpectator', login, 2)
                self.forced[login] = 2
                self.players[login] = 0
                self.spectators.pop(login, None)

        for login, value in list(self.players.items()):
            self.players[login] += 1
            if value >= MAX_PLAYER_GAME:
                await self._force_spectator(login, value + 1)

        self.gamestate = 0
        await self._show_freezone_button()

    async def end_race(self):
        self.gamestate = 1
        for login in list(self.retired.keys()):
            count = self.players.get(login, self.spectators.get(login, MAX_PLAYER_GAME))
            count += 1
            await self._api('PUT', f'/freezone/rules/{login}/index.json', [count])
            self.players.pop(login, None)
            self.spectators.pop(login, None)
        self.retired.clear()
        await self._show_freezone_button()

    async def tick(self):
        now = time.time()
        if self.interval['ban_slang'] + 21600 <= now:
            self.banned = []
            self.interval['ban_slang'] = now
        if self.interval['rules'] + 780 <= now:
            self.interval['rules'] = now

    def check_language(self, login: str, text: str):
        pass


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',            _fz_sync)
    aseco.register_event('onChat',            _fz_chat)
    aseco.register_event('onPlayerConnect',   _fz_player_connect)
    aseco.register_event('onPlayerDisconnect',_fz_player_disconnect)
    aseco.register_event('onPlayerInfoChanged',_fz_info_changed)
    aseco.register_event('onPlayerManialinkPageAnswer', _fz_action)
    aseco.register_event('onEverySecond',     _fz_tick)
    aseco.register_event('onNewChallenge',    _fz_new_challenge)
    aseco.register_event('onEndRace1',        _fz_end_race)


async def _fz_sync(aseco: 'Aseco', _data):
    global _fz
    try:
        import pathlib
        from pyxaseco.core.config import parse_xml_file
        base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
        cfg_path = base / 'freezone.xml'
        config: dict = {}
        if cfg_path.exists():
            raw = parse_xml_file(cfg_path)
            ws = raw.get('FREEZONE', {}).get('WEBSERVICES', [{}])[0] if raw else {}
            def g(block, key, default=''):
                v = block.get(key.upper(), [default])
                return v[0] if v else default
            config = {
                'ws_user':     g(ws, 'USER', aseco.server.serverlogin),
                'ws_password': g(ws, 'PASSWORD', ''),
                'testmode':    g(ws, 'TESTMODE', 'true').lower() == 'true',
            }
        else:
            config = {'testmode': True}
        _fz = FreezoneState(aseco, config)
        aseco.console('[Freezone] Loaded (version {1})', FREEZONE_VERSION)
    except Exception as e:
        logger.warning('[Freezone] Init error: %s', e)
        _fz = None


async def _fz_chat(aseco: 'Aseco', chat: list):
    if _fz and chat[0] != aseco.server.id:
        _fz.check_language(chat[1], chat[2])


async def _fz_player_connect(aseco: 'Aseco', player):
    if _fz:
        await _fz.player_connect(player)


async def _fz_player_disconnect(aseco: 'Aseco', player):
    if _fz:
        await _fz.player_disconnect(player)


async def _fz_info_changed(aseco: 'Aseco', info: dict):
    if not _fz:
        return
    if isinstance(info, dict):
        login = str(info.get('Login', info.get('login', '')) or '').strip()
    else:
        login = str(getattr(info, 'login', '') or '').strip()
    if not login:
        return
    player = aseco.server.players.get_player(login)
    if not player or getattr(player, 'rights', False):
        return

    is_spec = _fz._is_spectator(info if isinstance(info, dict) else player)
    player.isspectator = is_spec

    if not is_spec:
        if login in _fz.spectators:
            _fz.players[login] = _fz.spectators.pop(login)
        await aseco.client.query_ignore_result('ForceSpectator', login, 2)
        _fz.forced[login] = 2
    else:
        if login in _fz.players:
            _fz.spectators[login] = _fz.players.pop(login)

    await _fz._show_freezone_button(login)


async def _fz_action(aseco: 'Aseco', answer: list):
    pass


async def _fz_tick(aseco: 'Aseco', _param=None):
    if _fz:
        await _fz.tick()


async def _fz_new_challenge(aseco: 'Aseco', challenge):
    if _fz:
        await _fz.new_challenge(challenge)


async def _fz_end_race(aseco: 'Aseco', _data):
    if _fz:
        await _fz.end_race()
