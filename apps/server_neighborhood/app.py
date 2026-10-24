"""Optional, local-folder Server Neighborhood inspired by undef's XAseco plugin."""

import asyncio
import logging
from time import monotonic, time
import xml.etree.ElementTree as ET

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_float, as_int, as_str,
    bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase

from . import storage, views


logger = logging.getLogger(__name__)
POLICY = JobPolicy(capacity=1, deadline_seconds=30)
SCHEMA = AppSettingsSchema(app_id='server_neighborhood', settings=(
    AppSetting('enabled', True, as_bool, 'Enable local-folder Server Neighborhood.'),
    AppSetting('directory', 'server-neighborhood', as_str, 'Use the SAME absolute local folder on all linked instances.'),
    AppSetting('server_logins', '', as_str, 'Comma-separated server logins; empty discovers all status files (maximum 100).'),
    AppSetting('refresh_interval', 10, as_int, 'Refresh interval, 5-300 seconds.'),
    AppSetting('stale_seconds', 60, as_int, 'Mark stale after 10-3600 seconds; at least twice the refresh interval.'),
    AppSetting('widget/enabled', True, as_bool, 'Show a rotating server summary; click to open /servers.'),
    AppSetting('widget/entries', 3, as_int, 'Visible neighboring servers, 1-10.'),
    AppSetting('widget/pos_x', -64.7, as_float, 'Widget X position.'),
    AppSetting('widget/pos_y', -8.3, as_float, 'Widget Y position.'),
    AppSetting('widget/width', 21.0, as_float, 'Widget width, 15.5-40.'),
    AppSetting('widget/show_on_score', False, as_bool, 'Also show the widget on the scoreboard.'),
))
APP_METADATA = {
    'id': 'server_neighborhood', 'display_name': 'Server Neighborhood',
    'description': 'Local server status exchange, browser and native join/spectate links.',
    'modules': ['apps/server_neighborhood/app.py', 'apps/server_neighborhood/storage.py',
                'apps/server_neighborhood/views.py'],
    'entries': ['app/server_neighborhood'], 'provides': ['feature/server_neighborhood'],
    'depends_on': ['platform_core', 'ui'],
}


def checked_configuration(values, root):
    for key, minimum, maximum in (('refresh_interval', 5, 300), ('widget/entries', 1, 10),
                                   ('widget/width', 15.5, 40)):
        if not minimum <= values[key] <= maximum:
            raise ValueError(f'Neighborhood {key} = {values[key]}; allowed range is {minimum}-{maximum}.')
    if not 2 * values['refresh_interval'] <= values['stale_seconds'] <= 3600:
        raise ValueError(f'Neighborhood stale_seconds = {values["stale_seconds"]}; allowed range is '
                         f'{2 * values["refresh_interval"]}-3600 for this refresh interval.')
    names = tuple(dict.fromkeys(storage.valid_login(name.strip())
                  for name in values['server_logins'].split(',') if name.strip()))
    if len(names) > storage.MAX_SERVERS:
        raise ValueError('Neighborhood supports at most 100 selected servers.')
    return values, storage.directory(root, values['directory']), names, storage.owner(root)


def validate_config(document, root):
    """Validate a proposed TOML edit before the apps manager saves it."""
    section = document.get(SCHEMA.app_id, {})
    checked_configuration({setting.key: setting.read(section) for setting in SCHEMA.settings}, root)


