"""Optional MA-only backup tools; destructive database maintenance is excluded."""

import logging
import secrets
from time import monotonic, time

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_int, as_str, bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.app_services import get_localdb_service
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.helpers import _send_multipage

from . import backup


logger = logging.getLogger(__name__)
ACTION_BASE = 8580000
POLICY = JobPolicy(capacity=1, deadline_seconds=300)
USAGE = '/dbtools backup | listbackups | deletebackup <id> [confirm <code>] | status | help'
SCHEMA = AppSettingsSchema(app_id='dbtools', settings=(
    AppSetting('enabled', True, as_bool, 'Enable optional MA-only SQL backup tools.'),
    AppSetting('directory', 'backups/dbtools', as_str, 'Private backup subfolder inside the controller folder.'),
    AppSetting('compress', True, as_bool, 'Compress SQL backups with gzip.'),
    AppSetting('max_size_mb', 1024, as_int, 'Maximum uncompressed SQL size, 1-16384 MiB.'),
    AppSetting('retention_days', 14, as_int, 'Prune completed backups older than this; 0 disables pruning.'),
    AppSetting('keep_last', 3, as_int, 'Minimum successful backups retained, including the latest.'),
    AppSetting('schedule/enabled', False, as_bool, 'Enable automatic backups.'),
    AppSetting('schedule/interval_hours', 24, as_int, 'Hours between successful scheduled backups.'),
))
APP_METADATA = {
    'id': 'dbtools', 'display_name': 'DBTools',
    'description': 'Optional SQL backups, scheduling, retention and an MA backup browser.',
    'modules': ['apps/dbtools/app.py', 'apps/dbtools/backup.py'],
    'entries': ['app/dbtools'], 'provides': ['feature/dbtools'], 'depends_on': ['platform_core'],
}


