"""Server-wide ForceMods, ported from schmidi's plugin (2013)."""

import asyncio
from dataclasses import replace
import logging
import random

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_str, bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.core.base import App
from pyxaseco.app_services import localdb_get_pool
from pyxaseco.core.playlist import playlist
from pyxaseco.core.widget_delivery import is_score_phase
from pyxaseco.helpers import _send_multipage

from .mods import ENVIRONMENTS, MODES, MAX_MODS, environment, mode, mod_url, native_settings, parse_mods, signature
from . import storage


logger = logging.getLogger(__name__)
ACTION_BASE = 8560000
USAGE = '/fmods [help|list|off|sequential|random|override on|override off|reload|<environment>]'
TRACK_USAGE = '/fmods add [<id>] <url> | mod [<id>] <url> | rem [<id>] [<url>] | del [<id>] [<url>]'
SCHEMA = AppSettingsSchema(app_id='forcemods', settings=(
    AppSetting('enabled', True, as_bool, 'Enable the ForceMods app.'),
    AppSetting('mode', 'sequential', as_str, 'Server-wide forcing: off, sequential or random.'),
    AppSetting('override', False, as_bool, 'Override mods embedded in maps.'),
))
APP_METADATA = {
    'id': 'forcemods', 'display_name': 'ForceMods',
    'description': 'Server-wide environment mod rotation with MasterAdmin controls.',
    'modules': ['apps/forcemods/app.py', 'apps/forcemods/mods.py', 'apps/forcemods/storage.py'],
    'entries': ['app/forcemods'], 'provides': ['feature/forcemods'], 'depends_on': ['platform_core'],
}


