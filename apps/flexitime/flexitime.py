"""
flexitime.py - Optional flexible TimeAttack timer app.

Ported from the legacy plugin.flexitime.php line, but adapted to v1.2:
- app-native settings from apps/flexitime/app_defaults.toml
- current localdb service instead of legacy plugin imports
- standalone app that can stay disabled in apps.toml
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, as_int, as_str, bind_app_settings
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

ML_ID = 29288


def _as_login_list(value, default=None) -> list[str]:
    if value is None:
        value = default or []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace(";", ",").replace("\n", ",")
    return [item.strip() for item in text.split(",") if item.strip()]


FLEXITIME_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='flexitime',
    section_name='flexitime',
    description='Flexible TimeAttack timer settings',
    settings=(
        AppSetting('admin_level', 3, as_int, 'Minimum admin level allowed to change time.', 'access'),
        AppSetting('whitelist', (), _as_login_list, 'Whitelisted logins allowed to manage time.', 'access'),
        AppSetting('default_time', 180, as_int, 'Default time limit in minutes.', 'timing'),
        AppSetting('custom_time', True, as_bool, 'Use custom per-track times from the database.', 'timing'),
        AppSetting('author_mult', 5, as_int, 'Author-time multiplier when no custom value exists.', 'timing'),
        AppSetting('min_time', 45, as_int, 'Minimum time in minutes when using author-time scaling.', 'timing'),
        AppSetting('use_chat', True, as_bool, 'Reserved for legacy chat timer announcements.', 'ui'),
        AppSetting('show_panel', True, as_bool, 'Show the flexitime HUD panel.', 'ui'),
        AppSetting('colour', 'fff', as_str, 'Default timer colour.', 'ui'),
        AppSetting('warn_time', 300, as_int, 'Warn threshold in seconds.', 'ui'),
        AppSetting('warn_colour', 'ff4', as_str, 'Warn timer colour.', 'ui'),
        AppSetting('danger_time', 60, as_int, 'Danger threshold in seconds.', 'ui'),
        AppSetting('danger_colour', 'f44', as_str, 'Danger timer colour.', 'ui'),
    ),
)

feature_flexitime = True
_flexitime: "FlexiTime | None" = None


class FlexiTime:
    VERSION = '1.3.3'

    def __init__(self, aseco: 'Aseco'):
        self.aseco = aseco
        self.admin_level = 3
        self.admins: list[str] = []
        self.default_time = 180
        self.custom_time = True
        self.author_mult = 5
        self.min_time = 45
        self.use_chat = True
        self.show_panel = True
        self.clock_colour = 'fff'
        self.warn_time = 300
        self.warn_colour = 'ff4'
        self.danger_time = 60
        self.danger_colour = 'f44'

        self.time_left = self.default_time * 60
        self.author_time = 0
        self.paused = False
        self._mode_disabled = False
        self._panel_visible = False

        self._load_config()

    def _load_config(self) -> None:
        try:
            bound = bind_app_settings(FLEXITIME_SETTINGS_SCHEMA, getattr(self.aseco, '_base_dir', None))
            self.admin_level = int(bound.values['admin_level'])
            self.admins = list(bound.values['whitelist'])
            self.default_time = int(bound.values['default_time'])
            self.custom_time = bool(bound.values['custom_time'])
            self.author_mult = int(bound.values['author_mult'])
            self.min_time = int(bound.values['min_time'])
            self.use_chat = bool(bound.values['use_chat'])
            self.show_panel = bool(bound.values['show_panel'])
            self.clock_colour = str(bound.values['colour'])
            self.warn_time = int(bound.values['warn_time'])
            self.warn_colour = str(bound.values['warn_colour'])
            self.danger_time = int(bound.values['danger_time'])
            self.danger_colour = str(bound.values['danger_colour'])
            self.time_left = self.default_time * 60
        except Exception as exc:
            logger.warning('[FlexiTime] Could not read app defaults: %s', exc)

    def _is_ta_mode(self) -> bool:
        gameinfo = getattr(getattr(self.aseco, 'server', None), 'gameinfo', None)
        return getattr(gameinfo, 'mode', -1) == Gameinfo.TA

    def _is_whitelisted(self, login: str) -> bool:
        wanted = str(login or '').lower()
        return wanted in {str(item).lower() for item in self.admins}

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
                pool = await localdb_get_pool(self.aseco)
                if pool:
                    async with pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                'SELECT tracktime FROM custom_tracktimes WHERE challenge_uid=%s',
                                (challenge.uid,),
                            )
                            row = await cur.fetchone()
                            if row:
                                val = str(row[0]).strip()
                                parts = val.split(':')
                                if len(parts) == 2:
                                    self.time_left = int(parts[0]) * 60 + int(parts[1])
                                else:
                                    self.time_left = int(val) * 60
                                loaded_custom = True
            except Exception as exc:
                logger.debug('[FlexiTime] custom_tracktimes lookup: %s', exc)

        if not loaded_custom:
            if self.author_mult:
                scaled = int(challenge.authortime / 60000 * self.author_mult + 0.999) * 60
                scaled = max(self.min_time * 60, min(self.default_time * 60, scaled))
                self.time_left = scaled
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

        colour = self._colour()
        showtime = self._time_str(self.time_left)
        xpos = '120' if self.paused else '60'
        body = (
            f'<frame scale="1" posn="{xpos} 20">'
            f'<quad posn="8 0 0" sizen="18 5 0.08" halign="right" valign="center" '
            f'style="BgsPlayerCard" substyle="BgPlayerCardBig"/>'
            f'<label posn="3.5 0.1 0.1" halign="right" valign="center" scale="0.6" '
            f'style="TextRaceChrono" text="$s${colour}{showtime}"/>'
            '</frame>'
        )
        hud = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}">{body}</manialink>'
        await self.aseco.client.query_ignore_result('SendDisplayManialinkPage', hud, 0, False)
        self._panel_visible = True

    async def hide_panel(self):
        if not self._panel_visible:
            return
        self.paused = True
        hud = f'<?xml version="1.0" encoding="UTF-8"?><manialink id="{ML_ID}"></manialink>'
        await self.aseco.client.query_ignore_result('SendDisplayManialinkPage', hud, 0, False)
        self._panel_visible = False

    async def _next_round(self):
        self.paused = True
        await self.aseco.client.query_ignore_result('NextChallenge')

    def _authenticate(self, command: dict) -> bool:
        user = command['author']
        login = str(getattr(user, 'login', '') or '')
        if self._is_whitelisted(login):
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
        param = str(command.get('params') or '').strip()

        async def _private(msg: str):
            await self.aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)

        async def _chat(msg: str):
            await self.aseco.client.query_ignore_result('ChatSendServerMessage', f'> {msg}')

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

        plus = param.startswith('+')
        minus = param.startswith('-')
        raw = param.lstrip('+-')
        try:
            val = int(raw) * 60
        except ValueError:
            await _private('Invalid parameter to /timeleft.')
            return

        next_value = self.time_left
        if plus:
            next_value += val
        elif minus:
            next_value -= val
        else:
            next_value = val

        if next_value < 0:
            await _private("Can't set remaining time to less than zero.")
            return

        self.time_left = next_value
        await self._show_panel()
        await _chat(f'{login} changed time left: {self._time_str(self.time_left)}')
        if self.time_left == 0:
            await self._next_round()

    async def command_timeset(self, command: dict):
        login = command['author'].login

        async def _private(msg: str):
            await self.aseco.client.query_ignore_result('ChatSendServerMessageToLogin', msg, login)

        if not self._is_ta_mode():
            await _private('FlexiTime is only active in TimeAttack mode.')
            return
        if not self.custom_time:
            await _private('/timeset command not enabled in app config.')
            return
        if not self._authenticate(command):
            await _private('You do not have permission.')
            return

        try:
            minutes = int(str(command.get('params') or '').strip())
        except ValueError:
            await _private('Usage (where 120 is number of minutes): /timeset 120')
            return
        if not minutes:
            await _private('Usage (where 120 is number of minutes): /timeset 120')
            return

        uid = self.aseco.server.challenge.uid
        try:
            pool = await localdb_get_pool(self.aseco)
            if pool:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            'CREATE TABLE IF NOT EXISTS custom_tracktimes ('
                            '  id int NOT NULL AUTO_INCREMENT,'
                            '  challenge_uid varchar(27) NOT NULL,'
                            '  tracktime varchar(10) NOT NULL,'
                            '  PRIMARY KEY (id)'
                            ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
                        )
                        await cur.execute(
                            'SELECT id FROM custom_tracktimes WHERE challenge_uid=%s',
                            (uid,),
                        )
                        existing = await cur.fetchone()
                        if existing:
                            await cur.execute(
                                'UPDATE custom_tracktimes SET tracktime=%s WHERE challenge_uid=%s',
                                (str(minutes), uid),
                            )
                        else:
                            await cur.execute(
                                'INSERT INTO custom_tracktimes (challenge_uid, tracktime) VALUES (%s,%s)',
                                (uid, str(minutes)),
                            )
        except Exception as exc:
            logger.warning('[FlexiTime] timeset DB error: %s', exc)

        await self.aseco.client.query_ignore_result(
            'ChatSendServerMessage',
            f'> {login} set future time for this track to {minutes} minutes.',
        )


def register(aseco: 'Aseco'):
    setattr(aseco, 'feature_flexitime', True)
    setattr(aseco.server, 'feature_flexitime', True)

    aseco.register_event('onStartup', flexitime_startup)
    aseco.register_event('onBeginRound', flexitime_begin_round)
    aseco.register_event('onEndRound', flexitime_end_round)
    aseco.register_event('onEverySecond', flexitime_tick)

    aseco.add_chat_command(
        'timeleft',
        'Change or query time left: /timeleft [[+|-]MINUTES]|[pause|resume]',
        is_admin=True,
        app='flexitime',
        category='chat-timer',
    )
    aseco.add_chat_command(
        'tl',
        'Quickly set remaining time: /tl [MINUTES] (default: 5)',
        is_admin=True,
        app='flexitime',
        category='chat-timer',
    )
    aseco.add_chat_command(
        'timeset',
        'Sets custom timelimit in minutes for this track',
        is_admin=True,
        app='flexitime',
        category='chat-timer',
    )

    aseco.register_event('onChat_timeleft', chat_timeleft)
    aseco.register_event('onChat_tl', chat_tl)
    aseco.register_event('onChat_timeset', chat_timeset)


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
        params = str(command.get('params') or '').strip()
        await _flexitime.command_timeleft(command, emergency=(params == ''))


async def chat_timeset(aseco: 'Aseco', command: dict):
    if _flexitime:
        await _flexitime.command_timeset(command)
