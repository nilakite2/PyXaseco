"""Per-player UI style selection; Classic remains the unchanged default renderer."""

import asyncio
import logging
from pathlib import Path
import tomllib

from pyxaseco.app_services import localdb_get_ui_style, localdb_set_ui_style
from pyxaseco.core.file_io import file_io
from pyxaseco.helpers import _send_multipage
from pyxaseco.toml_tools import update_toml_table_scalar
from .uistyle_catalog import Catalog, load_catalog, valid_id
from .presentation import Presentation


logger = logging.getLogger(__name__)
ACTION_BASE = 8540000
MAX_PRESETS = 1000


class UiStyles:
    def __init__(self, aseco):
        self.aseco = aseco
        self.root = Path(getattr(aseco, '_base_dir', None) or aseco.base_dir)
        self.catalog = Catalog()
        self.default = 0
        self.lock = asyncio.Lock()
        self.presentation = Presentation(self)

    def delivery_groups(self, method, *args):
        return self.presentation.groups(method, *args)

    def remember_ui(self, method, *args):
        self.presentation.remember(method, *args)

    async def player_disconnect(self, _aseco, player):
        self.presentation.discard(player.login)

    @property
    def config_path(self):
        return self.root / 'apps/platform_ui/app_defaults.toml'

    async def startup(self, _aseco, _param):
        self.catalog = await file_io(load_catalog, self.root)
        for warning in self.catalog.warnings:
            logger.warning('[UIStyle] %s', warning)
        try:
            def read_default():
                if not self.config_path.exists():
                    return 0
                data = tomllib.loads(self.config_path.read_text(encoding='utf-8-sig'))
                return data.get('platform_ui', {}).get('uistyle', {}).get('default', 0)
            value = await file_io(read_default)
            if not valid_id(value):
                raise ValueError('default must be an integer UI preset ID')
            self.default = value
            if value not in self.catalog.presets:
                logger.warning('[UIStyle] Server default %s is unavailable; using Classic', value)
        except (OSError, ValueError, TypeError, AttributeError):
            self.default = 0
            logger.warning('[UIStyle] Server default could not be read; using Classic', exc_info=True)

    def resolve(self, player):
        return self.catalog.resolve(getattr(player, 'ui_style', None), self.default)

    def window_style(self, player, legacy):
        window = self.resolve(player).window
        return legacy if window is None else window

    def local_records_xml(self, player, **kwargs):
        preset = self.resolve(player)
        if preset.base != 1:
            return None
        from .modern import local_records
        return local_records(palette=preset.palette, **kwargs)

    def record_widget_xml(self, player, **kwargs):
        preset = self.resolve(player)
        if preset.base != 1:
            return None
        from .modern import record_widget
        return record_widget(palette=preset.palette, **kwargs)

    def tracklist_controls_xml(self, player, **kwargs):
        preset = self.resolve(player)
        if preset.base != 1:
            return None
        from .modern import tracklist_controls
        return tracklist_controls(palette=preset.palette, **kwargs)

    def picker_xml(self, player, header, rows, widths, page, total):
        preset = self.resolve(player)
        if preset.base != 1:
            return None
        from .modern import picker_window
        return picker_window(header, rows, widths, page, total, preset.palette)

    def command_window_xml(self, player, header, rows, widths, page=1, total=1, refresh_action=None, icon=None):
        preset = self.resolve(player)
        if preset.base != 1 or preset.window is not None:
            return None
        from .modern import command_window
        return command_window(header, rows, widths, page, total, preset.palette, refresh_action=refresh_action, icon=icon)

    async def reply(self, player, message):
        if not self.connected(player):
            return
        await self.aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            self.aseco.format_colors('{#server}> ' + message), player.login)

    def connected(self, player):
        return self.aseco.server.players.get_player(player.login) is player

    async def player_connect(self, _aseco, player):
        async with self.lock:
            previous = self.resolve(player)
            try:
                selected = await localdb_get_ui_style(self.aseco, player.login)
            except Exception:
                logger.warning('[UIStyle] Could not load preference for %s; using server default this session', player.login, exc_info=True)
                if self.connected(player):
                    player.ui_style, player.ui_style_loaded = None, False
                return
            if not self.connected(player):
                return
            player.ui_style, player.ui_style_loaded = selected, True
        if previous != self.resolve(player):
            # Earlier connect handlers may already have drawn using the default.
            await self.changed(player)

    async def changed(self, player):
        if self.connected(player):
            await self.aseco.release_event('onUiStyleChanged', {
                'login': player.login, 'saved_id': player.ui_style,
                'preset_id': self.resolve(player).id})
            await self.presentation.refresh(player)

    async def select(self, player, identifier):
        if identifier is not None and (not valid_id(identifier) or identifier not in self.catalog.presets):
            await self.reply(player, '{#error}Unknown or unavailable UI preset. Use /uistyle list.')
            return False
        async with self.lock:
            try:
                await localdb_set_ui_style(self.aseco, player.login, identifier)
            except Exception:
                logger.warning('[UIStyle] Could not save preference for %s', player.login, exc_info=True)
                await self.reply(player, '{#error}UI style was not saved; your current selection is unchanged.')
                return False
            if not self.connected(player):
                return False
            player.ui_style, player.ui_style_loaded = identifier, True
        await self.changed(player)
        return True

    async def picker(self, player):
        current = self.resolve(player)
        selected = getattr(player, 'ui_style', None)
        server_name = self.catalog.resolve(None, self.default).name
        choices = [(None, 'Follow server default: ' + server_name)] + [(item.id, item.name)
            for item in sorted(self.catalog.presets.values(), key=lambda item: item.id)[:MAX_PRESETS]]
        player.ui_style_actions = {}
        rows = []
        for index, (identifier, name) in enumerate(choices):
            action = ACTION_BASE + index
            player.ui_style_actions[action] = identifier
            rows.append(['-' if identifier is None else str(identifier),
                         ['{#black}' + name, action], '{#black}Selected' if identifier == selected else ''])
        pages = [[['ID', 'UI Style', 'Preference']] + rows[start:start + 14] for start in range(0, len(rows), 14)]
        player.msgs = [[1, f'UI Styles - Active: {current.name}', [1.25, .12, .8, .33],
                        ['Icons64x64_1', 'Windowed'], None, None, None,
                        self.picker_xml]] + pages
        player.ui_style_picker = player.msgs
        await _send_multipage(self.aseco, player)

    async def command(self, _aseco, command):
        player = command['author']
        parameter = str(command.get('params') or '').strip().lower()
        if parameter == 'list':
            await self.picker(player)
        elif parameter == 'default' or (len(parameter) <= 10 and parameter.isdecimal()):
            identifier = None if parameter == 'default' else int(parameter)
            if await self.select(player, identifier):
                await self.reply(player, '{#message}UI style saved: {#highlite}' + self.resolve(player).name +
                                 ('{#message} (following server default).' if identifier is None else '.'))
        else:
            await self.reply(player, '{#message}/uistyle list: choose a UI preset; /uistyle <id>: save a choice; '
                             '/uistyle default: follow the server default. Active: {#highlite}' + self.resolve(player).name)

    async def answer(self, _aseco, answer):
        if len(answer) < 3:
            return
        try:
            action = int(answer[2])
        except (TypeError, ValueError):
            return
        if not ACTION_BASE <= action <= ACTION_BASE + MAX_PRESETS:
            return
        player = self.aseco.server.players.get_player(answer[1])
        if player is None or getattr(player, 'ui_style_picker', None) is not player.msgs:
            return
        actions = getattr(player, 'ui_style_actions', {})
        if action in actions and await self.select(player, actions[action]):
            await self.picker(player)

    async def admin_command(self, player, arguments):
        if not self.aseco.allow_ability(player, 'uistyle'):
            await self.reply(player, '{#error}You do not have permission to change the server UI default.')
            return
        if (len(arguments) != 2 or arguments[0].lower() != 'default'
                or len(arguments[1]) > 10 or not arguments[1].isdecimal()):
            await self.reply(player, '{#message}Usage: //uistyle default <id>')
            return
        identifier = int(arguments[1])
        if not valid_id(identifier) or identifier not in self.catalog.presets:
            await self.reply(player, '{#error}Unknown or unavailable UI preset. Use /uistyle list.')
            return
        async with self.lock:
            try:
                await file_io(update_toml_table_scalar, self.config_path, ('platform_ui', 'uistyle'), 'default', identifier)
            except Exception:
                logger.warning('[UIStyle] Could not save server default', exc_info=True)
                await self.reply(player, '{#error}Server UI default was not saved; the current default is unchanged.')
                return
            self.default = identifier
        for viewer in list(self.aseco.server.players.all()):
            if getattr(viewer, 'ui_style', None) is None or getattr(viewer, 'ui_style', None) not in self.catalog.presets:
                await self.changed(viewer)
        await self.reply(player, '{#message}Server UI default saved: {#highlite}' + self.catalog.presets[identifier].name)


def register(aseco):
    service = UiStyles(aseco)
    aseco.register_service('ui/uistyle', service, owner='platform_ui')
    aseco.register_event('onStartup', service.startup)
    aseco.register_event('onPlayerConnect', service.player_connect)
    aseco.register_event('onPlayerDisconnect', service.player_disconnect)
    aseco.register_event('onPlayerManialinkPageAnswer', service.answer)
    aseco.add_chat_command('uistyle', 'Selects your UI preset (see: /uistyle list)',
                           app='platform_ui', owner='ui/uistyle', category='chat-ui',
                           usage='/uistyle [list|default|id]')
    aseco.register_event('onChat_uistyle', service.command)
