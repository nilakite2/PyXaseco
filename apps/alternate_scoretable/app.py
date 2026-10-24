"""Optional Alternate Scoretable, inspired by undef's XAseco plugin (GPLv3+)."""

import logging
from time import monotonic

from pyxaseco.app_config import (AppSetting, AppSettingsSchema, as_bool, as_float, as_int, as_str,
                                bind_app_settings, clear_app_defaults_cache)
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.base import App
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase

from . import results, views


logger = logging.getLogger(__name__)
POLICY = JobPolicy(capacity=1, deadline_seconds=15)
SCHEMA = AppSettingsSchema(app_id='alternate_scoretable', settings=(
    AppSetting('enabled', True, as_bool, 'Enable Alternate Scoretable.'),
    AppSetting('entries', 20, as_int, 'Rows per page, 5-20.'),
    AppSetting('show_at_score', True, as_bool, 'Automatically open at the end of the map.'),
    AppSetting('show_at_finish', True, as_bool, 'Automatically open after a positive finish.'),
    AppSetting('delay_score_display', 5, as_int, 'End-of-map delay, 0-30 seconds.'),
    AppSetting('delay_finish_display', 3, as_int, 'Finish popup delay, 0-30 seconds.'),
    AppSetting('score_display_time', 20, as_int, 'Automatic end-of-map popup duration, 1-120 seconds.'),
    AppSetting('finish_display_time', 8, as_int, 'Automatic finish popup duration, 1-120 seconds.'),
    AppSetting('columns/pb', True, as_bool, 'Show personal bests, including those outside leaderboard limits.'),
    AppSetting('columns/finishes', True, as_bool, 'Show positive finishes observed on this map.'),
    AppSetting('columns/ladder', True, as_bool, 'Show cached ladder rank.'),
    AppSetting('columns/online', True, as_bool, 'Show current connection duration.'),
    AppSetting('button/enabled', True, as_bool, 'Show a scoretable quicklink while racing.'),
    AppSetting('button/pos_x', -52.5, as_float, 'Quicklink X position.'),
    AppSetting('button/pos_y', -28.5, as_float, 'Quicklink Y position.'),
    AppSetting('button/width', 4.6, as_float, 'Bar width, 1-20.'),
    AppSetting('button/height', 6.5, as_float, 'Bar height, 1-20.'),
    AppSetting('button/text_color', 'FC0F', as_str, 'Bar caption color.'),
    AppSetting('button/background_style', 'BgsPlayerCard', as_str, 'Classic bar background style.'),
    AppSetting('button/background_substyle', 'ProgressBar', as_str, 'Classic bar background substyle.'),
    AppSetting('button/background_color', '', as_str, 'Optional flat background override.'),
))
APP_METADATA = {
    'id': 'alternate_scoretable', 'display_name': 'Alternate Scoretable',
    'description': 'Native result table, personal bests, team scores and player details.',
    'modules': ['apps/alternate_scoretable/app.py', 'apps/alternate_scoretable/results.py',
                'apps/alternate_scoretable/views.py'],
    'entries': ['app/alternate_scoretable'], 'provides': ['feature/alternate_scoretable'],
    'depends_on': ['platform_core', 'ui'],
}


def validate_values(values):
    for key, low, high in (('entries', 5, 20), ('delay_score_display', 0, 30), ('delay_finish_display', 0, 30),
                            ('score_display_time', 1, 120), ('finish_display_time', 1, 120),
                            ('button/width', 1, 20), ('button/height', 1, 20)):
        if not low <= values[key] <= high:
            raise ValueError(f'Alternate Scoretable {key} = {values[key]}; allowed range is {low}-{high}.')
    return values


def validate_config(document, _root):
    section = document.get(SCHEMA.app_id, {})
    validate_values({setting.key: setting.read(section) for setting in SCHEMA.settings})


