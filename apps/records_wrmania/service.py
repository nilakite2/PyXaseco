"""Background global records with independently controlled display and submissions."""

from collections import OrderedDict
import json
import logging
import os
import re
from time import monotonic
from uuid import uuid4

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, as_int, as_str, bind_app_settings
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.retained_delivery import delivery, PreparationDeferred, PreparationRejected
from pyxaseco.helpers import format_time, strip_colors, is_lan_login

from .api import ApiError, Client, MODES, base_url, map_data, valid_checks


logger = logging.getLogger(__name__)
POLICY = JobPolicy(capacity=1, deadline_seconds=200)
HEARTBEAT_POLICY = JobPolicy(capacity=1, deadline_seconds=160)
SCHEMA = AppSettingsSchema(app_id='records_wrmania', settings=(
    AppSetting('enabled', True, as_bool, 'Enable Mania Records.'),
    AppSetting('api_base', 'https://api.wrmania.net', as_str, 'WRMania HTTPS API origin.'),
    AppSetting('server_login', '', as_str, 'Dedicated-server login; blank uses the connected server.'),
    AppSetting('server_password', '', as_str, 'Dedicated password; prefer WRMANIA_SERVER_PASSWORD in .env.'),
    AppSetting('nation', '', as_str, 'Three-letter dedicated-server nation.'),
    AppSetting('request_timeout', 30, as_int, 'Request deadline, 1-60 seconds.'),
    AppSetting('refresh_interval', 45, as_int, 'Refresh interval, 15-3600 seconds.'),
    AppSetting('heartbeat_interval', 240, as_int, 'Server heartbeat interval, 30-240 seconds; independent of records.'),
    AppSetting('submit_records', True, as_bool, 'Submit validated improvements even while another widget is visible.'),
    AppSetting('widget_enabled', True, as_bool, 'Show Mania Records in the shared external-record slot.'),
    AppSetting('prefer_widget', False, as_bool, 'Prefer Mania Records over Dedimania, never RPG/Trial/Ultimania.'),
    AppSetting('show_record_messages', True, as_bool, 'Announce confirmed new/improved records when chat priority permits.'),
    AppSetting('show_map_messages', True, as_bool, 'Announce the map leaderboard once when chat priority permits.'),
    AppSetting('announce_when_hidden', False, as_bool, 'Allow enabled announcements even while another provider owns the widget.'),
))


def current_uid(aseco):
    return str(getattr(aseco.server.challenge, 'uid', '') or '')


def dedi_available(aseco):
    if 'records_dedimania' not in (getattr(aseco, 'active_apps', ()) or ()):
        return False
    service = aseco.services.get('service/records_dedimania')
    data = getattr(service, 'dedi_db', {})
    track = data.get('Challenge', {})
    uid = track.get('UId') or track.get('Uid') or track.get('UID') or current_uid(aseco)
    return (bool(getattr(service, '_connected', False)) and bool(data.get('RecsValid'))
            and uid == current_uid(aseco))


async def announce(aseco, nickname, score, old_rank, old_score, rank):
    nickname = strip_colors(str(nickname or '?'))
    if old_rank <= 0:
        action, suffix = 'claimed the', ''
    else:
        action = 'gained the' if rank < old_rank else 'secured his/her'
        previous = old_rank if rank < old_rank else rank
        suffix = f'{{#dedirec}} $n({{#rank}}{previous}{{#highlite}} -{format_time(max(0, old_score - score))}{{#dedirec}})'
    message = (f'{{#server}}>> {{#highlite}}{nickname}{{#dedirec}} {action} '
               f'{{#rank}}{rank}{{#dedirec}}. Mania Record!  '
               f'Time: {{#highlite}}{format_time(score)}{suffix}')
    await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))


