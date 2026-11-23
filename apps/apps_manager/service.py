from __future__ import annotations

import asyncio
import logging
import sys
from time import monotonic
from copy import deepcopy
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from functools import wraps
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apps.platform_ui.hud_layout import LEGACY_PANEL_TYPES, PANELS, POSITION_STEPS
from pyxaseco.models import Gameinfo
from pyxaseco.management.app_policy import (
    MANAGEABLE_STANDALONE_APPS, PROTECTED_STANDALONE_APPS, RELOADABLE_APPS,
)
from pyxaseco.toml_tools import read_toml as _read_toml, revision_guard, update_toml_table_scalar

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


logger = logging.getLogger(__name__)

_config_snapshot: ContextVar[dict[Path, dict[str, Any]] | None] = ContextVar(
    'apps_manager_config_snapshot', default=None,
)


def read_toml(path: str | Path) -> dict[str, Any]:
    snapshot = _config_snapshot.get()
    if snapshot is None:
        return _read_toml(path)
    key = Path(path)
    if key not in snapshot:
        snapshot[key] = _read_toml(key)
    return snapshot[key]


def _with_config_snapshot(render):
    @wraps(render)
    def wrapped(*args, **kwargs):
        if _config_snapshot.get() is not None:
            return render(*args, **kwargs)
        token = _config_snapshot.set({})
        try:
            return render(*args, **kwargs)
        finally:
            _config_snapshot.reset(token)
    return wrapped


def _guard_config_change(function):
    import inspect
    signature = inspect.signature(function)
    parameters = tuple(signature.parameters)
    def file_for(args, kwargs):
        bound = signature.bind(*args, **kwargs).arguments
        aseco, target = bound[parameters[0]], bound[parameters[1]]
        relative = target['file'] if isinstance(target, dict) else f'apps/{target}/app_defaults.toml'
        return _root_dir(aseco) / relative
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def asynchronous(*args, **kwargs):
            with revision_guard(file_for(args, kwargs)):
                return await function(*args, **kwargs)
        return asynchronous
    @wraps(function)
    def synchronous(*args, **kwargs):
        with revision_guard(file_for(args, kwargs)):
            return function(*args, **kwargs)
    return synchronous


CONFIG_APPS: dict[str, dict[str, str]] = {
    'pyxa_stats': {
        'label': 'PYXA Stats',
        'save_mode': 'reload',
        'description': 'Optional external server snapshots and recent local records',
    },
    'seqinfomsg': {
        'label': 'Sequential Info Messages',
        'save_mode': 'reload',
        'description': 'Periodic chat messages and broadcast interval',
    },
    'admin': {
        'label': 'Admin',
        'save_mode': 'restart',
        'description': 'Optional admin-side extension toggles',
    },
    'ui': {
        'label': 'UI',
        'save_mode': 'reload',
        'description': 'Panels, widgets, and on-screen overlays',
    },
    'bestcps': {
        'label': 'Best CPs',
        'save_mode': 'reload',
        'description': 'Best checkpoints widget settings',
    },
    'bestsecs': {
        'label': 'Best Secs',
        'save_mode': 'reload',
        'description': 'Best sector widget settings',
    },
    'bestruns': {
        'label': 'Best Runs',
        'save_mode': 'reload',
        'description': 'Best runs widget settings',
    },
    'bestfinishes': {
        'label': 'Best Finishes',
        'save_mode': 'reload',
        'description': 'Best finishes widget settings',
    },
    'best_cp_times': {
        'label': 'Best CP Times',
        'save_mode': 'reload',
        'description': 'Best CP times widget settings',
    },
    'checkpoint_tools': {
        'label': 'Checkpoint Tools',
        'save_mode': 'reload',
        'description': 'Checkpoint live overlay settings',
    },
    'flexitime': {
        'label': 'FlexiTime',
        'save_mode': 'reload',
        'description': 'Time Attack timer settings and HUD layout',
    },
    'endlesstmxr': {
        'label': 'Endless TMX Random',
        'save_mode': 'reload',
        'description': 'Auto-skip to a random TMX map after an author-time beat',
    },
}

CONFIG_APP_DISCOVERY_EXCLUDE = {
    'admin',
    'platform_core',
    'jukebox',
}

_APPS_USAGE = (
    'Usage: /admin apps <list|status [name]|config <app>|preview [race/score/table/off] [mode]|reload <app>|enable <app>|disable <app>|'
    ' add <app>|remove <app>|rem <app>|fremove <app> confirm|frem <app> confirm|'
    ' updates|download <package>|review <package>|update <package> [force] [confirm]>'
)


def _ui_item(key: str, label: str, **extra: Any) -> dict[str, Any]:
    path = tuple(key.split('.'))
    item = {
        'key': key,
        'label': label,
        'file': 'apps/ui/app_defaults.toml',
        'table_path': ('ui',) + path,
    }
    item.update(extra)
    return item


def _ui_score_item(key: str, label: str) -> dict[str, Any]:
    return _ui_item(f'{key}.score', label, phase='score', parent_table_path=('ui', key),
                    display_label=label)


_YOUR_STATS_ITEM = 'scoretable_lists.your_stats'


def _panel_position_item(name: str, label: str, *, key: str | None = None) -> dict[str, Any]:
    return {'key': key or f'panels.{name}', 'label': label, 'display_label': label,
            'file': 'apps/platform_ui/app_defaults.toml', 'table_path': ('platform_ui', 'panels', name),
            'default_fields': {'offset_x': 0.0, 'offset_y': 0.0}}


