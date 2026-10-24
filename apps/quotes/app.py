"""On-demand quotes, with Admin/MasterAdmin-managed TOML storage."""

import asyncio
import logging
import random
import re
import tomllib
from time import monotonic

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_int, bind_app_settings,
    clear_app_defaults_cache, get_app_defaults_path,
)
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.helpers import _send_multipage
from pyxaseco.management.config_store import (
    ManagementError, edit_toml, remove_toml_value, update_file,
)


logger = logging.getLogger(__name__)
USAGE = '/quote [<id>|help|list|add <text>|mod <id> <new_text>|rem <id>|del <id>]'
SCHEMA = AppSettingsSchema(app_id='quotes', settings=(
    AppSetting('enabled', True, as_bool, 'Enable on-demand quotes.'),
    AppSetting('cooldown_seconds', 5, as_int, 'Seconds between public quotes per player.'),
))
APP_METADATA = {
    'id': 'quotes', 'display_name': 'Quotes',
    'description': 'On-demand quotes curated by Admins and MasterAdmins.',
    'modules': ['apps/quotes/app.py'], 'entries': ['app/quotes'],
    'provides': ['feature/quotes'], 'depends_on': ['platform_core'],
}


def _number(key):
    match = re.fullmatch(r'message_([0-9]{1,10})', key)
    return int(match[1]) if match else None


def _identifier(value):
    if not re.fullmatch(r'[0-9]{1,10}', value) or not 1 <= int(value) <= 2147483647:
        raise ManagementError('Use a positive quote ID from /quote list')
    return int(value)


def _messages(data):
    section = data.get('quotes', {})
    messages = section.get('messages', {}) if isinstance(section, dict) else None
    if not isinstance(messages, dict):
        raise ManagementError('quotes.messages must be a TOML table')
    result = {}
    for key, text in messages.items():
        number = _number(key)
        if number is None or not 1 <= number <= 2147483647:
            raise ManagementError('Quote row keys must be message_01, message_02, etc.')
        if number in result:
            raise ManagementError('Duplicate quote ID; check the TOML row keys')
        result[number] = (key, text)
    return dict(sorted(result.items()))


def _edit(path, action, identifier, text):
    saved = {}

    def transform(source):
        messages = _messages(tomllib.loads(source))
        number = 1 if action == 'add' else _identifier(identifier)
        if action == 'add':
            while number in messages:
                number += 1
            if number > 2147483647:
                raise ManagementError('No unused quote IDs remain')
            key = f'message_{number:02d}'
        else:
            if number not in messages:
                raise ManagementError('No quote found with that ID')
            key = messages[number][0]
        target = ('quotes', 'messages', key)
        saved['id'] = number
        return (remove_toml_value(source, target) if action == 'rem'
                else edit_toml(source, target, text))

    update_file(path, transform, validator=tomllib.loads)
    return saved['id']


class QuotesApp(App):
    def __init__(self):
        super().__init__(app_id='quotes', display_name='Quotes',
                         description=APP_METADATA['description'], depends_on=('platform_core',),
                         entry_modules=('app/quotes',), settings_schema=SCHEMA)
        self.enabled = False
        self.quotes = {}
        self.cooldown = 5
        self.sent_at = {}
        self.edit_lock = asyncio.Lock()

    def register_runtime(self, aseco):
        aseco.add_chat_command('quote', 'Show server quotes; Admin/MA can manage them',
                               app='quotes', owner='feature/quotes', usage=USAGE, category='chat')
        aseco.register_event('onChat_quote', self.command)
        aseco.register_event('onPlayerDisconnect', self.disconnect)

    def configure(self, aseco):
        bound = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None))
        messages = _messages({'quotes': bound.section})
        self.quotes = {number: text for number, (_key, text) in messages.items()
                       if isinstance(text, str) and text.strip()}
        self.enabled = bound.values['enabled']
        self.cooldown = max(0, bound.values['cooldown_seconds'])

    async def startup(self, context):
        self.configure(context.aseco)

    async def shutdown(self, _context):
        self.enabled = False
        self.quotes = {}
        self.sent_at.clear()

    async def disconnect(self, _aseco, player):
        self.sent_at.pop(player.login, None)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def command(self, aseco, command):
        player = command['author']
        params = str(command.get('params') or '').strip()
        parts = params.split(None, 1)
        action = parts[0].lower() if parts else ''
        admin = aseco.is_master_admin(player) or aseco.is_admin(player)
        if action in ('add', 'mod', 'rem', 'del') and not admin:
            await self.reply(aseco, player, '{#error}Only Admins and MasterAdmins can manage quotes.')
            return
        try:
            if params.lower() == 'help':
                await self.reply(aseco, player, '{#message}/quote: random quote; /quote <id>: specific quote; /quote list: all quotes.')
                if admin:
                    await self.reply(aseco, player, '{#message}' + USAGE)
                return
            if not self.enabled:
                await self.reply(aseco, player, '{#error}Quotes are disabled.')
                return
            if params.lower() == 'list':
                if not self.quotes:
                    await self.reply(aseco, player, '{#message}No quotes configured.')
                    return
                rows = [[str(number), text] for number, text in self.quotes.items()]
                player.msgs = [[1, 'Quotes', [1.3, .12, 1.18], ['Icons64x64_1', 'TrackInfo']]]
                player.msgs.extend([[['ID', 'Quote']] + rows[i:i + 14] for i in range(0, len(rows), 14)])
                await _send_multipage(aseco, player)
                return
            if action in ('add', 'mod', 'rem', 'del'):
                if len(parts) != 2:
                    raise ManagementError(USAGE)
                action = 'rem' if action == 'del' else action
                identifier, text = '', parts[1]
                if action == 'mod':
                    arguments = text.split(None, 1)
                    if len(arguments) != 2:
                        raise ManagementError(USAGE)
                    identifier, text = arguments
                elif action == 'rem':
                    identifier, text = text, ''
                if action != 'rem' and (not text.strip() or any(ch in text for ch in '\r\n\0')):
                    raise ManagementError('Supply a non-empty, single-line quote')
                async with self.edit_lock:
                    path = get_app_defaults_path('quotes', getattr(aseco, '_base_dir', None))
                    number = await file_io(_edit, path, action, identifier, text)
                    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
                    self.configure(aseco)
                await self.reply(aseco, player, f'{{#message}}Quote {number} saved ({action}).')
                return
            if not self.quotes:
                await self.reply(aseco, player, '{#message}No quotes configured.')
                return
            number = _identifier(params) if params else random.choice(tuple(self.quotes))
            if number not in self.quotes:
                raise ManagementError('No quote found with that ID')
            now = monotonic()
            if now - self.sent_at.get(player.login, float('-inf')) < self.cooldown:
                await self.reply(aseco, player, '{#message}Please wait before sending another quote.')
                return
            self.sent_at[player.login] = now
            await aseco.client.query_ignore_result('ChatSendServerMessage',
                aseco.format_colors(f'$39f[QUOTE #{number}] $fff' + self.quotes[number]))
        except (OSError, ValueError, TypeError) as error:
            logger.warning('[Quotes] Command failed: %s', error)
            await self.reply(aseco, player, '{#error}' + str(error))


APP_CLASS = QuotesApp
APP_INSTANCE = QuotesApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    APP_INSTANCE.configure(aseco)
