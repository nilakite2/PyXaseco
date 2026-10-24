"""Optional population history, inspired by [GB]-FlyveHest's ServerStats (2008)."""

from datetime import datetime, timezone
import logging
from time import monotonic

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_int, as_str, bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.helpers import _send_multipage, strip_colors

from . import graph, storage


logger = logging.getLogger(__name__)
REFRESH_ACTION = 8570000
POLICY = JobPolicy(capacity=1, deadline_seconds=30)
SCHEMA = AppSettingsSchema(app_id='serverstats', settings=(
    AppSetting('enabled', True, as_bool, 'Record optional server population statistics.'),
    AppSetting('interval_seconds', 300, as_int, 'Sampling interval: 60-3600 seconds.'),
    AppSetting('retention_hours', 168, as_int, 'Keep population samples for 1-8760 hours; peaks are retained.'),
    AppSetting('graph/enabled', False, as_bool, 'Export an SVG graph for external websites.'),
    AppSetting('graph/file', 'stats/serverstats.svg', as_str, 'SVG path relative to the controller folder.'),
    AppSetting('graph/width', 900, as_int, 'Graph width, 320-1920 pixels.'),
    AppSetting('graph/height', 240, as_int, 'Graph height, 160-1080 pixels.'),
))
APP_METADATA = {
    'id': 'serverstats', 'display_name': 'ServerStats',
    'description': 'Optional player/spectator history, sampled peaks and SVG export.',
    'modules': ['apps/serverstats/app.py', 'apps/serverstats/storage.py', 'apps/serverstats/graph.py'],
    'entries': ['app/serverstats'], 'provides': ['feature/serverstats'], 'depends_on': ['platform_core'],
}


def population(aseco):
    players = aseco.server.players.all()
    spectators = sum(bool(getattr(player, 'isspectator', False) or
                          int(getattr(player, 'spectatorstatus', 0) or 0) % 10) for player in players)
    return len(players) - spectators, spectators


def date_text(value):
    return value.strftime('%Y-%m-%d %H:%M') if isinstance(value, datetime) else str(value or '-')


