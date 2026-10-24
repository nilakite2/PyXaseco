"""Port of plugin.seqinfomsg.php: one chat message per interval, in ID order."""

import asyncio
import logging
import re
import tomllib
from collections import Counter
from time import monotonic

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_int, bind_app_settings,
    clear_app_defaults_cache,
    get_app_defaults_path,
)
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.helpers import _send_multipage
from pyxaseco.management.config_store import (
    ManagementError, edit_toml, remove_toml_value, update_file,
)
from pyxaseco.toml_tools import read_toml


logger = logging.getLogger(__name__)
MAX_MESSAGE_ID = 2147483647
USAGE = '/seq list | /seq add <text> | /seq mod <id> <new_text> | /seq rem <id> | /seq del <id>'


def _message_number(key):
    match = re.fullmatch(r'message_([0-9]{1,10})', key)
    return int(match[1]) if match else None


def _ordered_messages(messages):
    def order(item):
        number = _message_number(item[0])
        return (0, number) if number is not None else (1, 0)
    # Stable sorting keeps manually named rows in their relative file order.
    return sorted(messages.items(), key=order)


def _message_key(messages, identifier):
    if identifier in messages:
        return identifier
    if re.fullmatch(r'[0-9]{1,10}', identifier):
        matches = [key for key in messages if _message_number(key) == int(identifier)]
        if len(matches) == 1:
            return matches[0]
    raise ManagementError('Unknown or ambiguous message ID; use /seq list and the exact row key if needed')


def _edit_message(path, action, identifier, message):
    saved = {}
    def transform(text):
        data = tomllib.loads(text)
        section = data.get('seqinfomsg', {})
        messages = section.get('messages', {}) if isinstance(section, dict) else None
        if not isinstance(messages, dict):
            raise ManagementError('seqinfomsg.messages must be a TOML table')
        if action == 'add':
            used_ids = {_message_number(key) for key in messages}
            next_id = 1
            while next_id in used_ids:
                next_id += 1
            if next_id > MAX_MESSAGE_ID:
                raise ManagementError('No unused message IDs remain')
            key = f'message_{next_id:02d}'
            updated = edit_toml(text, ('seqinfomsg', 'messages', key), message)
        else:
            key = _message_key(messages, identifier)
            target = ('seqinfomsg', 'messages', key)
            updated = (remove_toml_value(text, target) if action == 'rem'
                       else edit_toml(text, target, message))
        saved['key'] = key
        return updated
    update_file(path, transform, validator=tomllib.loads)
    return saved['key']


def _interval(value, default=30):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    seconds = as_int(value, default)
    return seconds if seconds > 0 else default


SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='seqinfomsg',
    description='Sequential server information messages',
    settings=(
        AppSetting('enabled', True, as_bool, 'Enable periodic chat messages.'),
        AppSetting('interval_seconds', 30, _interval, 'Seconds between messages; must be positive.'),
    ),
)

APP_METADATA = {
    'id': 'seqinfomsg',
    'display_name': 'Sequential Info Messages',
    'description': 'Broadcasts configured chat messages in order at a fixed interval.',
    'modules': ['apps/seqinfomsg/app.py'],
    'entries': ['app/seqinfomsg'],
    'provides': ['feature/seqinfomsg'],
    'depends_on': ['platform_core'],
}