UI_CONFIG_ITEMS: list[dict[str, Any]] = [
    _ui_item('welcome_window', 'Welcome Window'),
    _ui_item('menu', 'Menu'),
    _ui_item('challenge_widget', 'Challenge Widget', phase='race'),
    _ui_score_item('challenge_widget', 'Next Challenge'),
    _ui_item('checkpointcount_widget', 'Checkpoint Counter'),
    _ui_item('join_leave_info', 'Join/Leave Info'),
    _ui_item('donation_widget', 'Please Donate'),
    _ui_item('donation_widget.widget', 'Please Donate Layout', display_label='Please Donate Layout'),
    _ui_item('clock_widget', 'Clock Widget', phase='race'),
    _ui_score_item('clock_widget', 'Clock (Score)'),
    _ui_item('banner', 'Banner'),
    _ui_item('allbutton', 'AllButton'),
    _ui_item(
        'karma',
        'Karma',
        widget_table_path=('ui', 'karma', 'karma_widget'),
        phase='race',
    ),
    _ui_item('karma.reminder_window.score', 'Karma Reminder', display_label='Karma Reminder'),
    _ui_item('karma.karma_widget.gamemode.score', 'ManiaKarma (Score)', display_label='ManiaKarma (Score)'),
    _ui_item('ladderlimit_widget', 'Ladderlimit Widget'),
    _ui_item('gamemode_widget', 'Gamemode Widget'),
    _ui_item('player_spectator_widget', 'Player/Spectator Widget'),
    _ui_item('current_ranking_widget', 'Current Ranking Widget'),
    _ui_item('tmexchange_widget', 'TMX Widget'),
    _ui_item('toplist_widget', 'Toplist Widget'),
    _ui_item('trackcount_widget', 'Trackcount Widget'),
    _ui_item('visitors_widget', 'Visitors Widget'),
    _ui_item('discord_widget', 'Discord Widget'),
    _ui_item('force_play_widget', 'Force Play Widget'),
    _ui_item('favorite_widget', 'Favorite Widget', phase='race'),
    _ui_score_item('favorite_widget', 'Add to Favorites (Score)'),
    _ui_item('next_environment_widget', 'Next Environment Widget'),
    _ui_item('next_gamemode_widget', 'Next Gamemode Widget'),
    _ui_item('eyepiece_widget', 'Eyepiece Widget', phase='score'),
    _ui_item('dedimania_records', 'Dedimania Records'),
    _ui_item('local_records', 'Local Records'),
    _ui_item('live_rankings', 'Live Rankings'),
    _ui_item('round_score', 'Round Score'),
    _ui_item('winning_payout', 'Finish Winners'),
    _ui_item('winning_payout.widget', 'Finish Winners Layout', display_label='Finish Winners Layout'),
    _ui_item('scoretable_lists.top_average_times', 'Scoretable: Top Average Times'),
    _ui_item('scoretable_lists.dedimania_records', 'Scoretable: Dedimania Records'),
    _ui_item('scoretable_lists.local_records', 'Scoretable: Local Records'),
    _ui_item('scoretable_lists.top_rankings', 'Scoretable: Top Rankings'),
    _ui_item('scoretable_lists.top_winners', 'Scoretable: Top Winners'),
    _ui_item('scoretable_lists.most_records', 'Scoretable: Most Records'),
    _ui_item('scoretable_lists.most_finished', 'Scoretable: Most Finished'),
    _ui_item('scoretable_lists.top_playtime', 'Scoretable: Top Playtime'),
    _ui_item('scoretable_lists.top_donators', 'Scoretable: Top Donators'),
    _ui_item('scoretable_lists.top_nations', 'Scoretable: Top Nations'),
    _ui_item('scoretable_lists.top_tracks', 'Scoretable: Top Tracks'),
    _ui_item('scoretable_lists.top_voters', 'Scoretable: Top Voters'),
    _ui_item('scoretable_lists.top_visitors', 'Scoretable: Top Visitors'),
    _panel_position_item('stats', 'Your Stats', key=_YOUR_STATS_ITEM),
]

UI_DISCOVERY_EXCLUDE_PREFIXES: tuple[tuple[str, ...], ...] = (
    ('ui', 'show_progress_indicator'),
    ('ui', 'links'),
    ('ui', 'style'),
    ('ui', 'images'),
    ('ui', 'menu'),
    # Retained legacy settings with no active renderer or config binding.
    ('ui', 'music_widget'),
    ('ui', 'scoretable_lists', 'top_active_players'),
    ('ui', 'scoretable_lists', 'top_winning_payouts'),
    ('ui', 'scoretable_lists', 'top_betwins'),
    ('ui', 'scoretable_lists', 'top_roundscore'),
    ('ui', 'features', 'songlist'),
    ('ui', 'welcome_window', 'image'),
    ('ui', 'challenge_widget', 'icons'),
    ('ui', 'challenge_widget', 'title'),
    ('ui', 'challenge_widget', 'race'),
    ('ui', 'clock_widget', 'race'),
    ('ui', 'favorite_widget', 'race'),
    ('ui', 'eyepiece_widget', 'race'),
    ('ui', 'eyepiece_widget', 'score'),
    ('ui', 'karma', 'images'),
    ('ui', 'karma', 'widget_styles'),
)

STATIC_CONFIG_ITEMS: dict[str, list[dict[str, Any]]] = {
    'platform_ui': [
        _panel_position_item(name, PANELS[panel][0])
        for panel, name in LEGACY_PANEL_TYPES.items()
    ],
    'admin': [
        {
            'key': 'stalker',
            'label': 'Stalker',
            'file': 'apps/admin/app_defaults.toml',
            'table_path': ('admin', 'stalker_tools'),
            'linked_enabled_paths': (
                ('admin', 'stalker_tools'),
                ('admin', 'stalker_actionids'),
            ),
        },
    ],
    'ui': UI_CONFIG_ITEMS,
    'checkpoint_tools': [
        {
            'key': 'cplive_v3',
            'label': 'CP Live',
            'file': 'apps/checkpoint_tools/app_defaults.toml',
            'table_path': ('cplive_v3',),
        },
    ],
}

UI_GROUP_ORDER: tuple[str, ...] = (
    'Track & Challenge',
    'Bar Widgets',
    'Record Panels',
    'Karma',
    'Scoretable Lists',
    'HUD & Widgets',
    'Misc',
)

_SCORETABLE_WIDGETS = (
    'scoretable_lists', 'challenge_widget.score', 'clock_widget.score', 'favorite_widget.score',
    'next_environment_widget', 'next_gamemode_widget', 'eyepiece_widget',
    'donation_widget', 'winning_payout', 'karma.reminder_window.score', 'karma.karma_widget.gamemode.score',
)

UI_GROUP_PREFIXES: dict[str, tuple[str, ...]] = {
    'Track & Challenge': (
        'challenge_widget',
        'features.tracklist',
    ),
    'Bar Widgets': (
        'clock_widget',
        'trackcount_widget',
        'visitors_widget',
        'discord_widget',
        'force_play_widget',
        'player_spectator_widget',
        'current_ranking_widget',
        'ladderlimit_widget',
        'gamemode_widget',
        'favorite_widget',
        'tmexchange_widget',
        'toplist_widget',
    ),
    'Record Panels': (
        'dedimania_records',
        'local_records',
        'live_rankings',
        'round_score',
    ),
    'Karma': (
        'features.karma',
        'karma',
    ),
    'HUD & Widgets': (
        'banner',
        'checkpointcount_widget',
        'allbutton',
        'menu',
        'join_leave_info',
        'welcome_window',
        'custom_ui',
    ),
}


def get_service(aseco: 'Aseco') -> 'AppsManagerService | None':
    if aseco is None:
        return None
    try:
        return aseco.get_service('apps_manager')
    except Exception:
        return None


