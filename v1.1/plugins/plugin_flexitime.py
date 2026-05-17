"""
plugin_flexitime.py — Port of plugins/plugin.flexitime.php (by realh / AMPDev)

Flexible time limit for tracks.
Reads flexitime.xml for config. Stores custom per-track times in DB table
custom_tracktimes. Shows a countdown panel (ManiaLink id 29288).

/timeleft [[+|-]MINUTES]|[pause|resume]  — query or change time remaining
/tl                                        — quick-set to 5 minutes
/timeset MINUTES                           — set custom time for this track
"""

from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

from pyxaseco.core.config import parse_xml_file
from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

ML_ID = 29288


class FlexiTime:
    VERSION = '1.3.3'

    def __init__(self, aseco: 'Aseco'):
        self.aseco = aseco

        # Defaults (overridden by flexitime.xml)
        self.admin_level  = 1
        self.admins       = []
        self.default_time = 90        # minutes
        self.custom_time  = True
        self.author_mult  = 0
        self.min_time     = 15        # minutes
        self.use_chat     = False
        self.show_panel   = True
        self.clock_colour = 'fff'
        self.warn_time    = 300       # seconds
        self.warn_colour  = 'ff4'
        self.danger_time  = 60        # seconds
        self.danger_colour = 'f44'

        self.time_left   = self.default_time * 60
        self.author_time = 0          # seconds
        self.paused      = False
        self._mode_disabled = False
        self._panel_visible = False

        self._load_config(aseco)

    def _is_ta_mode(self) -> bool:
        gameinfo = getattr(getattr(self.aseco, 'server', None), 'gameinfo', None)
        return getattr(gameinfo, 'mode', -1) == Gameinfo.TA

    def _load_config(self, aseco: 'Aseco'):
        xml_path = aseco._base_dir / 'flexitime.xml'
        try:
            data = parse_xml_file(xml_path)
            if not data:
                return
            ft = data.get('FLEXITIME', {})

            def g(key, default):
                items = ft.get(key.upper(), [default])
                return items[0] if items else default

            self.admin_level   = int(g('ADMIN_LEVEL', 1))
            self.default_time  = int(g('DEFAULT_TIME', 90))
            self.custom_time   = bool(int(g('CUSTOM_TIME', 1)))
            self.author_mult   = int(g('AUTHOR_MULT', 0))
            self.min_time      = int(g('MIN_TIME', 15))
            self.use_chat      = bool(int(g('USE_CHAT', 0)))
            self.show_panel    = bool(int(g('SHOW_PANEL', 1)))
            self.clock_colour  = g('COLOUR', 'fff')
            self.warn_time     = int(g('WARN_TIME', 300))
            self.warn_colour   = g('WARN_COLOUR', 'ff4')
            self.danger_time   = int(g('DANGER_TIME', 60))
            self.danger_colour = g('DANGER_COLOUR', 'f44')

            # Whitelist / admins
            whitelist = ft.get('WHITELIST', [{}])
            if whitelist and isinstance(whitelist[0], dict):
                admin_list = whitelist[0].get('ADMIN', [])
                if isinstance(admin_list, list):
                    self.admins = admin_list
                elif isinstance(admin_list, str):
                    self.admins = [admin_list]

        except Exception as e:
            logger.warning('[FlexiTime] Could not read flexitime.xml: %s', e)

    def _time_str(self, secs: int) -> str:
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        if h:
            return f'{h:02d}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def _colour(self) -> str:
        if self.time_left < self.danger_time:
            return self.danger_colour
        if self.time_left < self.warn_time or self.time_left < self.author_time:
            return self.warn_colour
        return self.clock_colour

    async def init_timer(self):
        if not self._is_ta_mode():
            await self._disable_outside_ta()
            return
        self._mode_disabled = False
        challenge = self.aseco.server.challenge
        self.author_time = round(challenge.authortime / 1000)
        self.paused = False

        loaded_custom = False
        if self.custom_time:
            try:
                from pyxaseco.plugins.plugin_localdatabase import get_pool
                pool = await get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                'SELECT tracktime FROM custom_tracktimes WHERE challenge_uid=%s',
                                (challenge.uid,))
                            row = await cur.fetchone()
                            if row:
                                val = str(row[0]).strip()
                                parts = val.split(':')
                                if len(parts) == 2:
                                    self.time_left = int(parts[0]) * 60 + int(parts[1])
                                else:
                                    self.time_left = int(val) * 60
                                loaded_custom = True
            except Exception as e:
                logger.debug('[FlexiTime] custom_tracktimes lookup: %s', e)

        if not loaded_custom:
            if self.author_mult:
                t = int(challenge.authortime / 60000 * self.author_mult + 0.999) * 60
                t = max(self.min_time * 60, min(self.default_time * 60, t))
                self.time_left = t
            else:
                self.time_left = self.default_time * 60

        await self._show_panel()

    async def tick(self):
        if not self._is_ta_mode():
            await self._disable_outside_ta()
            return
        self._mode_disabled = False
        if not self.paused and self.time_left > 0:
            self.time_left -= 1
        await self._show_panel()
        if not self.paused and self.time_left <= 0:
            await self._next_round()

    async def _disable_outside_ta(self):
        self.paused = True
        if self._mode_disabled:
            return
        self._mode_disabled = True
        await self.hide_panel()

    async def _show_panel(self):
        if not self.show_panel:
            if self._panel_visible:
                await self.hide_panel()
            return
        colour   = self._colour()
        showtime = self._time_str(self.time_left)
        xpos     = '120' if self.paused else '60'
        body = (
            f'<frame scale="1" posn="{xpos} 20">'
            f'<quad posn="8 0 0" sizen="18 5 0.08" halign="right" valign="center" '
            f'style="BgsPlayerCard" substyle="BgPlayerCardBig"/>'
            f'<label posn="3.5 0.1 0.1" halign="right" valign="center" scale="0.6" '
            f'style="TextRaceChrono" text="$s${colour}{showtime}"/>'
            f'</frame>'
        )
        hud = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}">{body}</manialink>'
        await self.aseco.client.query_ignore_result(
            'SendDisplayManialinkPage', hud, 0, False)
        self._panel_visible = True

    async def hide_panel(self):
        if not self._panel_visible:
            return
        self.paused = True
        hud = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
        await self.aseco.client.query_ignore_result(
            'SendDisplayManialinkPage', hud, 0, False)
        self._panel_visible = False

    async def _next_round(self):
        self.paused = True
        await self.aseco.client.query_ignore_result('NextChallenge')

    def _authenticate(self, command: dict) -> bool:
        user = command['author']
        if user.login in self.admins:
            return True
        if self.admin_level == 4:
            return True
        if self.aseco.is_master_admin(user) and self.admin_level > 0:
            return True
        if self.aseco.is_admin(user) and self.admin_level > 1:
            return True
        if self.aseco.is_operator(user) and self.admin_level > 2:
            return True
        return False

    async def command_timeleft(self, command: dict, emergency: bool = False):
        login = command['author'].login
        param = command['params'].strip()

        async def _private(msg):
            await self.aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', msg, login)

        async def _chat(msg):
            await self.aseco.client.query_ignore_result(
                'ChatSendServerMessage', f'> {msg}')

        if not self._is_ta_mode():
            await _private('FlexiTime is only active in TimeAttack mode.')
            return

        if not emergency and not param:
            suf = ' (h:m:s)' if self.time_left >= 3600 else ' (m:s)'
            status = ' (paused).' if self.paused else '.'
            await _private(self._time_str(self.time_left) + suf + ' until round end' + status)
            return

        if not self._authenticate(command):
            await _private('You do not have permission to change the remaining time.')
            return

        if param.lower() == 'pause':
            self.paused = True
            await _chat(f'{login} paused the timer.')
            return
        if param.lower() == 'resume':
            self.paused = False
            await _chat(f'{login} unpaused the timer.')
            return

        if emergency:
            self.time_left = 300
            await self._show_panel()
            await _chat(f'{login} changed time left: {self._time_str(self.time_left)}')
            return

        plus  = param.startswith('+')
        minus = param.startswith('-')
        raw   = param.lstrip('+-')
        try:
            val = int(raw) * 60
        except ValueError:
            await _private('Invalid parameter to /timeleft.')
            return

        tl = self.time_left
        if plus:
            tl += val
        elif minus:
            tl -= val
        else:
            tl = val

        if tl < 0:
            await _private("Can't set remaining time to less than zero.")
            return

        self.time_left = tl
        await self._show_panel()
        await _chat(f'{login} changed time left: {self._time_str(self.time_left)}')
        if self.time_left == 0:
            await self._next_round()

    async def command_timeset(self, command: dict):
        login = command['author'].login

        async def _private(msg):
            await self.aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', msg, login)

        if not self._is_ta_mode():
            await _private('FlexiTime is only active in TimeAttack mode.')
            return

        if not self.custom_time:
            await _private('/timeset command not enabled in plugin config.')
            return
        if not self._authenticate(command):
            await _private('You do not have permission.')
            return

        try:
            minutes = int(command['params'].strip())
        except ValueError:
            await _private('Usage (where 120 is number of minutes): /timeset 120')
            return
        if not minutes:
            await _private('Usage (where 120 is number of minutes): /timeset 120')
            return

        uid = self.aseco.server.challenge.uid
        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
            pool = await get_pool()
            if pool:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        # Ensure table exists
                        await cur.execute(
                            'CREATE TABLE IF NOT EXISTS custom_tracktimes ('
                            '  id int NOT NULL AUTO_INCREMENT,'
                            '  challenge_uid varchar(27) NOT NULL,'
                            '  tracktime varchar(10) NOT NULL,'
                            '  PRIMARY KEY (id)'
                            ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
                        )
                        await cur.execute(
                            'SELECT id FROM custom_tracktimes WHERE challenge_uid=%s', (uid,))
                        existing = await cur.fetchone()
                        if existing:
                            await cur.execute(
                                'UPDATE custom_tracktimes SET tracktime=%s WHERE challenge_uid=%s',
                                (str(minutes), uid))
                        else:
                            await cur.execute(
                                'INSERT INTO custom_tracktimes (challenge_uid, tracktime) VALUES (%s,%s)',
                                (uid, str(minutes)))
        except Exception as e:
            logger.warning('[FlexiTime] timeset DB error: %s', e)

        await self.aseco.client.query_ignore_result(
            'ChatSendServerMessage',
            f'> {login} set future time for this track to {minutes} minutes.')