class SequentialInfoMessagesApp(App):
    def __init__(self):
        super().__init__(
            app_id='seqinfomsg', display_name='Sequential Info Messages',
            description=APP_METADATA['description'], depends_on=('platform_core',),
            entry_modules=('app/seqinfomsg',), settings_schema=SETTINGS_SCHEMA,
        )
        self.enabled = False
        self.interval_seconds = 30
        self.messages = ()
        self.index = 0
        self.next_at = None
        self.edit_lock = asyncio.Lock()

    def register_runtime(self, aseco):
        aseco.register_event('onEverySecond', self.tick)
        aseco.add_chat_command(
            'seq', 'Manage sequential info messages (Admin/MasterAdmin only)',
            is_admin=True, app='seqinfomsg', owner='feature/seqinfomsg',
            category='chat-admin', usage=USAGE, role='admin',
        )
        aseco.register_event('onChat_seq', self.command)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def command(self, aseco, command):
        player = command['author']
        if not (aseco.is_master_admin(player) or aseco.is_admin(player)):
            await self.reply(aseco, player, '{#error}This command is restricted to Admins and MasterAdmins.')
            return
        params = str(command.get('params') or '').strip()
        path = get_app_defaults_path('seqinfomsg', getattr(aseco, '_base_dir', None))
        try:
            if params.lower() == 'list':
                data = await file_io(read_toml, path)
                section = data.get('seqinfomsg', {})
                messages = section.get('messages', {}) if isinstance(section, dict) else None
                if not isinstance(messages, dict):
                    raise ManagementError('seqinfomsg.messages must be a TOML table')
                if not messages:
                    await self.reply(aseco, player, '{#message}No sequential messages configured.')
                    return
                rows = []
                numbers = Counter(_message_number(key) for key in messages)
                for key, value in _ordered_messages(messages):
                    number = _message_number(key)
                    unique = number is not None and numbers[number] == 1
                    label = str(number) if unique else key
                    text = value if isinstance(value, str) and value.strip() else '(empty/invalid - skipped)'
                    rows.append([label, key, text])
                player.msgs = [[1, 'Sequential Info Messages', [1.3, .1, .3, .9],
                                ['Icons64x64_1', 'TrackInfo']]]
                player.msgs.extend([[['ID', 'Row Key', 'Message']] + rows[start:start + 14]
                                   for start in range(0, len(rows), 14)])
                await _send_multipage(aseco, player)
                return
            parts = params.split(None, 1)
            if len(parts) != 2 or parts[0].lower() not in ('add', 'mod', 'rem', 'del'):
                await self.reply(aseco, player, '{#message}' + USAGE)
                return
            action, payload = parts[0].lower(), parts[1]
            if action == 'del':
                action = 'rem'
            identifier, message = '', payload
            if action == 'mod':
                arguments = payload.split(None, 1)
                if len(arguments) != 2:
                    await self.reply(aseco, player, '{#message}' + USAGE)
                    return
                identifier, message = arguments
            elif action == 'rem':
                if len(payload.split()) != 1:
                    await self.reply(aseco, player, '{#message}' + USAGE)
                    return
                identifier, message = payload, ''
            if action != 'rem' and (not message.strip() or any(char in message for char in '\r\n\0')):
                raise ManagementError('Supply a non-empty, single-line message')
            async with self.edit_lock:
                key = await file_io(_edit_message, path, action, identifier, message)
                clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
                self.configure(aseco)
            await self.reply(aseco, player, f'{{#message}}Message {key} saved ({action}); configuration applied.')
        except (OSError, ValueError, TypeError) as error:
            logger.warning('[SeqInfoMsg] Message command failed: %s', error)
            await self.reply(aseco, player, '{#error}Could not apply message command: ' + str(error))

    def configure(self, aseco):
        bound = bind_app_settings(SETTINGS_SCHEMA, getattr(aseco, '_base_dir', None))
        messages = bound.section.get('messages', {})
        if not isinstance(messages, dict):
            logger.warning('[SeqInfoMsg] messages must be a table of message text rows')
            messages = {}
        self.enabled = bound.values['enabled']
        self.interval_seconds = bound.values['interval_seconds']
        self.messages = tuple(value for _key, value in _ordered_messages(messages)
                              if isinstance(value, str) and value.strip())
        self.index, self.next_at = 0, None
        if self.enabled and not self.messages:
            logger.warning('[SeqInfoMsg] No non-empty messages configured; broadcasting is paused')

    async def startup(self, context):
        self.configure(context.aseco)

    async def shutdown(self, _context):
        self.enabled = False
        self.messages = ()
        self.index, self.next_at = 0, None

    async def tick(self, aseco, _param=None):
        if not self.enabled or not self.messages:
            return
        now = monotonic()
        if self.next_at is not None and now < self.next_at:
            return
        # No catch-up burst after a delayed tick; failed sends also wait an interval.
        self.next_at = now + self.interval_seconds
        messages, index = self.messages, self.index
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(messages[index]))
        # A reload/shutdown can replace the sequence while the send is awaiting I/O.
        if self.messages is messages:
            self.index = (index + 1) % len(messages)


APP_CLASS = SequentialInfoMessagesApp
APP_INSTANCE = SequentialInfoMessagesApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    APP_INSTANCE.configure(aseco)