class Runtime:
    def __init__(self):
        self.enabled, self.available = False, False
        self.values, self.rows = {}, []
        self.uid, self.track, self.mode = '', None, ''
        self.client = None
        self.epoch = 0
        self.next_due = self.next_heartbeat = self.retry_after = 0
        self.reconcile_after = 0
        self.rejected_events = set()
        self.best = OrderedDict()
        self.laps = {}
        self.map_announced = False

    def register(self, aseco):
        aseco.register_service('service/records_wrmania', self, owner='records_wrmania')
        for event, callback in (('onSync', self.sync), ('onNewChallenge', self.sync),
                ('onRestartChallenge', self.sync), ('onEverySecond', self.tick),
                ('onPlayerFinish1', self.finish), ('onCheckpoint', self.checkpoint),
                ('onPlayerDisconnect', self.disconnect)):
            aseco.register_event(event, callback)
        for name in ('wr', 'wrrecs', 'wrhelp'):
            aseco.add_chat_command(name, 'Mania Records: records, pb, next, diff, help',
                                   app='records_wrmania', owner='service/records_wrmania')
            aseco.register_event('onChat_' + name, self.help if name == 'wrhelp' else self.command)

    def configure(self, aseco):
        values = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None)).values
        values['api_base'] = base_url(values['api_base'])
        if (not 15 <= values['refresh_interval'] <= 3600 or not 1 <= values['request_timeout'] <= 60
                or not 30 <= values['heartbeat_interval'] <= 240):
            raise ValueError('Invalid Mania Records refresh/heartbeat interval or timeout.')
        values['server_password'] = os.getenv('WRMANIA_SERVER_PASSWORD') or values['server_password']
        values['nation'] = values['nation'].upper()
        self.values, self.enabled = values, values['enabled']
        self.client = None
        self.available = False
        self.rows = []
        self.epoch += 1
        self.next_due = self.next_heartbeat = self.retry_after = 0
        aseco.jobs.service('wrmania_lookup', POLICY).invalidate()
        aseco.jobs.service('wrmania_heartbeat', HEARTBEAT_POLICY).invalidate()
        self.dispatcher(aseco)

    def active(self, aseco):
        return self.enabled and self.available and self.uid == current_uid(aseco)

    def cached_visible(self, aseco):
        if not self.active(aseco) or not self.values['widget_enabled']:
            return False
        active = getattr(aseco, 'active_apps', ()) or ()
        if any(app in active and getattr(aseco.server, flag, False) for app, flag in (
                ('records_rpg', 'rpg_records_active'), ('records_trial', 'trial_records_active'))):
            return False
        ulti = aseco.services.get('service/records_ultimania') if 'records_ultimania' in active else None
        if ulti is not None and ulti.active(aseco):
            return False
        return self.values['prefer_widget'] or not dedi_available(aseco)

    async def visible(self, aseco):
        if not self.active(aseco) or not self.values['widget_enabled']:
            return False
        from apps.ui.record_views import _is_rpg_track_active, _is_trial_track_active, _is_ultimania_track_active
        if (await _is_rpg_track_active(aseco) or await _is_trial_track_active(aseco)
                or await _is_ultimania_track_active(aseco)):
            return False
        return self.cached_visible(aseco)

    async def notify(self, aseco):
        await aseco.release_event('onWRManiaRecordsLoaded', current_uid(aseco))

    async def announcements_allowed(self, aseco):
        if not self.active(aseco):
            return False
        if self.values['announce_when_hidden']:
            return True
        # Disabling Dedimania deliberately selects Mania chat, independently of
        # the RPG/Trial widget. An outage only enables chat in the fallback slot.
        if 'records_dedimania' not in (getattr(aseco, 'active_apps', ()) or ()):
            return True
        return not dedi_available(aseco) and await self.visible(aseco)

    def checkpoint_records(self, aseco):
        if not self.active(aseco) or self.client is None:
            return []
        return [row for row in self.rows if row['rank'] <= self.client.limit
                and valid_checks(row.get('checkpointsMs'), row['score'])]

    async def sync(self, aseco, _data=None):
        self.epoch += 1
        self.uid = current_uid(aseco)
        mode = getattr(aseco.server.gameinfo, 'mode', -1)
        self.track = map_data(aseco.server.challenge, mode)
        self.mode = MODES.get(mode, '')
        self.rows, self.available, self.map_announced = [], False, False
        self.best.clear()
        self.laps.clear()
        self.next_due = 0
        aseco.jobs.service('wrmania_lookup', POLICY).invalidate()
        await self.notify(aseco)
        await self.tick(aseco)

    async def tick(self, aseco, _data=None):
        if not self.enabled:
            return
        if self.uid != current_uid(aseco):
            await self.sync(aseco)
            return
        if self.client is None:
            actual = str(getattr(aseco.server, 'serverlogin', '') or '')
            login = self.values['server_login'] or actual
            if not actual:
                return
            if login != actual or not self.values['server_password'] or not re.fullmatch('[A-Z]{3}', self.values['nation']):
                if monotonic() >= self.next_due:
                    logger.warning('[Mania Records] Configure the actual dedicated login, password and three-letter nation.')
                    self.next_due = monotonic() + 300
                return
            self.client = Client(aseco, {**self.values, 'server_login': login})
        self.heartbeat_tick(aseco)
        if (self.client.authenticated and self.values['submit_records']
                and monotonic() >= max(self.retry_after, self.reconcile_after)):
            self.reconcile_after = monotonic() + 60
            # The supplied adapter's eventId is an idempotency key: retries keep
            # exactly the captured event/body, including after an ambiguous send.
            for record in await aseco.record_outbox.list('wrmania_records', state='uncertain', limit=32):
                entry = json.loads(record.payload_json)
                if entry['server_id'] != aseco.capture_job_context().server_id:
                    continue
                event = entry['payload']['submission']['eventId']
                await aseco.record_outbox.transition(record.record_id, expected='uncertain',
                    target='failed' if event in self.rejected_events else 'pending')
        if not self.track or monotonic() < max(self.next_due, self.retry_after):
            return
        jobs = aseco.jobs.service('wrmania_lookup', POLICY)
        if jobs.outstanding:
            return
        client, track, mode, epoch = self.client, dict(self.track), self.mode, self.epoch

        async def operation(_job):
            await client.authenticate()
            return await client.get_records(track, mode)

        async def apply(result):
            if client is not self.client or epoch != self.epoch:
                return
            self.next_due = monotonic() + self.values['refresh_interval']
            if result.status == 'completed':
                self.rows, self.available = result.value, True
                if (not self.map_announced and self.values['show_map_messages']
                        and await self.announcements_allowed(aseco)):
                    if self.rows:
                        row = self.rows[0]
                        await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(
                            f'{{#server}}>> {{#dedirec}}Mania Records: {{#highlite}}{format_time(row["score"])}'
                            f'{{#dedirec}} by {{#highlite}}{strip_colors(row["nickname"])}'))
                    self.map_announced = True
            else:
                self.available = False
                logger.warning('[Mania Records] Lookup unavailable (%s); submissions remain retained.', result.failure_label)
            await self.notify(aseco)

        jobs.submit(JobEnvelope.capture(aseco.capture_job_context(), {'uid': self.uid}), operation, apply)

    def heartbeat_tick(self, aseco):
        if monotonic() < self.next_heartbeat:
            return
        jobs = aseco.jobs.service('wrmania_heartbeat', HEARTBEAT_POLICY)
        if jobs.outstanding:
            return
        client = self.client
        self.next_heartbeat = monotonic() + self.values['heartbeat_interval']

        async def operation(_job):
            await client.authenticate()
            name = str(getattr(aseco.server, 'name', '') or '')
            try:
                current = await aseco.client.query('GetServerName')
                if isinstance(current, str) and current:
                    name = current
            except Exception:
                logger.debug('[Mania Records] GetServerName unavailable; using cached dedicated name.')
            await client.heartbeat(current_uid(aseco), len(aseco.server.players.all()), name)

        async def apply(result):
            if client is not self.client:
                return
            if result.status != 'completed':
                self.next_heartbeat = monotonic() + min(60, self.values['heartbeat_interval'])
                logger.warning('[Mania Records] Heartbeat unavailable (%s); retry scheduled.', result.failure_label)

        # A map change or a failed records lookup must not cancel presence updates.
        admission = jobs.submit(JobEnvelope.capture(aseco.capture_job_context(), {}), operation, apply,
                                current_map=False, revision_guard=False)
        if admission in (Admission.FULL, Admission.STOPPED, Admission.COOLDOWN):
            self.next_heartbeat = monotonic() + 10

    async def disconnect(self, _aseco, player):
        self.laps.pop(player.login, None)

    async def finish(self, aseco, finish):
        if getattr(aseco.server.gameinfo, 'mode', -1) == 3:
            return
        player = getattr(finish, 'player', None)
        challenge = getattr(finish, 'challenge', None)
        if not player or not challenge or challenge.uid != current_uid(aseco):
            return
        from apps.platform_core.checkpoints import checkpoints
        cp = checkpoints.get(player.login)
        score = getattr(finish, 'score', 0)
        if cp is not None and cp.curr_fin == score:
            await self.enqueue(aseco, player, score, list(cp.curr_cps))

    async def checkpoint(self, aseco, data):
        if (not self.enabled or not self.track or getattr(aseco.server.gameinfo, 'mode', -1) != 3
                or not isinstance(data, (list, tuple)) or len(data) < 5):
            return
        _, login, absolute, lap, index = data[:5]
        count = self.track['nbCheckpoints']
        if any(type(value) is not int for value in (absolute, lap, index)) or min(absolute, count) <= 0 or index < 0:
            return
        state = self.laps.setdefault(login, {'end': 0, 'index': -1, 'checks': []})
        if index != state['index'] + 1 or len(state['checks']) != index % count:
            state['end'], state['checks'] = None, []
        state['index'] = index
        if state['end'] is None:
            if lap > 0 and lap * count == index + 1:
                state['end'] = absolute
            return
        state['checks'].append(absolute - state['end'])
        if lap > 0 and lap * count == index + 1:
            player = aseco.server.players.get_player(login)
            if player:
                await self.enqueue(aseco, player, absolute - state['end'], list(state['checks']))
            state['end'], state['checks'] = absolute, []

    async def enqueue(self, aseco, player, score, checks):
        if (not self.enabled or not self.values['submit_records'] or not self.track
                or self.uid != current_uid(aseco) or getattr(aseco, 'warmup_phase', False)
                or type(score) is not int or not 6000 <= score <= 2147483647
                or not valid_checks(checks, score) or len(checks) != self.track['nbCheckpoints']):
            return
        login = str(player.login)
        if (not re.fullmatch(r'[^\s\x00-\x1f]{1,100}', login) or is_lan_login(login)
                or login == 'lan' or login.startswith('lan_')
                or login.lower() == str(aseco.server.serverlogin).lower()):
            return
        best = min([row['score'] for row in self.rows if row['login'] == login]
                   + [self.best.get(login, 2147483648)])
        if score >= best:
            return
        submission = {'eventId': uuid4().hex, 'game': 'TMF', 'mode': self.mode,
            'map': dict(self.track), 'player': {'login': login, 'nickname': str(player.nickname)[:120],
                'nation': str(getattr(player, 'nation', '') or '')[:24]},
            'run': {'timeMs': score, 'checkpointsMs': checks,
                    'sourceMode': aseco.server.gameinfo.mode}}
        await self.dispatcher(aseco).retain({'api_base': self.values['api_base'],
            'server_login': self.values['server_login'] or str(aseco.server.serverlogin),
            'submission': submission}, map_uid=self.uid)
        self.best[login] = score
        while len(self.best) > 4096:
            self.best.popitem(last=False)

    def dispatcher(self, aseco):
        async def prepare(data):
            if (not self.enabled or not self.values['submit_records'] or self.client is None
                    or not self.client.authenticated or monotonic() < self.retry_after):
                raise PreparationDeferred('WRMania authentication is not ready.')
            if (data['api_base'] != self.client.base
                    or data['server_login'] != self.client.values['server_login']):
                raise PreparationRejected('Captured WRMania destination/account differs from configuration.')
            return data, self.client

        async def send(prepared):
            data, client = prepared
            try:
                result = await client.submit(data['submission'])
            except ApiError as error:
                if error.status in (400, 403, 409, 413, 422):
                    self.rejected_events.add(data['submission']['eventId'])
                raise
            if result.get('accepted') is not True:
                self.rejected_events.add(data['submission']['eventId'])
                raise ValueError('WRMania did not acknowledge the submission.')
            return result

        async def apply(data, result, current):
            if not current or not self.enabled or self.client is None or data['api_base'] != self.client.base:
                return
            self.next_due = 0
            # A GET started before this acknowledgement must not restore older rows.
            self.epoch += 1
            aseco.jobs.service('wrmania_lookup', POLICY).invalidate()
            run = data['submission']
            rank = result.get('rank')
            if (self.values['show_record_messages'] and result.get('personalBest') is True
                    and result.get('status') == 'verified' and not result.get('duplicate')
                    and result.get('ranked', True) is True and type(rank) is int and 1 <= rank <= self.client.limit
                    and await self.announcements_allowed(aseco)):
                old = next((row for row in self.rows if row['login'] == run['player']['login']), {})
                await announce(aseco, run['player']['nickname'], run['run']['timeMs'],
                               old.get('rank', 0), old.get('score', 0), rank)

        async def failure(_result):
            self.retry_after = monotonic() + 60

        return delivery(aseco, 'wrmania_records', send, apply, prepare=prepare, on_failure=failure,
            ready=lambda: self.enabled and self.values['submit_records'] and self.client is not None
                and self.client.authenticated and monotonic() >= self.retry_after)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def help(self, aseco, command):
        await self.command(aseco, {**command, 'params': 'help'})

    async def command(self, aseco, command):
        player = command['author']
        option = str(command.get('params') or '').strip().lower()
        if option == 'help':
            await self.reply(aseco, player, '/wr [recs|pb|next|diff|help] - Mania Records. /wrrecs opens the leaderboard.')
            return
        if not self.active(aseco):
            await self.reply(aseco, player, 'Mania Records is unavailable, not configured, or this map/mode is unsupported.')
            return
        if option in ('', 'recs'):
            from .records_widget import show_window
            await show_window(aseco, player, self.rows)
            return
        rows = [row for row in self.rows if self.client is not None and row['rank'] <= self.client.limit]
        mine = next((row for row in rows if row['login'] == player.login), None)
        if option not in ('pb', 'next', 'diff'):
            await self.reply(aseco, player, 'Use /wr help for commands.')
        elif mine is None:
            await self.reply(aseco, player, 'No personal best within the API-authorized record places.')
        elif option == 'pb':
            await self.reply(aseco, player, f'Your Mania Record: {mine["rank"]}. {format_time(mine["score"])}')
        else:
            target = (rows[0] if option == 'diff' else
                      next((row for row in reversed(rows) if row['rank'] < mine['rank']), None))
            if target is None:
                await self.reply(aseco, player, 'You hold the first Mania Record!')
            else:
                await self.reply(aseco, player, f'{target["rank"]}. {strip_colors(target["nickname"])}: '
                    f'{format_time(target["score"])} | gap +{format_time(max(0, mine["score"] - target["score"]))}')


RUNTIME = Runtime()


def is_enabled():
    return RUNTIME.enabled
