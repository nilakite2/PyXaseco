"""Curated GPS commands and an optional native HUD bar; independent of TMX."""

import asyncio
import logging
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

import aiomysql

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_float, bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.base import App
from pyxaseco.core.playlist import playlist
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase
from pyxaseco.helpers import _send_multipage
from pyxaseco.management.config_store import ManagementError

from . import storage


logger = logging.getLogger(__name__)
ML_ID = 5834289
USAGE = '/cgps [help|list|add [<map_id>] <link>|mod [<map_id>] <new_link>|rem [<map_id>] [<link>]|del [<map_id>] [<link>]]'
SCHEMA = AppSettingsSchema(app_id='cgps', settings=(
    AppSetting('enabled', True, as_bool, 'Enable curated GPS commands.'),
    AppSetting('widget/enabled', True, as_bool, 'Show the GPS bar widget.'),
    AppSetting('widget/pos_x', 30.1, as_float, 'GPS bar X position.'),
    AppSetting('widget/pos_y', 22.4, as_float, 'GPS bar Y position.'),
    AppSetting('widget/width', 4.6, as_float, 'GPS bar width.'),
    AppSetting('widget/height', 6.5, as_float, 'GPS bar height.'),
))
APP_METADATA = {
    'id': 'cgps', 'display_name': 'Curated GPS',
    'description': 'Administrator-curated map GPS links and a GPS bar widget.',
    'modules': ['apps/cgps/app.py', 'apps/cgps/storage.py'], 'entries': ['app/cgps'],
    'provides': ['feature/cgps'], 'depends_on': ['platform_core'],
}


def validate_link(link):
    try:
        parsed = urlsplit(link)
        valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                 and not parsed.username and not parsed.password)
    except ValueError:
        valid = False
    if (not valid or len(link) > 2048 or
            any(ch.isspace() or ord(ch) < 32 or ch in '$[]<>"' for ch in link)):
        raise ManagementError('Supply a valid http:// or https:// GPS link without spaces or TMF formatting')
    return link


def chat_link(link):
    # TMF requires HTTP; use the same URL for display and new database writes.
    validate_link(link)
    return 'http://' + link.split('://', 1)[1]