class ServerNeighborhoodApp(App):
    def __init__(self):
        super().__init__(app_id='server_neighborhood', display_name='Server Neighborhood',
                         description=APP_METADATA['description'], depends_on=('platform_core', 'ui'),
                         entry_modules=('app/server_neighborhood',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.folder = None
        self.publisher = ''
        self.logins = ()
        self.rows = []
        self.waiting = {}
        self.hidden = set()
        self.next_at = 0
        self.rotation = -1
        self.last_mode = -1
        self.last_error = ''
        self.warn_at = 0
        self.published = None
        self.generation = 0
        self.io_lock = asyncio.Lock()

    def register_runtime(self, aseco):
        aseco.add_chat_command('servers', 'Browse neighboring servers', app='server_neighborhood',
                               owner='feature/server_neighborhood', usage='/servers [help]', category='chat-server')
        for event, callback in (
            ('onChat_servers', self.command), ('onEverySecond', self.tick),
            ('onPlayerConnect', self.connect), ('onPlayerDisconnect', self.disconnect),
            ('onPlayerManialinkPageAnswer', self.answer),
            ('onWidgetVisibilityChanged', self.visibility), ('onUiStyleChanged', self.style),
            ('onNewChallenge2', self.transition), ('onBeginRound', self.transition),
            ('onEndRace', self.transition), ('onStatusChangeTo3', self.transition),
            ('onStatusChangeTo5', self.transition),
        ):
            aseco.register_event(event, callback)

    def read_configuration(self, aseco):
        values = bind_app_settings(SCHEMA, aseco._base_dir).values
        return checked_configuration(values, aseco._base_dir)

    def apply_configuration(self, configuration):
        self.values, self.folder, self.logins, self.publisher = configuration
        self.enabled, self.next_at = self.values['enabled'], 0

    def configure(self, aseco):
        self.apply_configuration(self.read_configuration(aseco))

    async def startup(self, context):
        self.configure(context.aseco)
        await self.tick(context.aseco)

    async def retire_status(self):
        async with self.io_lock:
            if self.published is not None:
                folder, snapshot, publisher = self.published
                snapshot = dict(snapshot, updated=time(), online=False)
                try:
                    await file_io(storage.write, folder, snapshot, publisher)
                except (OSError, ValueError, ET.ParseError):
                    logger.warning('[ServerNeighborhood] Could not mark own status offline; freshness timeout will apply')
                self.published = None

    async def shutdown(self, context):
        self.enabled = False
        self.generation += 1
        if context.aseco.jobs.running:
            context.aseco.jobs.service('server_neighbors', POLICY).invalidate()
        await self.retire_status()
        self.waiting.clear()
        await self.refresh(context.aseco)
        self.rows.clear()
        self.hidden.clear()

    def snapshot(self, aseco):
        server = aseco.server
        login = str(getattr(server, 'serverlogin', '') or '')
        if not login:
            return None
        storage.valid_login(login)
        players = list(server.players.all())
        spectators = sum(bool(getattr(player, 'isspectator', False) or
                              int(getattr(player, 'spectatorstatus', 0) or 0) % 10) for player in players)
        mode = int(getattr(getattr(server, 'gameinfo', None), 'mode', -1))
        if mode in views.MODES:
            self.last_mode = mode
        track = getattr(server, 'challenge', None)
        def short(obj, name, default=''):
            return str(getattr(obj, name, default) or default)[:160]
        return {'login': login, 'name': short(server, 'name', login), 'updated': time(), 'online': True,
                'mode': self.last_mode, 'pack': short(server, 'packmask'),
                'players': len(players) - spectators, 'spectators': spectators,
                'maxplayers': int(getattr(server, 'maxplay', 0)),
                'maxspectators': int(getattr(server, 'maxspec', 0)),
                'map': short(track, 'name'), 'author': short(track, 'author'),
                'environment': short(track, 'environment')}

    async def tick(self, aseco, _data=None):
        if not self.enabled or monotonic() < self.next_at:
            return
        service = aseco.jobs.service('server_neighbors', POLICY)
        if service.outstanding:
            return
        data = self.snapshot(aseco)
        if data is None:
            return
        self.next_at = monotonic() + self.values['refresh_interval']
        folder, publisher, logins, generation = self.folder, self.publisher, self.logins, self.generation
        job = JobEnvelope.capture(aseco.capture_job_context(), data)

        def exchange(snapshot):
            errors = []
            try:
                storage.write(folder, snapshot, publisher)
            except (OSError, ValueError, ET.ParseError) as error:
                errors.append(str(error))
            rows, read_errors = storage.scan(folder, logins)
            return rows, errors + read_errors

        async def operation(envelope):
            async with self.io_lock:
                if not self.enabled or generation != self.generation:
                    return [], []
                self.published = (folder, envelope.payload(), publisher)
                return await file_io(exchange, envelope.payload())

        async def apply(result):
            if not self.enabled:
                return
            if result.status == 'completed':
                self.rows, errors = result.value
                error = '; '.join(errors[:3])
            else:
                error = 'Status refresh failed (' + result.failure_label + ')'
            if error and (error != self.last_error or monotonic() >= self.warn_at):
                logger.warning('[ServerNeighborhood] %s', error)
                self.warn_at = monotonic() + 60
            self.last_error = error
            self.rotation += 1
            await self.refresh(aseco)
            waiting, self.waiting = self.waiting, {}
            for login, (player, marker, page) in waiting.items():
                if aseco.server.players.get_player(login) is player and getattr(player, 'msgs', None) is marker:
                    await self.open(aseco, player, page)

        if service.submit(job, operation, apply, current_map=False) not in (Admission.ACCEPTED, Admission.DUPLICATE):
            self.last_error = 'Status refresh deferred'
            self.waiting.clear()

    async def draw(self, aseco, player):
        from apps.ui.config import _state
        shown = (self.enabled and self.values['widget/enabled'] and player.login not in self.hidden and
                 _state.player_visible.get(player.login, True) and
                 (self.values['widget/show_on_score'] or not is_score_phase(aseco)))
        xml = (views.widget(self.rows, self.values, aseco.server.serverlogin, max(0, self.rotation)) if shown
               else f'<manialink id="{views.ML_WIDGET}"></manialink>')
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def refresh(self, aseco):
        for player in aseco.server.players.all():
            await self.draw(aseco, player)

    async def connect(self, aseco, player):
        self.hidden.discard(player.login)
        self.waiting.pop(player.login, None)
        await self.draw(aseco, player)

    async def disconnect(self, _aseco, player):
        self.hidden.discard(player.login)
        self.waiting.pop(player.login, None)
        player._neighborhood_window = None

    async def visibility(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player:
            if data['visible']:
                self.hidden.discard(player.login)
            else:
                self.hidden.add(player.login)
            await self.draw(aseco, player)

    async def style(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player:
            await self.draw(aseco, player)

    async def transition(self, aseco, _data=None):
        self.next_at = 0
        await self.tick(aseco)
        await self.refresh(aseco)

    async def open(self, aseco, player, page=0):
        xml, page = views.window(self.rows, self.values, aseco.server.serverlogin, page)
        player.msgs = []
        player._neighborhood_window = player.msgs
        player._neighborhood_page = page
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def request(self, aseco, player, page=0):
        if len(self.waiting) >= 1000 and player.login not in self.waiting:
            return
        self.waiting[player.login] = (player, getattr(player, 'msgs', None), page)
        self.next_at = 0
        await self.tick(aseco)

    async def command(self, aseco, command):
        player = command['author']
        if str(command.get('params') or '').strip() or not self.enabled:
            message = ('/servers: browse linked servers and join or spectate. Statuses refresh in the background.'
                       if self.enabled else 'Server Neighborhood is disabled.')
            await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', message, player.login)
            return
        await self.request(aseco, player)

    async def answer(self, aseco, answer):
        if not self.enabled or len(answer) < 3:
            return
        try:
            action = int(answer[2])
        except (ValueError, TypeError):
            return
        player = aseco.server.players.get_player(answer[1])
        if player is None:
            return
        if action in (0, views.ML_WINDOW):
            self.waiting.pop(player.login, None)
            player._neighborhood_window = None
        elif action == views.OPEN:
            if player.login not in self.hidden and (not is_score_phase(aseco) or self.values['widget/show_on_score']):
                await self.request(aseco, player)
        elif (getattr(player, '_neighborhood_window', None) is not None and
              getattr(player, '_neighborhood_window', None) is getattr(player, 'msgs', None)):
            page = getattr(player, '_neighborhood_page', 0)
            if action == views.REFRESH:
                await self.request(aseco, player, page)
            elif action in (views.PREVIOUS, views.NEXT):
                await self.open(aseco, player, page + (1 if action == views.NEXT else -1))


APP_CLASS = ServerNeighborhoodApp
APP_INSTANCE = ServerNeighborhoodApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(aseco._base_dir)
    configuration = APP_INSTANCE.read_configuration(aseco)
    APP_INSTANCE.enabled = False
    APP_INSTANCE.generation += 1
    aseco.jobs.service('server_neighbors', POLICY).invalidate()
    await APP_INSTANCE.retire_status()
    APP_INSTANCE.apply_configuration(configuration)
    APP_INSTANCE.rows.clear()
    APP_INSTANCE.waiting.clear()
    await APP_INSTANCE.tick(aseco)
    await APP_INSTANCE.refresh(aseco)