class DbToolsApp(App):
    def __init__(self):
        super().__init__(app_id='dbtools', display_name='DBTools', description=APP_METADATA['description'],
                         depends_on=('platform_core',), entry_modules=('app/dbtools',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.next_due = 0
        self.revision = 0
        self.last_status = 'No operation yet'

    def register_runtime(self, aseco):
        aseco.add_chat_command('dbtools', 'Database backup tools (MasterAdmin only)',
                               is_admin=True, role='masteradmin', app='dbtools', owner='feature/dbtools', usage=USAGE)
        for event, callback in (('onChat_dbtools', self.command), ('onEverySecond', self.tick),
                                ('onPlayerManialinkPageAnswer', self.answer), ('onPlayerDisconnect', self.disconnect)):
            aseco.register_event(event, callback)

    def configure(self, aseco):
        values = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None)).values
        if (not 1 <= values['max_size_mb'] <= 16384 or not 0 <= values['retention_days'] <= 36500
                or not 1 <= values['keep_last'] <= 1000 or not 1 <= values['schedule/interval_hours'] <= 8760):
            raise ValueError('Invalid DBTools size, retention, keep_last or schedule interval.')
        backup.directory(aseco._base_dir, values['directory'])
        self.values, self.enabled = values, values['enabled']
        self.next_due = 0
        self.revision += 1

    async def startup(self, context):
        self.configure(context.aseco)

    async def shutdown(self, _context):
        self.enabled = False

    def allowed(self, aseco, player):
        return (aseco.server.players.get_player(player.login) is player and aseco.is_master_admin(player)
                and (not getattr(aseco.settings, 'lock_password', '') or getattr(player, 'unlocked', False)))

    def window_allowed(self, aseco, player):
        window = getattr(player, '_dbtools_window', None)
        return window is not None and window is getattr(player, 'msgs', None) and self.allowed(aseco, player)

    def settings(self, aseco):
        getter = getattr(get_localdb_service(aseco), 'connection_settings', None)
        if not callable(getter):
            raise ValueError('Local database connection settings are unavailable.')
        return dict(getter())

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def request(self, aseco, kind, player=None, *, identifier=None, expected=None, command_id=None):
        service = aseco.jobs.service('dbtools_backups', POLICY)
        if service.outstanding:
            if player:
                await self.reply(aseco, player, '{#message}DBTools is busy; please try again when the current operation completes.')
            return False
        settings, values, revision = self.settings(aseco), dict(self.values), self.revision
        parent = backup.directory(aseco._base_dir, values['directory'])
        source = backup.identity(settings)
        interval = values['schedule/interval_hours'] * 3600
        job = JobEnvelope.capture(aseco.capture_job_context(), {'kind': kind})

        async def operation(_envelope):
            try:
                if kind == 'list':
                    return {'kind': 'list', 'rows': await file_io(backup.scan, parent, source)}
                if kind == 'review':
                    row = await file_io(backup.inspect, parent, identifier, source)
                    return {'kind': 'review', 'row': row}
                if kind == 'delete':
                    await file_io(backup.remove, parent, identifier, source, expected)
                    return {'kind': 'delete', 'id': identifier}
                if kind == 'scheduled':
                    rows = await file_io(backup.scan, parent, source)
                    latest = next((row for row in rows if row['status'] == 'complete'), None)
                    due = latest['timestamp'] + interval if latest else 0
                    if due > time():
                        return {'kind': 'not_due', 'due': due}
                row = await backup.create(settings, parent, values['compress'], values['max_size_mb'])
                retention_error = ''
                try:
                    await file_io(backup.prune, parent, source, values['retention_days'], values['keep_last'], row['id'])
                except Exception as error:
                    retention_error = str(error)
                return {'kind': 'backup', 'row': row, 'retention_error': retention_error}
            except Exception as error:
                return {'kind': 'failed', 'error': str(error)}

        async def apply(result):
            data = result.value if result.status == 'completed' else {'kind': 'failed', 'error': result.failure_label}
            outcome = data['kind']
            if outcome == 'not_due':
                if self.revision == revision:
                    self.next_due = data['due']
                return
            if outcome == 'backup':
                row = data['row']
                self.last_status = 'Backup completed: ' + row['id']
                if row.get('warning'):
                    self.last_status += ' (best-effort live export)'
                    logger.warning('[DBTools] %s: %s', row['id'], row['warning'])
                logger.info('[DBTools] Backup complete: %s (%s tables, %s rows)', row['id'], row['tables'], row['rows'])
                if self.revision == revision:
                    self.next_due = row['timestamp'] + interval
                if data['retention_error']:
                    logger.warning('[DBTools] Backup succeeded, but retention failed: %s', data['retention_error'])
            elif outcome == 'failed':
                self.last_status = 'Last operation failed'
                if kind == 'scheduled' and self.revision == revision:
                    self.next_due = time() + min(interval, 3600)
                logger.warning('[DBTools] Operation incomplete: %s', data['error'])
            if player is None or not self.allowed(aseco, player):
                return
            if outcome == 'list':
                await self.show(aseco, player, data['rows'])
            elif outcome == 'review':
                token, row = secrets.token_hex(4), data['row']
                player._dbtools_pending = {'id': row['id'], 'revision': row['revision'], 'source': source,
                    'parent': str(parent), 'token': token, 'expires': monotonic() + 120}
                await self.reply(aseco, player, f'{{#message}}Delete local backup {row["id"]} ({row["status"]})? '
                    f'This deletes backup files only. Confirm within 120s: {{#highlite}}/dbtools deletebackup {command_id} confirm {token}')
            elif outcome == 'delete':
                await self.reply(aseco, player, '{#message}Backup deleted: ' + data['id'])
                player._dbtools_window = None
            elif outcome == 'backup':
                await self.reply(aseco, player, '{#message}' + self.last_status +
                    ('; tables may reflect different moments during concurrent writes' if data['row'].get('warning') else '') +
                    (' (retention cleanup failed; see controller log)' if data['retention_error'] else ''))
            elif outcome == 'failed':
                await self.reply(aseco, player, '{#error}DBTools could not complete the operation: ' + data['error'])

        admitted = service.submit(job, operation, apply, current_map=False, revision_guard=False)
        if admitted == Admission.ACCEPTED:
            if kind == 'backup' and player:
                await self.reply(aseco, player, '{#message}Backing up table definitions/data in the background; server remains running.')
            return True
        if player:
            await self.reply(aseco, player, '{#message}DBTools is unavailable/busy; operation was not started.')
        return False

    async def tick(self, aseco, _data=None):
        if self.enabled and self.values['schedule/enabled'] and time() >= self.next_due:
            try:
                await self.request(aseco, 'scheduled')
            except Exception as error:
                self.next_due = time() + 3600
                logger.warning('[DBTools] Scheduled backup deferred: %s', error)

    async def command(self, aseco, command):
        player = command['author']
        if not self.allowed(aseco, player):
            await self.reply(aseco, player, '{#error}MasterAdmin access is required; unlock admin access if configured.')
            return
        if not self.enabled:
            await self.reply(aseco, player, '{#message}DBTools is disabled.')
            return
        parts = str(command.get('params') or '').strip().split()
        if parts:
            parts[0] = parts[0].lower()
        try:
            if not parts or parts == ['help']:
                await self.reply(aseco, player, '{#message}' + USAGE)
            elif parts in (['list'], ['listbackups']):
                await self.request(aseco, 'list', player)
            elif parts == ['backup']:
                await self.request(aseco, 'backup', player)
            elif parts == ['status']:
                await self.reply(aseco, player, '{#message}' + self.last_status +
                    ('; automatic backups enabled' if self.values['schedule/enabled'] else '; automatic backups disabled'))
            elif parts[0].lower() == 'deletebackup' and len(parts) in (2, 4):
                number = parts[1]
                identifier = getattr(player, '_dbtools_ids', {}).get(number, number)
                if len(parts) == 2:
                    await self.request(aseco, 'review', player, identifier=identifier, command_id=number)
                else:
                    pending = getattr(player, '_dbtools_pending', None)
                    player._dbtools_pending = None
                    settings = self.settings(aseco)
                    parent = backup.directory(aseco._base_dir, self.values['directory'])
                    if (not pending or parts[2].lower() != 'confirm' or pending['token'] != parts[3]
                            or pending['id'] != identifier or monotonic() > pending['expires']
                            or pending['source'] != backup.identity(settings) or pending['parent'] != str(parent)):
                        raise ValueError('Deletion confirmation is missing, expired or changed; request a new review.')
                    await self.request(aseco, 'delete', player, identifier=identifier, expected=pending['revision'])
            else:
                await self.reply(aseco, player, '{#message}' + USAGE)
        except (OSError, ValueError) as error:
            await self.reply(aseco, player, '{#error}' + str(error))

    async def show(self, aseco, player, rows):
        if not rows:
            await self.reply(aseco, player, '{#message}No app-owned backups found for the configured database.')
            return
        player._dbtools_ids = {str(i + 1): row['id'] for i, row in enumerate(rows)}
        table = [[str(i + 1), row['created_at'][:19].replace('T', ' '),
                  'live*' if row['status'] == 'complete' and row.get('warning') else row['status'],
                  f'{row["bytes"] / 1048576:.2f} MiB', ['Delete...', ACTION_BASE + i]] for i, row in enumerate(rows)]
        player.msgs = [[1, 'DBTools - Private SQL backups (UTC)', [1.8, .12, .7, .35, .3, .33],
                        ['Icons128x128_1', 'Browse'], self.window_allowed]]
        player.msgs.extend([[['ID', 'Created (UTC)', 'Status', 'Size', 'Action']] + table[i:i + 14]
                            for i in range(0, len(table), 14)])
        player._dbtools_window = player.msgs
        await _send_multipage(aseco, player)
        if any(row['status'] == 'complete' and row.get('warning') for row in rows):
            await self.reply(aseco, player, '{#message}live* = completed best-effort live export; '
                             'tables may reflect different moments during concurrent writes.')

    async def answer(self, aseco, data):
        if len(data) < 3:
            return
        try:
            action = int(data[2])
        except (TypeError, ValueError):
            return
        if action != 0 and not ACTION_BASE <= action < ACTION_BASE + 5000:
            return
        player = aseco.server.players.get_player(data[1])
        if player is None:
            return
        if action == 0:
            player._dbtools_window = None
            return
        if self.window_allowed(aseco, player):
            number = str(action - ACTION_BASE + 1)
            if number in player._dbtools_ids:
                await self.command(aseco, {'author': player, 'params': 'deletebackup ' + number})

    async def disconnect(self, _aseco, player):
        player._dbtools_window = None
        player._dbtools_ids = {}
        player._dbtools_pending = None


APP_CLASS = DbToolsApp
APP_INSTANCE = DbToolsApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    APP_INSTANCE.configure(aseco)
