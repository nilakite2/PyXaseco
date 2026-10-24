"""Optional Stunts provider and retained score/replay delivery."""

import asyncio
from collections import OrderedDict
import logging
from pathlib import Path
import re
from time import monotonic
from uuid import uuid4

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, as_int, as_str, bind_app_settings
from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
from pyxaseco.core.file_io import file_io
from pyxaseco.core.retained_delivery import delivery, PreparationDeferred, PreparationRejected
from pyxaseco.models import Gameinfo

from .api import Client, MapNotFound, base_url, records


logger = logging.getLogger(__name__)
POLICY = JobPolicy(capacity=1, deadline_seconds=100)
SCHEMA = AppSettingsSchema(app_id='records_ultimania', settings=(
    AppSetting('enabled', True, as_bool, 'Enable Ultimania Stunts records.'),
    AppSetting('api_base', 'http://ultimania5.askuri.de', as_str, 'Ultimania v5 server. HTTPS verifies certificates normally.'),
    AppSetting('refresh_interval', 180, as_int, 'Seconds between record refreshes (30-3600).'),
    AppSetting('request_timeout', 15, as_int, 'HTTP request deadline (1-30 seconds).'),
    AppSetting('register_maps', True, as_bool, 'Register missing Stunts maps with Ultimania.'),
    AppSetting('submit_records', True, as_bool, 'Submit improved scores and player logins/nicknames.'),
    AppSetting('upload_replays', True, as_bool, 'Upload best ghosts; requires local dedicated replay storage.'),
    AppSetting('show_record_messages', True, as_bool, 'Announce confirmed score improvements.'),
    AppSetting('public_rank_limit', 25, as_int, 'Public announcement rank limit; 0 makes all messages private.'),
))


def current_uid(aseco):
    return str(getattr(aseco.server.challenge, 'uid', '') or '')


def stunts(aseco):
    return getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.STNT


def display_stunts(aseco):
    if stunts(aseco):
        return True
    if getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.SCOR:
        from apps.ui.config import _state
        return _state.last_real_mode == Gameinfo.STNT
    return False


def replay_path(aseco, filename):
    if not re.fullmatch(r'[0-9a-f]{32}\.Replay\.Gbx', filename):
        raise ValueError('Invalid Ultimania replay filename.')
    gamedir = str(getattr(aseco.server, 'gamedir', '') or '')
    if not gamedir or not Path(gamedir).is_absolute():
        raise ValueError('Ultimania replay capture requires a local absolute GameData folder.')
    root = (Path(gamedir) / 'Tracks' / 'Replays').resolve()
    folder = root / 'PyXasecoUltimania'
    path = folder / filename
    if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Unsafe Ultimania replay path.')
    return path