class ForceModsApp(App):
    def __init__(self):
        super().__init__(app_id='forcemods', display_name='ForceMods',
                         description=APP_METADATA['description'], depends_on=('platform_core',),
                         entry_modules=('app/forcemods',), settings_schema=SCHEMA)
        self.enabled, self.mode, self.override = False, 'off', False
        self.mods = {}
        self.selected = {}
        self.baseline = None
        self.queued = None
        self.revision = 0
        self.lock = asyncio.Lock()
        self.schema_pool = None

    def register_runtime(self, aseco):
        aseco.add_chat_command('fmods', 'Server-wide mod settings (MasterAdmin only)',
                               is_admin=True, role='masteradmin', app='forcemods',
                               owner='feature/forcemods', usage=USAGE, category='admin')
        for event, callback in (
            ('onChat_fmods', self.command), ('onSync', self.sync),
            ('onEndRace', self.end_race), ('onPlayerManialinkPageAnswer', self.answer),
            ('onPlayerDisconnect', self.disconnect),
            ('onNewChallenge2', self.sync_tracks), ('onTracklistChanged', self.sync_tracks),
            ('onChallengeListModified', self.sync_tracks),
        ):
            aseco.register_event(event, callback)

    def configure(self, aseco):
        bound = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None))
        configured_mode, mods = mode(bound.values['mode']), parse_mods(bound.section)
        self.enabled, self.mode, self.override = bound.values['enabled'], configured_mode, bound.values['override']
        self.mods = mods

    async def startup(self, context):
        self.configure(context.aseco)

    async def shutdown(self, context):
        async with self.lock:
            await self.restore(context.aseco)
            self.enabled = False

    def allowed(self, aseco, player):
        return (aseco.server.players.get_player(player.login) is player and aseco.is_master_admin(player)
                and (not getattr(aseco.settings, 'lock_password', '') or getattr(player, 'unlocked', False)))

    def window_allowed(self, aseco, player):
        window = getattr(player, '_fmods_window', None)
        return window is not None and window is getattr(player, 'msgs', None) and self.allowed(aseco, player)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + text), player.login)

    def choose(self, env, advance):
        choices = [mod for mod in self.mods.values() if mod.enabled and env in mod.environments]
        if not choices:
            return None
        previous = self.selected.get(env)
        current = next((i for i, mod in enumerate(choices) if mod.key == previous), -1)
        if current >= 0 and not advance:
            return choices[current]
        if self.mode == 'random':
            return random.choice([mod for mod in choices if mod.key != previous] or choices)
        return choices[(current + 1) % len(choices)]

    async def target_info(self, aseco, *, next_map):
        info = await aseco.client.query('GetNextChallengeInfo' if next_map else 'GetCurrentChallengeInfo')
        if not isinstance(info, dict):
            raise ValueError('Dedicated server did not return challenge information.')
        return info

    async def write_payload(self, aseco, payload):
        baseline = self.baseline
        if baseline is None:
            baseline = native_settings(await aseco.client.query('GetForcedMods'))
        if await aseco.client.query('SetForcedMods', *payload) is not True:
            raise ValueError('SetForcedMods was not acknowledged; queued settings are unconfirmed.')
        self.baseline, self.queued = baseline, payload

    async def queue(self, aseco, *, info=None, advance=False):
        if not self.enabled:
            await self.restore(aseco)
            return
        if self.mode == 'off':
            await self.write_payload(aseco, (False, []))
            return
        if info is None:
            info = await self.target_info(aseco, next_map=is_score_phase(aseco))
        env = environment(info.get('Environnement', ''))
        uid = str(info.get('UId') or info.get('Uid') or '')
        if not uid:
            raise ValueError('Target track UID is unavailable; cannot check per-track assignments.')
        link = await storage.current_link(await self.pool(aseco), uid)
        if link:
            await self.write_payload(aseco, (True, [{'Env': env, 'Url': mod_url(link)}]))
            logger.info('[ForceMods] Queued track-specific mod for %s (%s)', uid, env)
            return
        selected = self.choose(env, advance) if self.mode != 'off' else None
        payload = (self.override, [{'Env': env, 'Url': selected.url}]) if selected else (False, [])
        await self.write_payload(aseco, payload)
        if selected:
            self.selected[env] = selected.key
            logger.info('[ForceMods] Queued %s: %s for the next map load/restart', env, selected.name)
        else:
            logger.info('[ForceMods] Queued no server-forced mod; map-embedded mods remain allowed')

    async def restore(self, aseco):
        if self.queued is not None:
            current = native_settings(await aseco.client.query('GetForcedMods'))
            if signature(current) != signature(self.queued):
                logger.warning('[ForceMods] Forced mods changed externally; leaving those settings untouched')
            elif await aseco.client.query('SetForcedMods', *self.baseline) is not True:
                raise ValueError('Could not restore the previous forced-mod settings.')
            self.queued = None
        self.baseline = None

    async def sync(self, aseco, _data=None):
        await self.sync_tracks(aseco)
        async with self.lock:
            try:
                info = await self.target_info(aseco, next_map=False) if self.enabled and self.mode != 'off' else None
                await self.queue(aseco, info=info)
            except Exception as error:
                logger.warning('[ForceMods] Could not queue startup settings: %s', error)

    async def end_race(self, aseco, data):
        if not self.enabled or self.mode == 'off':
            return
        async with self.lock:
            try:
                restarting = bool(data and len(data) > 4 and data[4] == 1)
                info = data[1] if restarting else await self.target_info(aseco, next_map=True)
                await self.queue(aseco, info=info, advance=True)
            except Exception as error:
                logger.warning('[ForceMods] Could not queue next-map settings: %s', error)
                if self.queued is not None:
                    try:
                        await self.write_payload(aseco, (False, []))
                        logger.warning('[ForceMods] Cleared stale forcing for the next map after lookup failure')
                    except Exception as clear_error:
                        logger.warning('[ForceMods] Could not clear stale forcing: %s', clear_error)

    async def change(self, aseco, player, action, value=None, *, expected_revision=None):
        async with self.lock:
            if not self.allowed(aseco, player):
                raise ValueError('MasterAdmin access is required; unlock admin access if configured.')
            if expected_revision is not None and (expected_revision != self.revision or not self.window_allowed(aseco, player)):
                raise ValueError('Settings/window changed; reopen /fmods and select again.')
            previous = self.enabled, self.mode, self.override, self.mods
            try:
                if action == 'reload':
                    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
                    self.configure(aseco)
                elif action == 'mode':
                    self.mode = mode(value)
                elif action == 'override':
                    self.override = bool(value)
                elif action == 'mod':
                    mod = self.mods[value]
                    if not mod.enabled:
                        mod_url(mod.url)
                    self.mods = {**self.mods, value: replace(mod, enabled=not mod.enabled)}
                else:
                    raise ValueError('Unknown ForceMods action.')
                await self.queue(aseco)
            except Exception:
                self.enabled, self.mode, self.override, self.mods = previous
                raise
            self.revision += 1
        logger.info('[ForceMods] %s changed %s (%s)', player.login, action, value)

    async def reload_settings(self, aseco):
        async with self.lock:
            previous = self.enabled, self.mode, self.override, self.mods
            try:
                self.configure(aseco)
                await self.queue(aseco)
            except Exception:
                self.enabled, self.mode, self.override, self.mods = previous
                raise
            self.revision += 1

    async def show(self, aseco, player, env=None):
        if not self.allowed(aseco, player):
            return
        actions = {}
        def cell(label, action, value=None):
            identifier = ACTION_BASE + len(actions)
            actions[identifier] = (action, value)
            return [label, identifier]
        if env is None:
            rows = [['Mode'] + [cell(('$0f0' if self.mode == value else '') + value.title(), 'mode', value) for value in MODES],
                    ['Override map mods', cell('On', 'override', True), cell('Off', 'override', False), 'On' if self.override else 'Off'],
                    ['Saved settings', cell('Reload', 'reload'), 'App enabled' if self.enabled else 'App disabled', ''],
                    ['Changes apply at the next map load/restart', '', '', '']]
            for name in ENVIRONMENTS:
                mods = [mod for mod in self.mods.values() if name in mod.environments]
                rows.append([name, cell('Mod list', 'env', name), f'{sum(mod.enabled for mod in mods)}/{len(mods)} enabled', ''])
            title, widths = 'ForceMods - Server-wide settings', [1.4, .53, .29, .29, .29]
        else:
            env = environment(env)
            rows = [[cell('Back to settings', 'settings'), '', '']]
            for mod in self.mods.values():
                if env in mod.environments:
                    rows.append([mod.name, cell('$0f0On' if mod.enabled else '$f00Off', 'mod', mod.key),
                                 'Last queued' if self.selected.get(env) == mod.key else ''])
            if len(rows) == 1:
                rows.append(['No mods configured for this environment.', '', ''])
            title, widths = 'ForceMods - ' + env, [1.4, .95, .2, .25]
        headings = ['Setting', 'Choice', 'Choice / status', 'Choice'] if env is None else ['Mod', 'Enabled', 'Rotation']
        pages = [[headings] + rows[i:i + 14] for i in range(0, len(rows), 14)]
        player.msgs = [[1, title, widths, ['Icons128x128_1', 'Options'], self.window_allowed]] + pages
        player._fmods_window, player._fmods_actions = player.msgs, actions
        player._fmods_revision, player._fmods_environment = self.revision, env
        await _send_multipage(aseco, player)

    async def command(self, aseco, command):
        player = command['author']
        if not self.allowed(aseco, player):
            await self.reply(aseco, player, '{#error}MasterAdmin access is required; unlock admin access if configured.')
            return
        text = str(command.get('params') or '').strip()
        lowered, parts = text.lower(), text.split()
        try:
            if not text:
                await self.show(aseco, player)
                return
            if lowered == 'list':
                await self.track_list(aseco, player)
                return
            if parts[0].lower() in ('add', 'mod', 'rem', 'del'):
                await self.track_command(aseco, player, parts)
                return
            if lowered == 'help':
                await self.reply(aseco, player, '{#message}' + USAGE + ' Changes are server-wide and apply at the next map load/restart.')
                await self.reply(aseco, player, '{#message}' + TRACK_USAGE)
                return
            if lowered == 'reload':
                await self.change(aseco, player, 'reload')
            elif lowered in ('override on', 'override off'):
                await self.change(aseco, player, 'override', lowered.endswith(' on'))
            elif lowered in (*MODES, 'disabled', 'seq', '0', '1', '2'):
                await self.change(aseco, player, 'mode', lowered)
            else:
                await self.show(aseco, player, environment(text))
                return
            await self.reply(aseco, player, '{#message}ForceMods settings queued for the next map load/restart. '
                             'Runtime changes last until reload/restart; use //apps config forcemods for saved settings.')
        except Exception as error:
            logger.warning('[ForceMods] Command failed: %s', error)
            await self.reply(aseco, player, '{#error}Could not update ForceMods: ' + str(error))

    async def answer(self, aseco, data):
        if len(data) < 3:
            return
        try:
            identifier = int(data[2])
        except (TypeError, ValueError):
            return
        if identifier != 0 and not ACTION_BASE <= identifier < ACTION_BASE + MAX_MODS + 20:
            return
        player = aseco.server.players.get_player(data[1])
        if player is None:
            return
        if identifier == 0:
            self.clear_window(player)
            return
        if not self.window_allowed(aseco, player):
            return
        action = getattr(player, '_fmods_actions', {}).get(identifier)
        if action is None:
            return
        env = player._fmods_environment
        if player._fmods_revision != self.revision:
            await self.reply(aseco, player, '{#message}Settings changed; the window has been refreshed. Please select again.')
            await self.show(aseco, player, env)
            return
        name, value = action
        if name in ('settings', 'env'):
            await self.show(aseco, player, value)
            return
        try:
            await self.change(aseco, player, name, value, expected_revision=player._fmods_revision)
            await self.reply(aseco, player, '{#message}ForceMods settings queued for the next map load/restart.')
        except Exception as error:
            await self.reply(aseco, player, '{#error}Could not update ForceMods: ' + str(error))
        if self.window_allowed(aseco, player):
            await self.show(aseco, player, env)

    def clear_window(self, player):
        player._fmods_window = None
        player._fmods_actions = {}

    async def disconnect(self, _aseco, player):
        self.clear_window(player)

    async def pool(self, aseco):
        pool = await localdb_get_pool(aseco)
        if pool is None:
            raise ValueError('Local database is unavailable; track mod assignments could not be checked.')
        if pool is not self.schema_pool:
            await storage.ensure_schema(pool)
            self.schema_pool = pool
        return pool

    async def catalog(self, aseco):
        tracks = await playlist(aseco).snapshot(refresh=True)
        current = getattr(aseco.server, 'challenge', None)
        if current and getattr(current, 'uid', ''):
            tracks.append({'UId': current.uid, 'Name': current.name,
                           'Environnement': getattr(current, 'environment', '')})
        await storage.sync_tracks(await self.pool(aseco), tracks)
        return list(dict.fromkeys(str(track.get('UId') or track.get('Uid')) for track in tracks
                                  if track.get('UId') or track.get('Uid')))

    async def sync_tracks(self, aseco, _data=None):
        if self.enabled:
            try:
                async with self.lock:
                    await self.catalog(aseco)
            except Exception as error:
                logger.warning('[ForceMods] Could not synchronize server maps: %s', error)

    async def track_list(self, aseco, player):
        async with self.lock:
            uids = await self.catalog(aseco)
            rows = await storage.list_tracks(await self.pool(aseco), uids)
        if not self.allowed(aseco, player):
            return
        if not rows:
            await self.reply(aseco, player, '{#message}No server maps found.')
            return
        table = []
        for row in rows:
            if not self.enabled or self.mode == 'off':
                policy = 'Off (assignment saved)' if row['Link'] else 'Off / map default'
            elif row['Link']:
                policy = '$l[' + mod_url(row['Link']) + ']Track mod$l'
            else:
                try:
                    env = environment(row['Environment'])
                    count = sum(mod.enabled and env in mod.environments for mod in self.mods.values())
                    policy = f'Rotation: {count} mod(s)' if count else 'Map default'
                    if count and not self.override:
                        policy += ' (map mod wins)'
                except ValueError:
                    policy = 'Map default / environment unknown'
            table.append([str(row['Id']), row['Name'], row['Environment'], policy])
        player.msgs = [[1, 'ForceMods - Server maps / assigned mods', [1.8, .12, .83, .25, .6],
                        ['Icons128x128_1', 'Options'], self.window_allowed]]
        player.msgs.extend([[['ID', 'Track', 'Environment', 'Assigned mod / policy']] + table[i:i + 14]
                            for i in range(0, len(table), 14)])
        player._fmods_window, player._fmods_actions = player.msgs, {}
        await _send_multipage(aseco, player)

    async def track_command(self, aseco, player, parts):
        action = parts[0].lower()
        action = 'rem' if action == 'del' else action
        if len(parts) > 3 or (action != 'rem' and len(parts) < 2):
            raise ValueError(TRACK_USAGE)
        current = len(parts) == 1 or (len(parts) == 2 and
                    (action != 'rem' or parts[1].lower().startswith(('http://', 'https://'))))
        if current:
            if action != 'rem' and len(parts) != 2:
                raise ValueError(TRACK_USAGE)
            track = getattr(aseco.server, 'challenge', None)
            map_id = getattr(track, 'uid', '')
            if not map_id:
                raise ValueError('No current track is available.')
            info = {'Name': track.name, 'Environnement': getattr(track, 'environment', '')}
            link = mod_url(parts[1]) if len(parts) == 2 else None
        else:
            if action != 'rem' and len(parts) != 3:
                raise ValueError(TRACK_USAGE)
            map_id, info = parts[1], None
            link = mod_url(parts[2]) if len(parts) == 3 else None
        async with self.lock:
            pool = await self.pool(aseco)
            if not self.allowed(aseco, player):
                raise ValueError('MasterAdmin access expired; assignment was not saved.')
            number = await storage.save_link(pool, action, map_id, link, track=info)
            self.revision += 1
            try:
                await self.queue(aseco)
            except Exception as error:
                await self.reply(aseco, player, f'{{#message}}Track {number} assignment saved, but could not queue settings: {error}')
                return
        state = 'removed (using normal map/environment settings)' if action == 'rem' else 'saved'
        await self.reply(aseco, player, f'{{#message}}Track {number} mod {state}. '
                         'Applies at the next map load/restart; no automatic restart.' +
                         (' ForceMods is currently off/disabled.' if not self.enabled or self.mode == 'off' else ''))


APP_CLASS = ForceModsApp
APP_INSTANCE = ForceModsApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    await APP_INSTANCE.reload_settings(aseco)