class AppsManagerService:
    def __init__(self):
        self.release_busy = False
        self.release_catalogue = None
        self.copying = False
        self.restart_needed = False
        self.pending_packages = set()
        self.pending_config = set()
        self.package_states = {}
        self.update_settings = {}
        self.next_check = 0
        self.next_notice = 0

    def configure_updates(self, aseco):
        try:
            self.update_settings = read_toml(_root_dir(aseco) / 'apps/apps_manager/app_defaults.toml').get('apps_manager', {}).get('updates', {})
        except (OSError, ValueError, AttributeError):
            self.update_settings = {}
        if not isinstance(self.update_settings, dict):
            self.update_settings = {}

    async def notice(self, aseco, player=None):
        from pyxaseco.core.aseco import PYXASECO_VERSION
        from pyxaseco.management.release_manifest import version
        if self.restart_needed:
            text = 'PyXaseco update installed. Run //pyres when ready to load the changes.'
        else:
            package = next((item for item in (self.release_catalogue or {}).get('packages', [])
                            if item['id'] == 'controller'), None)
            if package is None or version(package['version']) <= version(PYXASECO_VERSION):
                return
            text = 'PyXaseco ' + package['version'] + ' is available. Use //apps updates to review it.'
        for owner in ([player] if player is not None else aseco.server.players.all()):
            if _is_masteradmin(aseco, owner, owner.login):
                await _reply(aseco, owner.login, '{#server}> {#highlite}' + text)

    async def update_tick(self, aseco, _data=None):
        if self.update_settings.get('enabled') is not True:
            return
        owners = [player for player in aseco.server.players.all() if _is_masteradmin(aseco, player, player.login)]
        if not owners:
            return
        now = monotonic()
        if now >= self.next_notice:
            self.next_notice = now + self._interval('notice_interval_seconds', 1800)
            await self.notice(aseco)
        if not self.restart_needed and not self.release_busy and now >= self.next_check:
            self.next_check = now + self._interval('check_interval_seconds', 3600)
            await self.releases(aseco, owners[0], quiet=True)

    def _interval(self, key, default):
        value = self.update_settings.get(key, default)
        return max(60, value) if type(value) is int else default

    async def update_connect(self, aseco, player):
        if _is_masteradmin(aseco, player, player.login):
            await self.notice(aseco, player)

    async def releases(self, aseco, admin, identity=None, *, review=False, force=False,
                       install=False, reviewed=None, quiet=False):
        from .views import _show_package_review_window, _show_release_window

        login = getattr(admin, 'login', '')
        if not _is_masteradmin(aseco, admin, login):
            await _reply(aseco, login, '{#server}> {#error}Only MasterAdmins may check or download releases.')
            return
        if self.release_busy:
            if not quiet:
                await _reply(aseco, login, '{#server}> {#message}An update operation is already running.')
            return
        from pyxaseco.core.aseco import PYXASECO_VERSION
        from pyxaseco.management.config_store import ManagementError
        from pyxaseco.management.update_client import UpdateClient
        from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
        if not aseco.jobs.running:
            return
        try:
            client = UpdateClient(_root_dir(aseco), PYXASECO_VERSION)
        except (ManagementError, OSError) as error:
            self.update_settings = {}
            logger.warning('[Updates] %s', error)
            if not quiet:
                await _reply(aseco, login, '{#server}> {#error}' + (
                    str(error) if isinstance(error, ManagementError) else 'Could not read the Apps Manager update settings.'))
            return
        self.update_settings = client.settings
        self.release_busy = True
        self.copying = install
        job = JobEnvelope.capture(aseco.capture_job_context(login=login), {'package': identity})

        async def operation(_envelope):
            try:
                if install:
                    return await client.apply(identity, reviewed=reviewed, force=force, confirmed=True)
                if review:
                    return await client.preview(identity, force=force)
                if identity:
                    return await client.stage(identity)
                catalogue = await client.check()
                try:
                    states = await asyncio.to_thread(client.local_package_states, catalogue)
                except (ValueError, ManagementError, OSError):
                    states = {}
                return {'catalogue': catalogue, 'states': states}
            except (ManagementError, OSError) as error:
                return {'error': str(error) if isinstance(error, ManagementError) else 'Could not read/write local update files.'}

        async def done(result):
            self.release_busy = False
            self.copying = False
            data = result.value if result.status == 'completed' else {'error': 'Update operation did not complete; check the local backup report before retrying.'}
            connected = aseco.server.players.get_player(login) is admin and _is_masteradmin(aseco, admin, login)
            if 'error' in data:
                if identity is None:
                    self.release_catalogue = None
                logger.warning('[Updates] %s', data['error'])
                if connected and not quiet:
                    await _reply(aseco, login, '{#server}> {#error}' + data['error'])
                return
            if install:
                self.restart_needed = self.restart_needed or data['restart_required']
                self.package_states[data['package']] = 'local_changes' if data['kept_modified'] else 'installed'
                if data['restart_required']:
                    self.pending_packages.add(data['package'])
                logger.info('[Updates] Copied %s files; report: %s', data['copied'], data['report'])
                if connected:
                    await _reply(aseco, login, f"{{#server}}> {{#message}}Copied {data['copied']} files; kept {data['kept_modified']} modified files. Backups and diffs saved.")
                await self.notice(aseco)
                self.next_notice = monotonic() + self._interval('notice_interval_seconds', 1800)
            elif review and connected:
                _show_package_review_window(aseco, admin, data)
            elif identity and not review:
                self.package_states[identity] = 'downloaded'
                if connected:
                    await _reply(aseco, login, f"{{#server}}> {{#message}}{data['id']} {data['version']} downloaded and verified. Use //apps update {identity} to review changes.")
                    if self.release_catalogue:
                        _show_release_window(aseco, admin, self.release_catalogue)
            elif not identity:
                self.release_catalogue = data['catalogue']
                self.package_states = data['states']
                self.next_check = monotonic() + self._interval('check_interval_seconds', 3600)
                if connected and not quiet:
                    _show_release_window(aseco, admin, self.release_catalogue)
                if quiet:
                    await self.notice(aseco)

        async def discarded(_result):
            self.release_busy = False
            self.copying = False

        outcome = aseco.jobs.service('apps_updates', JobPolicy(capacity=1, workers=1,
            deadline_seconds=300, max_attempts=1)).submit(job, operation, done,
            current_map=False, revision_guard=False, discard=discarded)
        if outcome != Admission.ACCEPTED:
            self.release_busy = self.copying = False
            if not quiet:
                await _reply(aseco, login, '{#server}> {#message}Update request deferred; try again shortly.')
        elif not quiet:
            await _reply(aseco, login, '{#server}> {#message}Validating both publishers in the background. No automatic restart.')

    async def handle_action(self, aseco: 'Aseco', admin, answer: list[Any]) -> bool:
        from .commands import handle_apps_action
        return await handle_apps_action(aseco, admin, answer)

    async def handle_command(self, aseco: 'Aseco', login: str, admin, args: list[str]) -> bool:
        from .commands import _handle_apps_command
        await _handle_apps_command(aseco, login, admin, args)
        return True


def _root_dir(aseco: 'Aseco') -> Path:
    return Path(str(getattr(aseco, 'base_dir', Path.cwd())))


def _apps_toml_path(aseco: 'Aseco') -> Path:
    return _root_dir(aseco) / 'apps.toml'


def _apps_dir(aseco: 'Aseco') -> Path:
    return _root_dir(aseco) / 'apps'


def _removed_apps_dir(aseco: 'Aseco') -> Path:
    return _apps_dir(aseco) / '00removed'


def _normalize_app_name(name: str) -> str:
    value = str(name or '').strip().lower().replace('\\', '/')
    if value.startswith('app/'):
        value = value[4:]
    return value.strip('/')


def _app_defaults_path_for_app(aseco: 'Aseco', app_key: str) -> Path:
    return _apps_dir(aseco) / app_key / 'app_defaults.toml'


def _format_config_label(parts: tuple[str, ...]) -> str:
    text = ' / '.join(str(part).replace('_', ' ').strip() for part in parts if str(part).strip())
    return text.title() if text else 'Config'


def _is_ui_discovery_excluded(table_path: tuple[str, ...]) -> bool:
    lowered = tuple(str(part).strip().lower() for part in table_path)
    if any(part in {'colors', 'messages', 'urls'} for part in lowered):
        return True
    return any(tuple(lowered[:len(prefix)]) == tuple(str(part).strip().lower() for part in prefix) for prefix in UI_DISCOVERY_EXCLUDE_PREFIXES)


def _can_configure_app(aseco, app_key):
    if not (_apps_dir(aseco) / app_key).is_dir() or _standalone_loadout_state(aseco, app_key) != 'enabled':
        return False
    active = getattr(aseco, 'active_apps', None)
    return active is None or app_key in active