def admit_replay(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    files = list(path.parent.glob('*.Replay.Gbx'))
    if len(files) >= 1000 or sum(file.stat().st_size for file in files) >= 2 * 1024 ** 3:
        raise ValueError('Ultimania replay storage limit reached; retained files were preserved.')


def read_replay(path):
    with path.open('rb') as stream:
        content = stream.read(64 * 1024 ** 2 + 1)
    if not content or len(content) > 64 * 1024 ** 2:
        raise ValueError('Ultimania replay is empty or larger than 64 MiB.')
    return content


class Runtime:
    def __init__(self):
        self.enabled = False
        self.values = {}
        self.uid = ''
        self.available = False
        self.rows = []
        self.next_due = 0
        self.pending_windows = {}
        self.queued = OrderedDict()
        self.records_revision = 0
        self.delivery_retry_after = 0

    def register(self, aseco):
        aseco.register_service('service/records_ultimania', self, owner='records_ultimania')
        for event, callback in (('onNewChallenge', self.sync), ('onRestartChallenge', self.sync),
                                ('onSync', self.sync), ('onEverySecond', self.tick),
                                ('onPlayerFinish1', self.finish),
                                ('onPlayerDisconnect', self.disconnect)):
            aseco.register_event(event, callback)
        for name in ('ultirecs', 'ultilist', 'ultiwindow'):
            aseco.add_chat_command(name, 'Show Ultimania Stunts records', app='records_ultimania', owner='service/records_ultimania')
            aseco.register_event('onChat_' + name, self.command)

    def configure(self, aseco):
        values = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None)).values
        values['api_base'] = base_url(values['api_base'])
        if (not 30 <= values['refresh_interval'] <= 3600 or not 1 <= values['request_timeout'] <= 30
                or not 0 <= values['public_rank_limit'] <= 10000):
            raise ValueError('Invalid Ultimania refresh interval or request timeout.')
        self.values, self.enabled = values, values['enabled']
        self.uid, self.available, self.rows, self.next_due = '', False, [], 0
        self.pending_windows.clear()
        self.queued.clear()
        self.records_revision += 1
        self.delivery_retry_after = 0
        aseco.jobs.service('ultimania_lookup', POLICY).invalidate()
        self.dispatcher(aseco)

    def active(self, aseco):
        return self.enabled and display_stunts(aseco) and self.available and self.uid == current_uid(aseco)

    async def notify(self, aseco):
        await aseco.release_event('onUltimaniaRecordsLoaded', current_uid(aseco))

    async def sync(self, aseco, _data=None):
        self.uid, self.available, self.rows, self.next_due = current_uid(aseco), False, [], 0
        self.pending_windows.clear()
        self.queued.clear()
        self.records_revision += 1
        aseco.jobs.service('ultimania_lookup', POLICY).invalidate()
        await self.notify(aseco)
        await self.tick(aseco)

    async def tick(self, aseco, _data=None):
        if not self.enabled or not stunts(aseco):
            if self.available and not display_stunts(aseco):
                self.available, self.rows = False, []
                await self.notify(aseco)
            return
        uid = current_uid(aseco)
        if not uid:
            return
        if uid != self.uid:
            await self.sync(aseco)
            return
        service = aseco.jobs.service('ultimania_lookup', POLICY)
        if monotonic() < self.next_due or service.outstanding:
            return
        values = dict(self.values)
        revision = self.records_revision
        client = Client(aseco, values['api_base'], values['request_timeout'])

        async def operation(_job):
            try:
                try:
                    rows = await client.get_records(uid)
                except MapNotFound:
                    if not values['register_maps']:
                        return False, [], ''
                    await client.register_map(uid, name)
                    rows = await client.get_records(uid)
                return True, rows, ''
            except MapNotFound:
                return False, [], ''
            except Exception as error:
                return False, [], str(error)

        async def apply(result):
            if result.status == 'completed':
                available, rows, error = result.value
                if available and self.records_revision != revision:
                    rows = records(rows + self.rows, uid)
                self.available, self.rows = available, rows
            else:
                self.available, self.rows, error = False, [], result.failure_label
            self.next_due = monotonic() + values['refresh_interval']
            if error:
                logger.warning('[Ultimania] Records unavailable: %s', error)
            await self.notify(aseco)
            waiting, self.pending_windows = self.pending_windows, {}
            for login, player in waiting.items():
                if aseco.server.players.get_player(login) is player:
                    await self.show(aseco, player)

        name = str(getattr(aseco.server.challenge, 'name', '') or uid)
        service.submit(JobEnvelope.capture(aseco.capture_job_context(), {'uid': uid}), operation, apply)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors('{#server}> ' + text), player.login)

    async def command(self, aseco, command):
        player = command['author']
        if not self.enabled or not stunts(aseco):
            await self.reply(aseco, player, 'Ultimania records are available in Stunts mode only.')
            return
        if str(command.get('params') or '').strip().lower() == 'help':
            await self.reply(aseco, player, '/ultirecs (aliases: /ultilist, /ultiwindow) - current Stunts leaderboard.')
            return
        if self.active(aseco):
            await self.show(aseco, player)
        else:
            if len(self.pending_windows) >= 1000:
                await self.reply(aseco, player, 'Ultimania is busy; please try again shortly.')
                return
            if self.uid != current_uid(aseco):
                await self.sync(aseco)
            self.pending_windows[player.login] = player
            self.next_due = 0
            await self.tick(aseco)

    async def show(self, aseco, player):
        from .records_widget import show_window
        if not self.active(aseco):
            await self.reply(aseco, player, 'Ultimania is unavailable or this map is not registered.')
        else:
            await show_window(aseco, player, self.rows)

    async def disconnect(self, _aseco, player):
        self.pending_windows.pop(player.login, None)

    async def finish(self, aseco, finish):
        if not self.enabled or not self.values['submit_records'] or not stunts(aseco):
            return
        player, challenge = getattr(finish, 'player', None), getattr(finish, 'challenge', None)
        if not player or not challenge or challenge.uid != current_uid(aseco):
            return
        raw = getattr(finish, 'score', 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 < raw <= 2147483647:
            return
        uid, login, score = str(challenge.uid), str(player.login), raw
        best = max([row['score'] for row in self.rows if row['login'] == login] + [self.queued.get((uid, login), 0)])
        if score <= best:
            return
        data = {'uid': uid, 'name': str(challenge.name), 'login': login, 'nickname': str(player.nickname),
                'score': score, 'api_base': self.values['api_base'], 'timeout': self.values['request_timeout'],
                'register_maps': self.values['register_maps'], 'replay': ''}
        if self.values['upload_replays']:
            try:
                filename = uuid4().hex + '.Replay.Gbx'
                path = replay_path(aseco, filename)
                await file_io(admit_replay, path)
                saved = await aseco.client.query('SaveBestGhostsReplay', login, 'PyXasecoUltimania/' + filename)
                if saved is True or saved == 1 or saved == '1':
                    data['replay'] = filename
                else:
                    logger.warning('[Ultimania] Replay capture not acknowledged; submitting score only.')
            except Exception as error:
                logger.warning('[Ultimania] Replay unavailable; submitting score only: %s', error)
        await self.dispatcher(aseco).retain(data, map_uid=uid)
        self.queued[(uid, login)] = score
        while len(self.queued) > 4096:
            self.queued.popitem(last=False)

    def dispatcher(self, aseco):
        async def prepare(data):
            client = Client(aseco, data['api_base'], data['timeout'])
            try:
                remote_rows = await client.get_records(data['uid'])
            except MapNotFound:
                if not data['register_maps']:
                    raise PreparationRejected('Captured map is not registered on Ultimania.')
                return data, [], True
            except Exception as error:
                self.delivery_retry_after = monotonic() + 60
                logger.warning('[Ultimania] Submission lookup deferred; no write attempted: %s', error)
                raise PreparationDeferred('Ultimania lookup unavailable.') from error
            return data, remote_rows, False

        async def send(prepared):
            data, remote_rows, register = prepared
            client = Client(aseco, data['api_base'], data['timeout'])
            if register:
                await client.register_map(data['uid'], data['name'])
            previous = next((row for row in remote_rows if row['login'] == data['login']), None)
            if previous is not None and previous['score'] >= data['score']:
                return {'saved': previous, 'rows': remote_rows, 'submitted': False, 'replay_uploaded': False}
            saved = await client.submit(data)
            replay_uploaded = False
            if data['replay'] and saved['score'] == data['score']:
                try:
                    path = replay_path(aseco, data['replay'])
                    content = None
                    for _ in range(20):
                        try:
                            size = await file_io(lambda: path.stat().st_size)
                            await asyncio.sleep(.25)
                            if size > 0 and size == await file_io(lambda: path.stat().st_size):
                                content = await file_io(read_replay, path)
                                break
                        except FileNotFoundError:
                            await asyncio.sleep(.25)
                    if content is None:
                        raise FileNotFoundError('Saved replay did not become available.')
                    await client.replay(saved['id'], content)
                    replay_uploaded = True
                except Exception as error:
                    logger.warning('[Ultimania] Score confirmed, replay retained without retry: %s', error)
            return {'saved': saved, 'rows': records(remote_rows + [saved], data['uid']),
                    'submitted': True, 'replay_uploaded': replay_uploaded}

        async def apply(data, result, current):
            if result['replay_uploaded']:
                try:
                    await file_io(replay_path(aseco, data['replay']).unlink)
                except OSError:
                    logger.warning('[Ultimania] Replay uploaded but local cleanup failed.')
            if not current or not self.enabled or not display_stunts(aseco) or data['api_base'] != self.values['api_base']:
                return
            saved = result['saved']
            old = next((row['score'] for row in self.rows if row['login'] == saved['login']), 0)
            self.rows = records(self.rows + result['rows'], data['uid'])
            self.uid, self.available = data['uid'], True
            self.records_revision += 1
            await self.notify(aseco)
            if self.values['show_record_messages'] and result['submitted'] and saved['score'] > old:
                row = next(row for row in self.rows if row['login'] == saved['login'])
                message = aseco.format_colors(f'{{#server}}> {{#highlite}}{data["nickname"]}$z$s{{#record}} '
                    f'claimed Ultimania rank {row["rank"]}: {{#highlite}}{row["score"]} points.')
                if row['rank'] <= self.values['public_rank_limit']:
                    await aseco.client.query_ignore_result('ChatSendServerMessage', message)
                elif aseco.server.players.get_player(data['login']) is not None:
                    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', message, data['login'])

        return delivery(aseco, 'ultimania_records', send, apply, prepare=prepare,
                        ready=lambda: self.enabled and self.values['submit_records'] and monotonic() >= self.delivery_retry_after)


RUNTIME = Runtime()


def is_enabled():
    return RUNTIME.enabled