class AlternateScoretableApp(App):
    def __init__(self):
        super().__init__(app_id='alternate_scoretable', display_name='Alternate Scoretable',
                         description=APP_METADATA['description'], depends_on=('platform_core', 'ui'),
                         entry_modules=('app/alternate_scoretable',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.players = {}
        self.pending = {}
        self.waiting = {}
        self.windows = {}
        self.hidden = set()
        self.native_released = set()
        self.mode = -1
        self.final_ranking = None
        self.cached = None
        self.cached_at = 0
        self.warn_at = 0

    def register_runtime(self, aseco):
        aseco.add_chat_command('scoretable', 'Show Alternate Scoretable or /scoretable help',
                               app='alternate_scoretable', owner='feature/alternate_scoretable',
                               usage='/scoretable [help]', category='chat-server')
        aseco.register_service('ui/scoretable_visibility', self.native_visible, owner='alternate_scoretable')
        aseco.register_service('ui/round_scores_visibility', self.native_round_scores_visible, owner='alternate_scoretable')
        for event, callback in (
            ('onChat_scoretable', self.command), ('onEverySecond', self.tick),
            ('onEndRaceRanking', self.end_race), ('onPlayerFinish1', self.finish),
            ('onPlayerConnect', self.connect), ('onPlayerInfoChanged', self.info),
            ('onPlayerDisconnect', self.disconnect), ('onCheckpoint', self.checkpoint),
            ('onPlayerRetire', self.retire), ('onBeginRound', self.round_start),
            ('onNewChallenge2', self.reset), ('onRestartChallenge2', self.reset),
            ('onStatusChangeTo3', self.race_start), ('onStatusChangeTo5', self.score_status),
            ('onPlayerManialinkPageAnswer', self.answer), ('onUiStyleChanged', self.style),
            ('onWidgetVisibilityChanged', self.visibility),
        ):
            aseco.register_event(event, callback)

    def configuration(self, aseco):
        return validate_values(bind_app_settings(SCHEMA, aseco._base_dir).values)

    def remember(self, player):
        old = self.players.get(player.login, {})
        row = results.player_data(player)
        row['finishes'], row['best'] = old.get('finishes', 0), old.get('best', 0)
        if player.login in self.players or len(self.players) < results.MAX_PLAYERS:
            self.players[player.login] = row

    def current_mode(self, aseco):
        mode = results.number(getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1), -1)
        if mode in results.MODES:
            self.mode = mode
        elif self.mode not in results.MODES:
            from apps.ui.config import _state
            self.mode = _state.last_real_mode
        return self.mode

    async def startup(self, context):
        self.values = self.configuration(context.aseco)
        self.enabled = self.values['enabled']
        self.current_mode(context.aseco)
        for player in context.aseco.server.players.all():
            self.remember(player)
            await self.native(context.aseco, player.login, force=True)
        await self.buttons(context.aseco)
        if is_score_phase(context.aseco):
            await self.score_status(context.aseco)

    def native_visible(self, login, default):
        return self.native_field(login, default, 'show_at_score')

    def native_round_scores_visible(self, login, default):
        return self.native_field(login, default, 'show_at_finish')

    def native_field(self, login, default, automatic):
        replacing = (self.values.get(automatic, False) and login not in self.native_released
                     and self.widget_visible(login))
        return False if self.enabled and (login in self.windows or replacing) else default

    async def native(self, aseco, login, *, force=False):
        renderer = aseco.get_service('ui/custom_ui')
        if callable(renderer):
            await renderer(aseco, login, force=force)

    async def shutdown(self, context):
        self.enabled = False
        if context.aseco.jobs.running:
            context.aseco.jobs.service('alternate_results', POLICY).invalidate()
        self.pending.clear()
        self.waiting.clear()
        for player in context.aseco.server.players.all():
            await self.close(context.aseco, player)
        await self.buttons(context.aseco)
        self.players.clear()
        self.native_released.clear()
        self.cached = None

    def snapshot(self, aseco):
        mode = self.current_mode(aseco)
        for player in aseco.server.players.all():
            self.remember(player)
        track = aseco.server.challenge
        records = getattr(aseco.server, 'records', ())
        local = {record.player.login: record.score for record in records if getattr(record, 'player', None)}
        return {'mode': mode, 'map': str(getattr(track, 'name', '') or '')[:160],
                'challenge_id': results.number(getattr(track, 'id', 0)),
                'players': list(self.players.values()), 'local_pbs': local}

    async def request(self, aseco, player, page=0, source='manual', *, force=False):
        if not self.enabled:
            return
        self.pending.pop(player.login, None)
        self.waiting[player.login] = (player, page, source)
        if self.cached is not None and not force and monotonic() - self.cached_at < 2:
            self.waiting.pop(player.login, None)
            await self.open(aseco, player, self.cached, page, source)
            return
        service = aseco.jobs.service('alternate_results', POLICY)
        if service.outstanding:
            return
        payload = self.snapshot(aseco)
        final = self.final_ranking
        use_final = is_score_phase(aseco) and final is not None
        load_pb = self.values['columns/pb']
        job = JobEnvelope.capture(aseco.capture_job_context(), payload)

        async def operation(envelope):
            snapshot = envelope.payload()
            ranks = final if use_final else await aseco.client.query('GetCurrentRanking', results.MAX_PLAYERS, 0)
            if not isinstance(ranks, list):
                raise ValueError('Invalid dedicated-server ranking response')
            pbs, available = {}, False
            if load_pb:
                try:
                    pool = await localdb_get_pool(aseco)
                    pbs, available = await results.personal_bests(pool, snapshot['challenge_id'], snapshot['players'], snapshot['mode'])
                except Exception:
                    pass
            return results.build(snapshot, ranks, pbs, available)

        async def apply(result):
            waiting, self.waiting = self.waiting, {}
            if not self.enabled:
                return
            if result.status != 'completed':
                if monotonic() >= self.warn_at:
                    logger.warning('[AlternateScoretable] Results refresh failed (%s); existing UI unchanged', result.failure_label)
                    self.warn_at = monotonic() + 60
                for target, _page, source in waiting.values():
                    if aseco.server.players.get_player(target.login) is target:
                        if target.login not in self.windows:
                            self.native_released.add(target.login)
                            await self.native(aseco, target.login, force=True)
                        if source == 'manual':
                            await self.reply(aseco, target, 'Scoretable unavailable; please try again.')
                return
            self.cached, self.cached_at = result.value, monotonic()
            for target, page, source in waiting.values():
                if aseco.server.players.get_player(target.login) is target and self.valid_source(aseco, target, source):
                    await self.open(aseco, target, result.value, page, source)

        if service.submit(job, operation, apply) not in (Admission.ACCEPTED, Admission.DUPLICATE):
            for target, _page, _source in self.waiting.values():
                if target.login not in self.windows:
                    self.native_released.add(target.login)
                    await self.native(aseco, target.login)
            self.waiting.clear()
            await self.reply(aseco, player, 'Scoretable refresh deferred; please try again.')

    def valid_source(self, aseco, player, source):
        if source == 'manual':
            return True
        return self.widget_visible(player.login) and (is_score_phase(aseco) if source == 'score' else not is_score_phase(aseco))

    def widget_visible(self, login):
        from apps.ui.config import _state
        return login not in self.hidden and _state.player_visible.get(login, True)

    async def open(self, aseco, player, data, page, source, detail=None, expires=None):
        xml, page = views.window(data, self.values, player.login, page, detail)
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)
        if expires is None:
            expires = (monotonic() + self.values['score_display_time' if source == 'score' else 'finish_display_time']
                       if source != 'manual' else 0)
        self.windows[player.login] = (data, page, source, detail, expires)
        self.native_released.discard(player.login)
        await self.native(aseco, player.login, force=True)

    async def close(self, aseco, player, *, release=True):
        if release:
            self.native_released.add(player.login)
        else:
            self.native_released.discard(player.login)
        self.pending.pop(player.login, None)
        self.waiting.pop(player.login, None)
        self.windows.pop(player.login, None)
        try:
            await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login,
                             f'<manialink id="{views.ML_WINDOW}"></manialink><manialink id="{views.ML_SUBWIN}"></manialink>', 0, False)
        finally:
            await self.native(aseco, player.login)

    async def draw_button(self, aseco, player):
        visible = self.enabled and self.values['button/enabled'] and self.widget_visible(player.login) and not is_score_phase(aseco)
        xml = views.button(self.values) if visible else f'<manialink id="{views.ML_BUTTON}"></manialink>'
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def buttons(self, aseco):
        for player in aseco.server.players.all():
            await self.draw_button(aseco, player)

    async def tick(self, aseco, _data=None):
        if not self.enabled:
            return
        now = monotonic()
        for login, window in list(self.windows.items()):
            player = aseco.server.players.get_player(login)
            if player is not None and window[4] and now >= window[4]:
                await self.close(aseco, player)
        for login, (player, due, source) in list(self.pending.items()):
            if now >= due:
                self.pending.pop(login, None)
                if aseco.server.players.get_player(login) is player and self.valid_source(aseco, player, source):
                    await self.request(aseco, player, source=source)
        if self.waiting and not aseco.jobs.service('alternate_results', POLICY).outstanding:
            player, page, source = next(iter(self.waiting.values()))
            if aseco.server.players.get_player(player.login) is player:
                await self.request(aseco, player, page, source, force=True)

    async def finish(self, aseco, record):
        player = getattr(record, 'player', None)
        score = results.number(getattr(record, 'score', 0))
        if not self.enabled or player is None or results.spectator(player) or is_score_phase(aseco):
            return
        if score <= 0:
            await self.retire(aseco, player)
            return
        self.remember(player)
        row = self.players.get(player.login)
        if row is not None:
            row['finishes'] += 1
            row['best'] = results.better(row['best'], score, self.current_mode(aseco))
        self.cached_at = 0
        if self.values['show_at_finish']:
            self.native_released.discard(player.login)
            self.pending[player.login] = (player, monotonic() + self.values['delay_finish_display'], 'finish')
            await self.native(aseco, player.login, force=True)

    async def end_race(self, aseco, rankings):
        self.current_mode(aseco)
        self.final_ranking = [dict(row) for row in rankings[:results.MAX_PLAYERS] if isinstance(row, dict)] if isinstance(rankings, list) else None
        self.cached_at = 0
        self.waiting.clear()
        aseco.jobs.service('alternate_results', POLICY).invalidate()
        for player in aseco.server.players.all():
            await self.close(aseco, player, release=False)
            if self.enabled and self.values['show_at_score']:
                self.pending[player.login] = (player, monotonic() + self.values['delay_score_display'], 'score')
            await self.native(aseco, player.login, force=True)
        await self.buttons(aseco)

    async def score_status(self, aseco, _data=None):
        if self.enabled and self.values['show_at_score']:
            for player in aseco.server.players.all():
                if player.login not in self.windows and player.login not in self.pending:
                    self.native_released.discard(player.login)
                    self.pending[player.login] = (player, monotonic() + self.values['delay_score_display'], 'score')
                await self.native(aseco, player.login, force=True)
        await self.buttons(aseco)

    async def round_start(self, aseco, _data=None):
        self.final_ranking = None
        self.cached_at = 0
        self.waiting.clear()
        aseco.jobs.service('alternate_results', POLICY).invalidate()
        for player in aseco.server.players.all():
            await self.close(aseco, player, release=False)
            await self.native(aseco, player.login, force=True)
        await self.buttons(aseco)

    async def race_start(self, aseco, _data=None):
        await self.round_start(aseco)

    async def reset(self, aseco, _data=None):
        self.players.clear()
        self.cached = None
        self.current_mode(aseco)
        await self.round_start(aseco)
        for player in aseco.server.players.all():
            self.remember(player)

    async def checkpoint(self, aseco, data):
        if len(data) >= 2:
            player = aseco.server.players.get_player(data[1])
            if player is not None and (player.login in self.windows or player.login in self.pending or player.login in self.waiting):
                await self.close(aseco, player)

    async def retire(self, aseco, player):
        if player.login in self.windows or player.login in self.pending or player.login in self.waiting:
            await self.close(aseco, player)

    async def connect(self, aseco, player):
        self.hidden.discard(player.login)
        self.native_released.discard(player.login)
        self.remember(player)
        await self.native(aseco, player.login, force=True)
        await self.draw_button(aseco, player)
        if self.enabled and is_score_phase(aseco) and self.values['show_at_score']:
            self.pending[player.login] = (player, monotonic() + self.values['delay_score_display'], 'score')

    async def info(self, _aseco, player):
        self.remember(player)

    async def disconnect(self, _aseco, player):
        self.pending.pop(player.login, None)
        self.waiting.pop(player.login, None)
        self.windows.pop(player.login, None)
        self.hidden.discard(player.login)
        self.native_released.discard(player.login)
        if player.login in self.players:
            self.players[player.login]['connected'] = False
        self.cached_at = 0

    async def visibility(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player is None:
            return
        if data['visible']:
            self.hidden.discard(player.login)
            self.native_released.discard(player.login)
        else:
            self.hidden.add(player.login)
            await self.close(aseco, player)
        await self.native(aseco, player.login)
        await self.draw_button(aseco, player)

    async def style(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player is not None:
            window = self.windows.get(player.login)
            if window is not None:
                await self.open(aseco, player, *window[:3], detail=window[3], expires=window[4])
            await self.draw_button(aseco, player)

    async def reply(self, aseco, player, message):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', message, player.login)

    async def command(self, aseco, command):
        player = command['author']
        if not self.enabled:
            await self.reply(aseco, player, 'Alternate Scoretable is disabled.')
        elif str(command.get('params') or '').strip():
            await self.reply(aseco, player, '/scoretable: results, PBs and player details. Click a name for details. '
                'Result = time in TA/Team, points in Rounds/Cup/Stunts, checkpoint progress in Laps. '
                'Finishes are counted since this app started on the current map; ladder rank is cached.')
        else:
            await self.request(aseco, player)

    async def answer(self, aseco, data):
        if not self.enabled or len(data) < 3:
            return
        try:
            action = int(data[2])
        except (ValueError, TypeError):
            return
        player = aseco.server.players.get_player(data[1])
        if player is None:
            return
        if action == views.CLOSE:
            await self.close(aseco, player)
        elif action == views.OPEN and self.values['button/enabled'] and self.widget_visible(player.login):
            await self.request(aseco, player)
        elif player.login in self.windows:
            result, page, source, _detail, expires = self.windows[player.login]
            if action == views.REFRESH:
                await self.request(aseco, player, page, source, force=True)
            elif action in (views.PREVIOUS, views.NEXT, views.BACK) or views.PLAYER_BASE <= action < views.PLAYER_BASE + len(result['rows']):
                detail = action - views.PLAYER_BASE if action >= views.PLAYER_BASE else None
                page += 1 if action == views.NEXT else -1 if action == views.PREVIOUS else 0
                await self.open(aseco, player, result, page, source, detail=detail, expires=expires)


APP_CLASS = AlternateScoretableApp
APP_INSTANCE = AlternateScoretableApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(aseco._base_dir)
    values = APP_INSTANCE.configuration(aseco)
    aseco.jobs.service('alternate_results', POLICY).invalidate()
    APP_INSTANCE.pending.clear()
    APP_INSTANCE.waiting.clear()
    for player in aseco.server.players.all():
        await APP_INSTANCE.close(aseco, player)
    APP_INSTANCE.values, APP_INSTANCE.enabled = values, values['enabled']
    APP_INSTANCE.native_released.clear()
    for player in aseco.server.players.all():
        await APP_INSTANCE.native(aseco, player.login, force=True)
    APP_INSTANCE.cached_at = 0
    await APP_INSTANCE.buttons(aseco)