def _discover_config_apps(aseco: 'Aseco') -> dict[str, dict[str, str]]:
    discovered = {key: spec for key, spec in CONFIG_APPS.items() if _can_configure_app(aseco, key)}
    apps_dir = _apps_dir(aseco)
    if not apps_dir.exists():
        return discovered
    for path in sorted(apps_dir.glob('*/app_defaults.toml')):
        app_key = path.parent.name
        if app_key == '00removed' or app_key in CONFIG_APP_DISCOVERY_EXCLUDE or not _can_configure_app(aseco, app_key):
            continue
        discovered.setdefault(app_key, {
            'label': app_key.replace('_', ' ').title(),
            'save_mode': 'reload' if app_key in RELOADABLE_APPS else 'restart',
            'description': 'App settings from app_defaults.toml',
        })
    return discovered


def _read_nested(data: Any, path: tuple[str, ...]) -> Any:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _discover_table_items_from_data(
    aseco: 'Aseco',
    app_key: str,
    file_path: Path,
    root_table: tuple[str, ...],
    data: dict[str, Any],
    *,
    label_prefix: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    root = _read_nested(data, root_table)
    if not isinstance(root, dict):
        return []

    file_name = str(file_path.relative_to(_root_dir(aseco))).replace('\\', '/')
    items: list[dict[str, Any]] = []

    def visit(path_parts: tuple[str, ...], table: dict[str, Any], labels: tuple[str, ...]) -> None:
        scalar_keys = [key for key, value in table.items() if not isinstance(value, dict)]
        if scalar_keys:
            rel_parts = path_parts if path_parts else (root_table[-1],)
            items.append({
                'key': '.'.join(rel_parts),
                'label': _format_config_label(labels or rel_parts[-1:]),
                'file': file_name,
                'table_path': root_table + path_parts,
            })
        for key, value in table.items():
            if isinstance(value, dict):
                visit(path_parts + (key,), value, labels + (key,))

    visit((), root, label_prefix)
    return items


def _config_items_for_app(aseco: 'Aseco', app_key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def append_item(item: dict[str, Any], *, allow_excluded: bool = False) -> None:
        if app_key == 'ui' and not allow_excluded and _is_ui_discovery_excluded(tuple(item.get('table_path', ()))):
            return
        ident = (str(item.get('file', '')), tuple(item.get('table_path', ())))
        if ident in seen:
            return
        seen.add(ident)
        items.append(item)

    for item in STATIC_CONFIG_ITEMS.get(app_key, []):
        append_item(item, allow_excluded=True)

    if app_key == 'admin':
        return items

    file_path = _app_defaults_path_for_app(aseco, app_key)
    if file_path.exists():
        if app_key == 'flexitime':
            from apps.flexitime.flexitime import HUD_DEFAULTS
            append_item({
                'key': 'hud', 'label': 'Timer HUD',
                'file': 'apps/flexitime/app_defaults.toml',
                'table_path': ('flexitime', 'hud'),
                'default_fields': HUD_DEFAULTS,
                'field_labels': {'width': 'Background width', 'height': 'Background height', 'text_scale': 'Timer text scale'},
            })
        data = read_toml(file_path)
        for root_key, root_value in data.items():
            if not isinstance(root_value, dict):
                continue
            discovered = _discover_table_items_from_data(
                aseco,
                app_key,
                file_path,
                (str(root_key),),
                data,
                label_prefix=(str(root_key),) if app_key != 'ui' else (),
            )
            for item in discovered:
                append_item(item)

    return items


def _config_item_owner(aseco: 'Aseco', name: str) -> tuple[str, dict[str, Any]] | None:
    for app_key in _discover_config_apps(aseco):
        for item in _config_items_for_app(aseco, app_key):
            if item['key'] == name:
                return app_key, item
    return None


def _login_in_masteradmin_list(aseco: 'Aseco', login: str) -> bool:
    login_l = str(login or '').strip().lower()
    if not login_l:
        return False
    role_list = getattr(aseco.settings, 'masteradmin_list', {})
    vals = role_list.get('TMLOGIN', []) if isinstance(role_list, dict) else []
    return any(str(v).strip().lower() == login_l for v in vals)


def _is_masteradmin(aseco: 'Aseco', admin, login: str = '') -> bool:
    try:
        checker = getattr(aseco, 'is_master_admin', None)
        if callable(checker) and admin is not None and checker(admin):
            return True
    except Exception:
        pass
    return _login_in_masteradmin_list(aseco, getattr(admin, 'login', '') or login)


async def _reply(aseco: 'Aseco', login: str, msg: str) -> None:
    from apps.admin.command_router import _reply as admin_reply
    await admin_reply(aseco, login, msg)


def _reply_apps_usage(aseco: 'Aseco', login: str):
    return _reply(aseco, login, '{#server}> {#message}' + _APPS_USAGE)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'on', 'yes'}
    return bool(value)


def _parse_numeric_string(value: Any) -> tuple[str, int | float] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed_float = float(text)
    except Exception:
        return None
    if not isfinite(parsed_float):
        return None
    if any(ch in text for ch in ('.', 'e', 'E')):
        return 'float', parsed_float
    try:
        parsed_int = int(text)
    except Exception:
        return 'float', parsed_float
    return 'int', parsed_int


def _standalone_loadout_state(aseco: 'Aseco', name: str) -> str:
    entry = f'app/{name}'
    data = read_toml(_apps_toml_path(aseco))
    loadout = data.get('loadout', {}) if isinstance(data, dict) else {}
    enabled = set(loadout.get('enabled', []) or [])
    disabled = set(loadout.get('disabled', []) or [])
    if entry in enabled:
        return 'enabled'
    if entry in disabled:
        return 'disabled'
    return 'unlisted'


def _existing_archive_path(aseco: 'Aseco', name: str) -> Path | None:
    removed_dir = _removed_apps_dir(aseco)
    exact = removed_dir / name
    if exact.exists():
        return exact
    if not removed_dir.exists():
        return None
    matches = sorted(removed_dir.glob(f'{name}_*'))
    return matches[-1] if matches else None


def _standalone_paths(aseco: 'Aseco', name: str) -> tuple[Path, Path | None]:
    app_dir = _apps_dir(aseco) / name
    archived = _existing_archive_path(aseco, name)
    return app_dir, archived


def _is_manageable_standalone_app(aseco: 'Aseco', name: str) -> bool:
    if name not in MANAGEABLE_STANDALONE_APPS:
        return False
    app_dir, archived = _standalone_paths(aseco, name)
    state = _standalone_loadout_state(aseco, name)
    return app_dir.exists() or archived is not None or state in {'enabled', 'disabled'}


def _standalone_app_names() -> list[str]:
    return list(MANAGEABLE_STANDALONE_APPS.keys())


def _standalone_status(aseco: 'Aseco', name: str) -> str:
    app_dir, archived = _standalone_paths(aseco, name)
    loadout_state = _standalone_loadout_state(aseco, name)
    if app_dir.exists():
        return 'enabled' if loadout_state == 'enabled' else 'disabled'
    if archived is not None:
        return 'removed'
    if loadout_state == 'enabled':
        return 'enabled (missing files)'
    if loadout_state == 'disabled':
        return 'disabled (missing files)'
    return 'missing'


def _runtime_status(aseco, name, loadout, disk_status=None):
    service = get_service(aseco)
    active = name in (getattr(aseco, 'active_apps', ()) or ())
    if active and loadout == 'disabled':
        return 'Pending restart: disable'
    if not active and loadout == 'enabled':
        return 'Files missing' if disk_status == 'enabled (missing files)' else 'Pending restart: enable'
    if service and (name in service.pending_packages or name in service.pending_config):
        return 'Pending restart'
    if active:
        return 'Active now'
    if service and service.package_states.get(name) == 'downloaded':
        return 'Downloaded, not installed'
    return disk_status or 'Not active'


def _mark_config_pending(aseco, name, pending=True):
    service = get_service(aseco)
    if service:
        if pending:
            service.pending_config.add(name)
        else:
            service.pending_config.discard(name)


def _archive_destination(aseco: 'Aseco', name: str) -> Path:
    removed_dir = _removed_apps_dir(aseco)
    removed_dir.mkdir(parents=True, exist_ok=True)
    base = removed_dir / name
    if not base.exists():
        return base
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return removed_dir / f'{name}_{stamp}'


def _restart_required_message(action: str) -> str:
    return f'{{#server}}> {{#message}}Change saved: {{#highlite}}{action}{{#message}} Restart required.'


def _reload_done_message(action: str) -> str:
    return f'{{#server}}> {{#message}}Change saved: {{#highlite}}{action}{{#message}} Saved and reloaded.'


def _unknown_apps_target(name: str) -> str:
    return (
        f'{{#server}}> {{#error}}Unknown app/feature {{#highlite}}{name}'
        f'{{#error}}. Use {{#highlite}}/admin apps{{#error}} to view manageable entries.'
    )


def _is_ui_item(item: dict[str, Any]) -> bool:
    return str(item.get('file', '')).replace('\\', '/') == 'apps/ui/app_defaults.toml'


def _current_ui_mode_key(aseco: 'Aseco') -> str | None:
    mode = getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1)
    try:
        from apps.ui.config import _effective_mode
        mode = _effective_mode(aseco)
    except Exception:
        pass

    mapping = {
        Gameinfo.RNDS: 'rounds',
        Gameinfo.TA: 'time_attack',
        Gameinfo.TEAM: 'team',
        Gameinfo.LAPS: 'laps',
        Gameinfo.STNT: 'stunts',
        Gameinfo.CUP: 'cup',
        Gameinfo.SCOR: 'score',
    }
    return mapping.get(int(mode)) if isinstance(mode, int) else None