class CuratedGpsApp(App):
    def __init__(self):
        super().__init__(app_id='cgps', display_name='Curated GPS',
                         description=APP_METADATA['description'], depends_on=('platform_core',),
                         entry_modules=('app/cgps',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.widget = {}
        self.schema_pool = None
        self.lock = asyncio.Lock()
        self.widget_uid = ''
        self.widget_link = None

    def register_runtime(self, aseco):
        aseco.add_chat_command('cgps', 'Shows the current track curated GPS; Admin/MA can manage links',
                               app='cgps', owner='feature/cgps', usage=USAGE, category='chat')
        for event, callback in (
            ('onChat_cgps', self.command),
            ('onNewChallenge2', self.sync), ('onTracklistChanged', self.sync),
            ('onChallengeListModified', self.sync), ('onPlayerConnect', self.player_connect),
            ('onEndRace', self.draw_all), ('onBeginRound', self.draw_all),
            ('onWidgetVisibilityChanged', self.visibility_changed),
        ):
            aseco.register_event(event, callback)

    def configure(self, aseco):
        bound = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None))
        widget = bound.section.get('widget', {})
        self.widget = widget if isinstance(widget, dict) else {}
        self.values = bound.values
        self.enabled = bound.values['enabled']

    async def pool(self, aseco):
        pool = await localdb_get_pool(aseco)
        if pool is None:
            raise ManagementError('Local database is unavailable; please try again later')
        if pool is not self.schema_pool:
            await storage.ensure_schema(pool)
            self.schema_pool = pool
        return pool

    async def startup(self, context):
        self.configure(context.aseco)
        await self.sync(context.aseco)

    async def shutdown(self, context):
        self.enabled = False
        self.schema_pool = None
        self.widget_uid, self.widget_link = '', None
        await self.draw_all(context.aseco)

    async def sync(self, aseco, _param=None):
        if not self.enabled:
            return
        try:
            async with self.lock:
                tracks = await playlist(aseco).snapshot(refresh=True)
                challenge = getattr(aseco.server, 'challenge', None)
                if challenge and getattr(challenge, 'uid', ''):
                    tracks.append({'UId': challenge.uid, 'Name': challenge.name})
                await storage.sync_tracks(await self.pool(aseco), tracks)
        except (aiomysql.Error, ManagementError) as error:
            logger.warning('[CuratedGPS] Map synchronization failed: %s', error)
        await self.draw_all(aseco)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    async def command(self, aseco, command):
        player = command['author']
        params = str(command.get('params') or '').strip()
        parts = params.split()
        action = parts[0].lower() if parts else ''
        admin = aseco.is_master_admin(player) or aseco.is_admin(player)
        if action in ('add', 'mod', 'rem', 'del') and not admin:
            await self.reply(aseco, player, '{#error}Only Admins and MasterAdmins can manage GPS links.')
            return
        try:
            if params.lower() == 'help':
                await self.reply(aseco, player, '{#message}/cgps: current track GPS; /cgps list: map IDs, names and GPS links.')
                if admin:
                    await self.reply(aseco, player, '{#message}' + USAGE)
                return
            if not self.enabled:
                raise ManagementError('Curated GPS is disabled')
            if params.lower() == 'list':
                await self.sync(aseco)
                rows = await storage.list_tracks(await self.pool(aseco))
                if not rows:
                    await self.reply(aseco, player, '{#message}No maps found.')
                    return
                table = [[str(row['Id']), row['Name'], row['Uid'],
                          f'$l[{chat_link(row["Link"])}]GPS$l' if row['Link'] else 'No GPS'] for row in rows]
                player.msgs = [[1, 'Curated GPS - Local Map IDs', [1.7, .12, .65, .68, .25],
                                ['Icons64x64_1', 'Camera']]]
                player.msgs.extend([[['ID', 'Track', 'UID', 'GPS']] + table[i:i + 14]
                                   for i in range(0, len(table), 14)])
                await _send_multipage(aseco, player)
                return
            if not params:
                uid = getattr(getattr(aseco.server, 'challenge', None), 'uid', '')
                if not uid:
                    raise ManagementError('No current track is available')
                link = await storage.current_link(await self.pool(aseco), uid)
                text = ('{#message}Current track GPS: $l[' + chat_link(link) + ']Watch GPS$l'
                        if link else '{#message}No GPS found for current track!')
                await self.reply(aseco, player, text)
                return
            if action not in ('add', 'mod', 'rem', 'del') or len(parts) > 3:
                raise ManagementError(USAGE)
            action = 'rem' if action == 'del' else action
            current = len(parts) == 1 or (len(parts) == 2 and
                        (action != 'rem' or parts[1].lower().startswith(('http://', 'https://'))))
            if current:
                if action != 'rem' and len(parts) != 2:
                    raise ManagementError(USAGE)
                challenge = getattr(aseco.server, 'challenge', None)
                map_id = getattr(challenge, 'uid', '')
                if not map_id:
                    raise ManagementError('No current track is available')
                track_name = str(getattr(challenge, 'name', '') or '')
                link = chat_link(parts[1]) if len(parts) == 2 else None
            else:
                map_id, track_name = parts[1], None
                if action != 'rem' and len(parts) != 3:
                    raise ManagementError(USAGE)
                link = chat_link(parts[2]) if len(parts) == 3 else None
            async with self.lock:
                pool = await self.pool(aseco)
                if current:
                    number = await storage.save_link(pool, action, map_id, link, track_name=track_name)
                else:
                    number = await storage.save_link(pool, action, map_id, link)
            await self.reply(aseco, player, f'{{#message}}GPS for map {number} saved ({action}).')
            await self.draw_all(aseco)
        except (aiomysql.Error, OSError, ValueError, TypeError) as error:
            logger.warning('[CuratedGPS] Command failed: %s', error)
            await self.reply(aseco, player, '{#error}Could not complete GPS command: ' + str(error))

    async def refresh_widget_link(self, aseco, *, force=False):
        uid = getattr(getattr(aseco.server, 'challenge', None), 'uid', '')
        if not force and self.widget_uid == uid:
            return
        self.widget_uid, self.widget_link = uid, None
        if not uid:
            return
        try:
            link = await storage.current_link(await self.pool(aseco), uid)
            link = chat_link(link) if link else None
        except (aiomysql.Error, OSError, ValueError, TypeError) as error:
            self.widget_uid = ''  # Retry on the next redraw rather than caching an outage.
            logger.warning('[CuratedGPS] Widget link unavailable: %s', error)
            return
        if getattr(getattr(aseco.server, 'challenge', None), 'uid', '') == uid:
            self.widget_link = link

    def widget_xml(self, link=None):
        values, cfg = self.values, self.widget
        width = max(1.0, min(20.0, values['widget/width']))
        height = max(1.0, min(20.0, values['widget/height']))
        def attr(name, default):
            return escape(str(cfg.get(name, default)), {'"': '&quot;'})
        background = (f'bgcolor="{attr("background_color", "")}"' if cfg.get('background_color') else
                      f'style="{attr("background_style", "BgsPlayerCard")}" substyle="{attr("background_substyle", "ProgressBar")}"')
        target = f' url={quoteattr(chat_link(link))}' if link else ''
        caption = 'GPS' if link else 'NO GPS'
        return (f'<manialink id="{ML_ID}"><frame posn="{values["widget/pos_x"]} {values["widget/pos_y"]} 0">'
                f'<format textsize="1"/><quad posn="0 0 0.001" sizen="{width} {height}" {background}/>'
                f'<quad posn="{width * .15} {-height * .05} 0.002" sizen="{width * .7} {height * .5}"'
                f' style="{attr("icon_style", "Icons64x64_1")}" substyle="{attr("icon_substyle", "Camera")}"/>'
                f'<label posn="{width / 2} {-height * .67} 0.003" sizen="{width * .9} {height * .3}"'
                f' halign="center" scale="0.7" textcolor="{attr("text_color", "FC0F")}" text="{caption}"/>'
                f'<quad posn="0 0 0.01" sizen="{width} {height}" bgcolor="0000"{target}/>'
                '</frame></manialink>')

    async def draw_player(self, aseco, player, *, refresh=True):
        from apps.ui.config import _state
        shown = (self.enabled and self.values.get('widget/enabled', False)
                 and not is_score_phase(aseco) and _state.player_visible.get(player.login, True))
        if shown and refresh:
            await self.refresh_widget_link(aseco)
        xml = self.widget_xml(self.widget_link) if shown else f'<manialink id="{ML_ID}"></manialink>'
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def draw_all(self, aseco, _param=None):
        if self.enabled and self.values.get('widget/enabled', False) and not is_score_phase(aseco):
            await self.refresh_widget_link(aseco, force=True)
        for player in aseco.server.players.all():
            await self.draw_player(aseco, player, refresh=False)

    async def player_connect(self, aseco, player):
        await self.draw_player(aseco, player)

    async def visibility_changed(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player:
            await self.draw_player(aseco, player)

APP_CLASS = CuratedGpsApp
APP_INSTANCE = CuratedGpsApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    APP_INSTANCE.configure(aseco)
    if APP_INSTANCE.enabled:
        await APP_INSTANCE.sync(aseco)
    else:
        await APP_INSTANCE.draw_all(aseco)