# ---------------------------------------------------------------------------
# Module-level globals and event handlers
# ---------------------------------------------------------------------------

_flexitime: FlexiTime | None = None


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup',   flexitime_startup)
    aseco.register_event('onBeginRound', flexitime_begin_round)
    aseco.register_event('onEndRound',  flexitime_end_round)
    aseco.register_event('onEverySecond', flexitime_tick)

    aseco.add_chat_command('timeleft',
                           'Change or query time left: /timeleft [[+|-]MINUTES]|[pause|resume]')
    aseco.add_chat_command('tl',      'Quickly set remaining time: /tl [MINUTES] (default: 5)')
    aseco.add_chat_command('timeset', 'Sets custom timelimit in minutes for this track')

    aseco.register_event('onChat_timeleft', chat_timeleft)
    aseco.register_event('onChat_tl',       chat_tl)
    aseco.register_event('onChat_timeset',  chat_timeset)


async def flexitime_startup(aseco: 'Aseco', _param):
    global _flexitime
    _flexitime = FlexiTime(aseco)
    await _flexitime.init_timer()
    aseco.console('[FlexiTime] Started v{1}', _flexitime.VERSION)


async def flexitime_begin_round(aseco: 'Aseco', _param):
    if _flexitime:
        await _flexitime.init_timer()


async def flexitime_end_round(aseco: 'Aseco', _param):
    if _flexitime:
        await _flexitime.hide_panel()


async def flexitime_tick(aseco: 'Aseco', _param):
    if _flexitime:
        await _flexitime.tick()


async def chat_timeleft(aseco: 'Aseco', command: dict):
    if _flexitime:
        await _flexitime.command_timeleft(command, emergency=False)


async def chat_tl(aseco: 'Aseco', command: dict):
    if _flexitime:
        params = (command.get('params') or '').strip()
        await _flexitime.command_timeleft(command, emergency=(params == ''))


async def chat_timeset(aseco: 'Aseco', command: dict):
    if _flexitime:
        await _flexitime.command_timeset(command)