def _ui_showing_score(aseco: 'Aseco') -> bool:
    from pyxaseco.core.widget_delivery import is_score_phase
    if getattr(aseco, 'score_phase', None) is not None:
        return is_score_phase(aseco)
    try:
        from apps.ui.config import _state as ui_state
        if bool(getattr(ui_state, 'challenge_show_next', False)):
            return True
    except Exception:
        pass
    return is_score_phase(aseco)


def _current_ui_runtime_mode_key(aseco: 'Aseco', base_table: dict[str, Any], scope=None) -> str | None:
    gamemode_table = base_table.get('gamemode')
    if not isinstance(gamemode_table, dict):
        return None
    score = scope[1] == 'score' if scope else _ui_showing_score(aseco)
    if score and isinstance(gamemode_table.get('score'), dict):
        return 'score'
    return scope[0] if scope else _current_ui_mode_key(aseco)


def _current_ui_phase_key(aseco: 'Aseco', mode_table: dict[str, Any], scope=None) -> str | None:
    if not isinstance(mode_table, dict):
        return None
    if scope:
        return scope[1] if isinstance(mode_table.get(scope[1]), dict) else 'race'
    if not any(isinstance(mode_table.get(name), dict) for name in ('race', 'warmup')):
        return None
    return 'warmup' if bool(getattr(aseco, 'warmup_phase', False)) and isinstance(mode_table.get('warmup'), dict) else 'race'


def _config_item_target_info_from_data(
    aseco: 'Aseco',
    item: dict[str, Any],
    data: dict[str, Any],
    *,
    file_path: Path | None = None,
    scope=None,
) -> dict[str, Any]:
    if file_path is None:
        file_path = _root_dir(aseco) / item['file']
    base_path = tuple(item.get('parent_table_path') or item['table_path'])
    base_table = _read_nested(data, base_path)
    default_fields = item.get('default_fields', {})
    if base_table is None and default_fields:
        base_table = {}
    if not isinstance(base_table, dict):
        return {
            'file_path': file_path,
            'base_path': base_path,
            'write_path': base_path,
            'base_table': None,
            'mode_key': None,
            'phase_key': None,
            'effective_table': None,
            'widget_base_path': tuple(item.get('widget_table_path') or ()),
            'widget_mode_path': None,
            'widget_mode_table': None,
        }

    effective = {**default_fields, **base_table}
    write_path = base_path
    mode_key = None
    phase_key = None
    mode_path = None
    mode_table = None
    phase_path = None
    phase_table = None
    widget_base_path = tuple(item.get('widget_table_path') or ())
    widget_mode_path = None
    widget_mode_table = None

    if widget_base_path:
        widget_root = _read_nested(data, widget_base_path)
        if isinstance(widget_root, dict) and isinstance(widget_root.get('gamemode'), dict):
            mode_key = ((scope[0] if scope else _current_ui_mode_key(aseco)) if item.get('phase') == 'race'
                        else _current_ui_runtime_mode_key(aseco, widget_root, scope))
            widget_mode_table = widget_root['gamemode'].get(mode_key) if mode_key else None
            if isinstance(widget_mode_table, dict):
                effective.update(widget_mode_table)
                widget_mode_path = widget_base_path + ('gamemode', mode_key)
                write_path = widget_mode_path
        return {
            'file_path': file_path,
            'base_path': base_path,
            'write_path': write_path,
            'base_table': base_table,
            'mode_key': mode_key,
            'mode_path': mode_path,
            'mode_table': mode_table,
            'phase_key': phase_key,
            'phase_path': phase_path,
            'phase_table': phase_table,
            'effective_table': effective,
            'widget_base_path': widget_base_path,
            'widget_mode_path': widget_mode_path,
            'widget_mode_table': widget_mode_table,
        }

    if _is_ui_item(item) and isinstance(base_table.get('gamemode'), dict):
        mode_key = _current_ui_runtime_mode_key(aseco, base_table, scope)
        mode_table = base_table['gamemode'].get(mode_key) if mode_key else None
        if isinstance(mode_table, dict):
            effective.update(mode_table)
            mode_path = base_path + ('gamemode', mode_key)
            write_path = mode_path
            phase_key = _current_ui_phase_key(aseco, mode_table, scope)
            if phase_key and isinstance(mode_table.get(phase_key), dict):
                phase_table = mode_table[phase_key]
                effective.update(phase_table)
                phase_path = mode_path + (phase_key,)
                write_path = phase_path
    elif _is_ui_item(item):
        direct_phase_key = item.get('phase') or (scope[1] if scope else ('score' if _ui_showing_score(aseco) else 'race'))
        direct_phase_table = base_table.get(direct_phase_key)
        if isinstance(direct_phase_table, dict):
            effective.update(direct_phase_table)
            phase_path = base_path + (direct_phase_key,)
            write_path = phase_path
            phase_key = direct_phase_key
            phase_table = direct_phase_table

    return {
        'file_path': file_path,
        'base_path': base_path,
        'write_path': write_path,
        'base_table': base_table,
        'mode_key': mode_key,
        'mode_path': mode_path,
        'mode_table': mode_table,
        'phase_key': phase_key,
        'phase_path': phase_path,
        'phase_table': phase_table,
        'effective_table': effective,
        'widget_base_path': widget_base_path,
        'widget_mode_path': widget_mode_path,
        'widget_mode_table': widget_mode_table,
        'scope': scope,
    }