class ServerStatsApp(App):
    def __init__(self):
        super().__init__(app_id='serverstats', display_name='ServerStats',
                         description=APP_METADATA['description'], depends_on=('platform_core',),
                         entry_modules=('app/serverstats',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.next_at = 0
        self.schema_pool = None
        self.cached = None
        self.last_error = ''

    def register_runtime(self, aseco):
        aseco.add_chat_command('serverstats', 'Displays sampled server population history',
                               app='serverstats', owner='feature/serverstats',
                               usage='/serverstats [history|help]', category='chat-server')
        for event, callback in (
            ('onChat_serverstats', self.command), ('onEverySecond', self.tick),
            ('onPlayerManialinkPageAnswer', self.answer), ('onPlayerDisconnect', self.disconnect),
        ):
            aseco.register_event(event, callback)

    def configure(self, aseco):
        values = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None)).values
        if not 60 <= values['interval_seconds'] <= 3600 or not 1 <= values['retention_hours'] <= 8760:
            raise ValueError('ServerStats requires interval_seconds 60-3600 and retention_hours 1-8760.')
        if values['graph/enabled']:
            graph.output_path(aseco._base_dir, values['graph/file'])
        self.values, self.enabled = values, values['enabled']
        self.next_at = 0

    async def startup(self, context):
        self.configure(context.aseco)

    async def shutdown(self, context):
        self.enabled = False
        # The controller stops/joins the background runtime before app teardown.
        self.cached = None

    async def tick(self, aseco, _data=None):
        if not self.enabled or monotonic() < self.next_at:
            return
        server = str(getattr(aseco.server, 'serverlogin', '') or '')
        if not server:
            return
        service = aseco.jobs.service('serverstats_samples', POLICY)
        if service.outstanding:
            return
        self.next_at = monotonic() + self.values['interval_seconds']
        pool = await localdb_get_pool(aseco)
        if pool is None:
            self.last_error = 'Database unavailable'
            logger.warning('[ServerStats] Database unavailable; sampling deferred')
            return
        players, spectators = population(aseco)
        values = dict(self.values)
        payload = {'server': server, 'at': datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat(sep=' '),
                   'players': players, 'spectators': spectators,
                   'interval_seconds': values['interval_seconds'], 'retention_hours': values['retention_hours']}
        needs_schema = pool is not self.schema_pool
        root = aseco._base_dir
        title = strip_colors(str(getattr(aseco.server, 'name', '') or server))
        job = JobEnvelope.capture(aseco.capture_job_context(), payload)

        async def operation(envelope):
            if needs_schema:
                await storage.ensure_schema(pool)
            result = await storage.sample(pool, envelope.payload())
            result['graph_error'] = ''
            if values['graph/enabled']:
                try:
                    await file_io(graph.write, root, values['graph/file'], result, title,
                                  values['graph/width'], values['graph/height'])
                except (OSError, ValueError) as error:
                    result['graph_error'] = type(error).__name__
            return result

        async def apply(result):
            if result.status == 'completed':
                self.schema_pool, self.cached, self.last_error = pool, result.value, ''
                if result.value['graph_error']:
                    logger.warning('[ServerStats] Sample saved, but graph export failed (%s)', result.value['graph_error'])
            else:
                self.last_error = 'Last sample failed'
                logger.warning('[ServerStats] Sampling failed (%s); next attempt waits for the sampling interval', result.failure_label)

        outcome = service.submit(job, operation, apply, current_map=False)
        if outcome not in (Admission.ACCEPTED, Admission.DUPLICATE):
            self.last_error = 'Sampling deferred'

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def command(self, aseco, command):
        player = command['author']
        params = str(command.get('params') or '').strip().lower()
        if params not in ('', 'history'):
            await self.reply(aseco, player, '{#message}/serverstats: live counts and sampled peaks/averages; '
                             '/serverstats history: retained activity. Times are UTC.')
            return
        if not self.enabled:
            await self.reply(aseco, player, '{#message}ServerStats is disabled.')
            return
        data = self.cached
        if not data or data['server'] != aseco.server.serverlogin:
            await self.reply(aseco, player, '{#message}ServerStats is waiting for its first successful sample.')
            return
        if params == 'history':
            rows = [[date_text(row['At']), f'{float(row["Players"] or 0):.1f}',
                     f'{float(row["Spectators"] or 0):.1f}',
                     f'{float(row["Players"] or 0) + float(row["Spectators"] or 0):.1f}']
                    for row in reversed(data['history'])]
            title = f'ServerStats - History (UTC, {data["bucket_seconds"]}s buckets)'
        else:
            players, spectators = population(aseco)
            averages, peaks = data['averages'], data['peaks']
            def average(*keys):
                return [f'{float(averages.get(key) or 0):.1f}' for key in keys]
            rows = [['Live now', str(players), str(spectators), str(players + spectators)],
                    ['Last sample', str(data['players']), str(data['spectators']), str(data['players'] + data['spectators'])],
                    ['Average: last hour'] + average('HourPlayers', 'HourSpectators', 'HourTotal'),
                    ['Average: retained history'] + average('AvgPlayers', 'AvgSpectators', 'AvgTotal'),
                    ['Highest sampled'] + [str(peaks.get(key, 0)) for key in ('PeakPlayers', 'PeakSpectators', 'PeakTotal')],
                    ['Peak times (UTC)'] + [date_text(peaks.get(key)) for key in ('PlayersPeakAt', 'SpectatorsPeakAt', 'TotalPeakAt')],
                    ['Last sample (UTC)', data['at'], '', ''],
                    ['Samples retained', str(averages.get('Samples', 0)), '', ''],
                    ['Interval / retention', f'{self.values["interval_seconds"]}s / {self.values["retention_hours"]}h', '', ''],
                    ['Sampling status', self.last_error or 'OK', '', '']]
            title = 'ServerStats - Population overview'
        if not rows:
            await self.reply(aseco, player, '{#message}No retained history yet.')
            return
        player.msgs = [[1, title, [1.9, .55, .45, .45, .45],
                        ['Icons128x128_1', 'Rankings'], None, None, REFRESH_ACTION]]
        player.msgs.extend([[['Metric / time (UTC)', 'Players', 'Spectators', 'Total']] + rows[i:i + 14]
                            for i in range(0, len(rows), 14)])
        player._serverstats_window, player._serverstats_view = player.msgs, params
        await _send_multipage(aseco, player)

    async def answer(self, aseco, data):
        if len(data) < 3 or str(data[2]) not in ('0', str(REFRESH_ACTION)):
            return
        player = aseco.server.players.get_player(data[1])
        if player is None:
            return
        if str(data[2]) == '0':
            player._serverstats_window = None
            return
        window = getattr(player, '_serverstats_window', None)
        if window is not None and window is getattr(player, 'msgs', None):
            await self.command(aseco, {'author': player, 'params': player._serverstats_view})

    async def disconnect(self, _aseco, player):
        player._serverstats_window = None


APP_CLASS = ServerStatsApp
APP_INSTANCE = ServerStatsApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    APP_INSTANCE.configure(aseco)
    aseco.jobs.service('serverstats_samples', POLICY).invalidate()