def _config_item_target_info(aseco: 'Aseco', item: dict[str, Any], *, scope=None) -> dict[str, Any]:
    file_path = _root_dir(aseco) / item['file']
    data = read_toml(file_path)
    return _config_item_target_info_from_data(aseco, item, data, file_path=file_path, scope=scope)


def _config_field_write_path(item: dict[str, Any], info: dict[str, Any], field_key: str) -> tuple[str, ...]:
    if item.get('widget_table_path'):
        if field_key == 'enabled':
            return tuple(info.get('base_path') or ())
        if field_key == 'widget_enabled':
            return tuple(info.get('widget_mode_path') or info.get('widget_base_path') or ())

    phase_path = info.get('phase_path')
    phase_table = info.get('phase_table')
    if isinstance(phase_table, dict) and field_key in phase_table and isinstance(phase_path, tuple):
        return phase_path

    mode_path = info.get('mode_path')
    mode_table = info.get('mode_table')
    if isinstance(mode_table, dict) and field_key in mode_table and isinstance(mode_path, tuple):
        return mode_path
    if (info.get('scope') and isinstance(mode_path, tuple)
            and item['key'] in ('local_records', 'dedimania_records', 'live_rankings')
            and field_key in ('width', 'height')):
        return mode_path

    widget_mode_path = info.get('widget_mode_path')
    widget_mode_table = info.get('widget_mode_table')
    if isinstance(widget_mode_table, dict) and field_key in widget_mode_table and isinstance(widget_mode_path, tuple):
        return widget_mode_path

    base_path = info.get('base_path')
    base_table = info.get('base_table')
    if isinstance(base_table, dict) and field_key in base_table and isinstance(base_path, tuple):
        return base_path

    return tuple(info.get('write_path') or ())


def _config_item_state_from_info(item: dict[str, Any], info: dict[str, Any]) -> str:
    if item['key'] == 'stalker':
        file_path = info['file_path']
        data = read_toml(file_path)
        states: list[bool] = []
        for path in tuple(item.get('linked_enabled_paths') or ()):
            table = _read_nested(data, tuple(path))
            if isinstance(table, dict) and 'enabled' in table:
                states.append(_coerce_bool(table.get('enabled', False)))
        if not states:
            return 'missing'
        if all(states):
            return 'enabled'
        if not any(states):
            return 'disabled'
        return 'mixed'

    table = info['effective_table']
    if not isinstance(table, dict):
        return 'missing'
    if 'enabled' not in table:
        return 'config'
    return 'enabled' if _coerce_bool(info['base_table'].get('enabled', False) if item.get('widget_table_path') else table.get('enabled', False)) else 'disabled'


def _config_item_state(aseco: 'Aseco', item: dict[str, Any]) -> str:
    return _config_item_state_from_info(item, _config_item_target_info(aseco, item))


def _config_item_state_text(state: str) -> str:
    return {
        'enabled': '{#record}Enabled',
        'disabled': '{#error}Disabled',
        'mixed': '{#highlite}Mixed',
        'config': '{#message}Config',
        'missing': '{#error}Missing',
    }.get(state, state)


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        text = f'{value:.2f}'
        return text.rstrip('0').rstrip('.') if '.' in text else text
    return str(value)


def _parse_pair(value: Any) -> tuple[float, float] | None:
    parts = str(value or '').replace(',', ' ').split()
    if len(parts) != 2:
        return None
    try:
        x, y = float(parts[0]), float(parts[1])
        return (x, y) if isfinite(x) and isfinite(y) else None
    except ValueError:
        return None


def _position_field(key: str) -> tuple[str, str] | None:
    field = key.lower()
    if field in ('x', 'y', 'xpos', 'ypos'):
        axis, prefix = field[0], ''
    elif field.endswith(('_x', '_y')):
        axis, prefix = field[-1], field[:-2]
        prefix = '' if prefix in ('pos', 'position') else prefix.removesuffix('_pos').removesuffix('_position')
    elif field in ('x_counter', 'y_counter'):
        axis, prefix = field[0], 'counter'
    else:
        return None
    direction = 'Left / Right' if axis == 'x' else 'Up / Down'
    return axis, f'{prefix.replace("_", " ").title()}: {direction}' if prefix else direction


_SIZE_FIELDS = {
    'width', 'height', 'size', 'row_height', 'scale', 'textsize', 'textscale', 'text_size',
    'text_scale', 'min_width', 'max_width', 'char_width', 'edge_shift', 'tile_spacing', 'rail_spacing',
}
_LEGACY_BOOLEANS = {'true', 'false', 'on', 'off', 'yes', 'no', '1', '0'}


def _size_field(item, key):
    # Image dimensions are whole pixels, not ManiaLink layout units.
    return key in _SIZE_FIELDS and not (
        item['file'] == 'apps/serverstats/app_defaults.toml' and key in {'width', 'height'}
    )


def _geometry_default(item, key, *, position):
    parts = Path(item['file']).parts
    module = sys.modules.get(f'apps.{parts[1]}.app') if len(parts) == 3 and parts[0] == 'apps' else None
    schema = getattr(getattr(module, 'APP_INSTANCE', None), 'settings_schema', None)
    table_path = item['table_path']
    if schema is not None and table_path[0] == schema.resolve_section_name():
        setting_key = '/'.join((*table_path[1:], key))
        for setting in schema.settings:
            if setting.key == setting_key and type(setting.default) in (int, float):
                return setting.default
    return 0 if position else 1


def _config_item_summary_from_info(aseco: 'Aseco', item: dict[str, Any], info: dict[str, Any]) -> str:
    if item['key'] == 'stalker':
        file_path = info['file_path']
        data = read_toml(file_path)
        stalker_tools = _read_nested(data, ('admin', 'stalker_tools'))
        stalker_actionids = _read_nested(data, ('admin', 'stalker_actionids'))
        tools_enabled = _coerce_bool(stalker_tools.get('enabled', False)) if isinstance(stalker_tools, dict) else False
        actionids_enabled = _coerce_bool(stalker_actionids.get('enabled', False)) if isinstance(stalker_actionids, dict) else False
        return f"tools={_display_value(tools_enabled)}, actionids={_display_value(actionids_enabled)}"

    table = info['effective_table']
    if not isinstance(table, dict):
        return '-'

    if item['key'] == 'menu':
        pos = _parse_pair(table.get('position'))
        size = str(table.get('size', '')).strip()
        parts = []
        if pos:
            parts.extend((f'Left/Right={_display_value(pos[0])}', f'Up/Down={_display_value(pos[1])}'))
        if size:
            parts.append(f'size={size}')
        return ', '.join(parts) or '-'

    if item['key'] == 'karma':
        parts: list[str] = [f"enabled={_display_value(_coerce_bool(info['base_table'].get('enabled', False)))}"]
        widget_table = info.get('widget_mode_table')
        if isinstance(widget_table, dict):
            if 'enabled' in widget_table:
                parts.append(f"widget={_display_value(_coerce_bool(widget_table.get('enabled', False)))}")
            if 'pos_x' in widget_table:
                parts.append(f"Left/Right={widget_table['pos_x']}")
            if 'pos_y' in widget_table:
                parts.append(f"Up/Down={widget_table['pos_y']}")
        if info.get('mode_key'):
            parts.insert(0, f"mode={info['mode_key']}")
        return ', '.join(parts[:5])

    parts: list[str] = []
    if 'enabled' in table:
        parts.append(f"enabled={_display_value(_coerce_bool(table.get('enabled')))}")
    for key, value in table.items():
        position = _position_field(key)
        if position and not isinstance(value, (bool, dict)):
            parts.append(f'{position[1]}={_display_value(value)}')
    if 'width' in table:
        parts.append(f"w={table['width']}")
    if 'height' in table:
        parts.append(f"h={table['height']}")
    if 'entries' in table:
        parts.append(f"n={table['entries']}")
    if 'row_height' in table:
        parts.append(f"row={table['row_height']}")
    if 'number' in table:
        parts.append(f"n={table['number']}")
    if 'topcount' in table:
        parts.append(f"top={table['topcount']}")
    if not parts:
        generic_parts: list[str] = []
        for key, value in table.items():
            if isinstance(value, dict):
                continue
            if key in {'position', 'size', 'template_xml', 'entries_json'}:
                continue
            if isinstance(value, bool):
                generic_parts.append(f'{key}={_display_value(value)}')
            elif isinstance(value, str) and value.strip().lower() in {'true', 'false', 'on', 'off', 'yes', 'no', '1', '0'}:
                generic_parts.append(f'{key}={_display_value(_coerce_bool(value))}')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                generic_parts.append(f'{key}={_display_value(value)}')
            elif _parse_numeric_string(value) is not None:
                generic_parts.append(f'{key}={_display_value(_parse_numeric_string(value)[1])}')
        if not generic_parts:
            return '-'
        parts = generic_parts
    if info['mode_key']:
        parts.insert(0, f"mode={info['mode_key']}")
    if info['phase_key']:
        parts.insert(1, f"phase={info['phase_key']}")
    return ', '.join(parts[:6])


def _config_item_summary(aseco: 'Aseco', item: dict[str, Any]) -> str:
    return _config_item_summary_from_info(aseco, item, _config_item_target_info(aseco, item))


def _editable_fields_from_info(aseco: 'Aseco', item: dict[str, Any], info: dict[str, Any]) -> list[dict[str, Any]]:
    table = info['effective_table'] if isinstance(info.get('effective_table'), dict) else None
    if not table:
        return []

    fields: list[dict[str, Any]] = []
    handled_fields: set[str] = set()

    def add_numeric(field_key: str, label: str, step_small: float, step_big: float, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if field_key in handled_fields:
            return
        kind = 'int' if isinstance(value, int) and not isinstance(value, bool) else 'float'
        fields.append({
            'field_key': field_key,
            'label': label,
            'kind': kind,
            'value': value,
            'step_small': step_small,
            'step_big': step_big,
            'write_path': _config_field_write_path(item, info, field_key),
        })
        handled_fields.add(field_key)

    def add_geometry(field_key, value, *, write_key=None, component=None):
        position = _position_field(field_key)
        if position is None and component is None and not _size_field(item, field_key):
            return
        parsed = _parse_numeric_string(value) if isinstance(value, str) else None
        numeric = parsed[1] if parsed is not None else value
        if type(value) is bool or (parsed is None and isinstance(value, str)
                                  and value.strip().lower() in _LEGACY_BOOLEANS):
            # Old editors could persist a boolean for a quoted 0 or 1.
            numeric = _geometry_default(item, field_key, position=position is not None)
            parsed = None
        if not isinstance(numeric, (int, float)) or not isfinite(numeric):
            return
        axis, label = position or (None, {'size_w': 'width', 'size_h': 'height'}.get(field_key, field_key))
        label = item.get('field_labels', {}).get(field_key, label)
        if item['key'] == 'banner' and field_key == 'width':
            label = 'Maximum width'
        write_key = write_key or field_key
        fields.append({
            'field_key': field_key, 'label': label, 'axis': axis, 'kind': 'float', 'value': numeric,
            'geometry': True, 'component': component,
            'storage': 'string' if isinstance(value, str) else 'number',
            'input_number': value.strip() if parsed is not None else str(numeric),
            'write_key': write_key, 'write_path': _config_field_write_path(item, info, write_key),
        })
        handled_fields.add(field_key)

    def add_bool(field_key: str, label: str, value: Any, *, storage: str | None = None) -> None:
        if field_key in handled_fields:
            return
        raw = value
        fields.append({
            'field_key': field_key,
            'label': label,
            'kind': 'bool',
            'value': _coerce_bool(value),
            'step_small': 1,
            'step_big': 1,
            'storage': storage or ('string' if isinstance(raw, str) else 'bool'),
            'write_path': _config_field_write_path(item, info, field_key),
        })
        handled_fields.add(field_key)

    def add_numeric_string(field_key: str, label: str, value: Any) -> None:
        if field_key in handled_fields:
            return
        parsed = _parse_numeric_string(value)
        if parsed is None:
            return
        kind, numeric_value = parsed
        fields.append({
            'field_key': field_key,
            'label': label,
            'kind': kind,
            'value': numeric_value,
            'step_small': 1 if kind == 'int' else 0.1,
            'step_big': 10 if kind == 'int' else 10.0,
            'storage': 'string',
            'write_path': _config_field_write_path(item, info, field_key),
        })
        handled_fields.add(field_key)

    if item['key'] == 'karma':
        add_bool('enabled', 'enabled', info['base_table'].get('enabled', False))
        widget_table = info.get('widget_mode_table')
        if isinstance(widget_table, dict) and 'enabled' in widget_table:
            add_bool('widget_enabled', 'widget_enabled', widget_table.get('enabled', False), storage='string' if isinstance(widget_table.get('enabled'), str) else None)

    pair_pos = _parse_pair(table.get('position'))
    pair_size = _parse_pair(table.get('size'))
    if pair_pos is not None:
        add_geometry('position_x', pair_pos[0], write_key='position', component=0)
        add_geometry('position_y', pair_pos[1], write_key='position', component=1)
        handled_fields.add('position')
    if pair_size is not None:
        add_geometry('size_w', pair_size[0], write_key='size', component=0)
        add_geometry('size_h', pair_size[1], write_key='size', component=1)
        handled_fields.add('size')

    for key, value in table.items():
        if key not in handled_fields:
            add_geometry(key, value)
    add_numeric('entries', 'entries', 1, 10, table.get('entries'))
    add_numeric('topcount', 'topcount', 1, 10, table.get('topcount'))
    add_numeric('number', '# entries', 1, 10, table.get('number'))
    add_numeric('window_lines', 'window_lines', 1, 10, table.get('window_lines'))

    for key, value in table.items():
        if key in handled_fields:
            continue
        if isinstance(value, dict):
            continue
        if key in {'template_xml', 'entries_json', 'title', 'text_color', 'background_color', 'button_color'}:
            continue
        if item['key'] == 'karma' and key == 'enabled':
            continue
        if isinstance(value, bool):
            add_bool(key, key, value)
            continue
        if isinstance(value, str) and value.strip().lower() in _LEGACY_BOOLEANS:
            add_bool(key, key, value)
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            add_numeric(key, key, 1, 10, value)
            continue
        if isinstance(value, float):
            add_numeric(key, key, 0.1, 10.0, value)
            continue
        if _parse_numeric_string(value) is not None:
            add_numeric_string(key, key, value)

    return fields


def _editable_fields(aseco: 'Aseco', item: dict[str, Any], *, scope=None) -> list[dict[str, Any]]:
    return _editable_fields_from_info(aseco, item, _config_item_target_info(aseco, item, scope=scope))


def _write_config_value(aseco, item, file_path, table_path, field_key, value):
    parts = Path(item['file']).parts
    module = sys.modules.get(f'apps.{parts[1]}.app') if len(parts) == 3 and parts[0] == 'apps' else None
    validator = getattr(module, 'validate_config', None)
    if callable(validator):
        document = deepcopy(read_toml(file_path))
        table = document
        for key in table_path:
            table = table.setdefault(key, {})
        table[field_key] = value
        try:
            validator(document, _root_dir(aseco))
        except ValueError as error:
            raise ValueError(f'Not saved: {error}') from error
    update_toml_table_scalar(file_path, table_path, field_key, value)


@_guard_config_change
def _update_config_field(aseco: 'Aseco', item: dict[str, Any], field_key: str, delta: float, *, scope=None) -> str:
    info = _config_item_target_info(aseco, item, scope=scope)
    file_path = info['file_path']
    table = info['effective_table']

    def normalize(value: float, kind: str) -> int | float:
        if kind == 'int':
            return int(round(value))
        return round(float(value), 2)

    editable = {entry['field_key']: entry for entry in _editable_fields_from_info(aseco, item, info)}
    spec = editable.get(field_key)
    if not spec:
        return f'{item["key"]}.{field_key}'

    write_field_key = spec.get('write_key', 'enabled' if field_key == 'widget_enabled' else field_key)
    table_path = spec.get('write_path', _config_field_write_path(item, info, write_field_key))

    if spec['kind'] == 'bool':
        next_value = True if delta >= 0 else False
        stored_value: Any = str(next_value).lower() if spec.get('storage') == 'string' else next_value
        _write_config_value(aseco, item, file_path, table_path, write_field_key, stored_value)
        return f'{item["key"]}.{field_key} = {_display_value(next_value)}'

    if spec.get('geometry'):
        if abs(delta) not in POSITION_STEPS:
            raise ValueError('Position and size use steps of 0.1, 1 or 10.')
        component = spec['component']
        components = str(table[write_field_key]).replace(',', ' ').split() if component is not None else None
        number = components[component] if components is not None else spec['input_number']
        adjusted = Decimal(number) + Decimal(str(delta))
        if not isfinite(float(adjusted)) or (not spec['axis'] and adjusted < 0):
            raise ValueError(f'{spec["label"]} must be a finite number' +
                             ('.' if spec['axis'] else ' of zero or more.'))
        if not spec['axis'] and adjusted == 0 and field_key in {
                'size', 'size_w', 'size_h', 'scale', 'row_height', 'textsize', 'text_size', 'textscale', 'text_scale'}:
            raise ValueError(f'{spec["label"]} must be greater than zero.')
        rendered = format(adjusted, 'f')
        if '.' in rendered:
            rendered = rendered.rstrip('0').rstrip('.')
        if components is not None:
            components[component] = rendered
            stored_value = ' '.join(components)
        else:
            stored_value = rendered if spec.get('storage') == 'string' else float(adjusted)
        _write_config_value(aseco, item, file_path, table_path, write_field_key, stored_value)
        return f'{item["key"]}.{spec["label"]} = {rendered}'

    current = float(spec['value'])
    next_value = normalize(current + delta, spec['kind'])

    stored_value = str(next_value) if spec.get('storage') == 'string' else next_value
    _write_config_value(aseco, item, file_path, table_path, write_field_key, stored_value)
    return f'{item["key"]}.{field_key} = {_display_value(next_value)}'


def _config_app_counts(aseco: 'Aseco', app_key: str) -> tuple[int, int]:
    items = _config_items_for_app(aseco, app_key)
    enabled = 0
    for item in items:
        if _config_item_state(aseco, item) in {'enabled', 'config'}:
            enabled += 1
    return enabled, len(items)


def _ui_config_group_for(item_key: str) -> str:
    if any(item_key == key or item_key.startswith(key + '.') for key in _SCORETABLE_WIDGETS):
        return 'Scoretable Lists'
    for group in UI_GROUP_ORDER:
        for prefix in UI_GROUP_PREFIXES.get(group, ()):
            if item_key == prefix or item_key.startswith(prefix + '.'):
                return group
    return 'Misc'


def _ui_display_label(item: dict[str, Any]) -> str:
    if item.get('display_label'):
        return item['display_label']
    key = str(item.get('key') or '').strip()
    parts = tuple(part for part in key.split('.') if part)
    if len(parts) <= 1:
        return str(item.get('label') or key)
    return _format_config_label(parts[1:])


def _config_app_spec(aseco: 'Aseco', app_key: str) -> dict[str, str]:
    return _discover_config_apps(aseco).get(app_key, {
        'label': app_key.replace('_', ' ').title(),
        'save_mode': 'restart',
        'description': 'App settings from app_defaults.toml',
    })


def _find_config_item(aseco: 'Aseco', app_key: str, item_key: str) -> dict[str, Any] | None:
    return next((entry for entry in _config_items_for_app(aseco, app_key) if entry['key'] == item_key), None)


def _can_reload_app(aseco: 'Aseco', app_key: str) -> bool:
    return app_key in RELOADABLE_APPS and _can_configure_app(aseco, app_key)


def _is_panel_position_item(app_key: str, item_key: str | None) -> bool:
    return ((app_key == 'ui' and item_key == _YOUR_STATS_ITEM)
            or (app_key == 'platform_ui' and item_key in {f'panels.{name}' for name in LEGACY_PANEL_TYPES.values()}))


def _config_save_mode(aseco: 'Aseco', app_key: str, item_key: str | None = None) -> str:
    if _is_panel_position_item(app_key, item_key):
        ui = aseco.get_service('ui/uistyle')
        return 'reload' if callable(getattr(ui, 'reload_panel_positions', None)) else 'restart'
    return 'reload' if _can_reload_app(aseco, app_key) else 'restart'


async def _reload_app_runtime(aseco: 'Aseco', app_key: str, item_key: str | None = None) -> bool:
    if _is_panel_position_item(app_key, item_key):
        reload_positions = getattr(aseco.get_service('ui/uistyle'), 'reload_panel_positions', None)
        if not callable(reload_positions):
            return False
        await reload_positions()
        return True
    if not _can_reload_app(aseco, app_key):
        return False
    from pyxaseco.management.reload import reload_app
    return await reload_app(aseco, app_key, item_key)


@_guard_config_change
async def _apply_config_toggle(
    aseco: 'Aseco',
    app_key: str,
    item_key: str,
    enabled: bool,
    *,
    scope=None,
) -> str:
    item = _find_config_item(aseco, app_key, item_key)
    if not item:
        return _unknown_apps_target(item_key)

    if item['key'] == 'stalker':
        file_path = _root_dir(aseco) / item['file']
        for path in tuple(item.get('linked_enabled_paths') or ()):
            update_toml_table_scalar(file_path, tuple(path), 'enabled', enabled)
        _mark_config_pending(aseco, app_key)
        return _restart_required_message(f'{app_key}.stalker.enabled = {str(enabled).lower()}')

    info = _config_item_target_info(aseco, item, scope=scope)
    write_path = _config_field_write_path(item, info, 'enabled')
    _write_config_value(aseco, item, info['file_path'], write_path, 'enabled', enabled)

    if _config_save_mode(aseco, app_key, item_key) == 'reload' and await _reload_app_runtime(aseco, app_key, item_key):
        return _reload_done_message(f'{app_key}.{item_key}.enabled = {str(enabled).lower()}')
    _mark_config_pending(aseco, app_key)
    return _restart_required_message(f'{app_key}.{item_key}.enabled = {str(enabled).lower()}')


