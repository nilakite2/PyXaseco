from __future__ import annotations

import importlib
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyxaseco.helpers import display_manialink_multi
from pyxaseco.models import Gameinfo
from pyxaseco.toml_tools import move_loadout_entry, read_toml, update_toml_table_scalar

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


logger = logging.getLogger(__name__)


MANAGEABLE_STANDALONE_APPS: dict[str, str] = {
    'flexitime': 'FlexiTime',
    'bestcps': 'Best CPs',
    'bestsecs': 'Best Secs',
    'bestruns': 'Best Runs',
    'bestfinishes': 'Best Finishes',
    'best_cp_times': 'Best CP Times',
    'records_rpg': 'RPG Records',
    'records_trial': 'Trial Records',
    'jfreu': 'JFreu',
    'ztrack': 'ZTrack',
}

CONFIG_APPS: dict[str, dict[str, str]] = {
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
}

CONFIG_APP_DISCOVERY_EXCLUDE = {
    'social_chat',
    'admin',
    'platform_core',
    'jukebox',
}

PROTECTED_STANDALONE_APPS = {
    'admin',
    'apps_manager',
    'discord',
    'help',
    'jukebox',
    'platform_core',
    'platform_ui',
    'players',
    'records_dedimania',
    'records_local',
    'server_info',
    'social_chat',
    'tmx',
    'ui',
    'voting',
}

RELOADABLE_APPS = {
    'ui',
    'bestcps',
    'bestsecs',
    'bestruns',
    'bestfinishes',
    'best_cp_times',
}

_APPS_USAGE = (
    'Usage: /admin apps <list|status [name]|config <app>|reload <app>|enable <app>|disable <app>|'
    ' add <app>|remove <app>|rem <app>|fremove <app> confirm|frem <app> confirm>'
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


UI_CONFIG_ITEMS: list[dict[str, Any]] = [
    _ui_item('welcome_window', 'Welcome Window'),
    _ui_item('menu', 'Menu'),
    _ui_item('challenge_widget', 'Challenge Widget'),
    _ui_item('checkpointcount_widget', 'Checkpoint Counter'),
    _ui_item('join_leave_info', 'Join/Leave Info'),
    _ui_item('donation_widget', 'Donation Widget'),
    _ui_item('clock_widget', 'Clock Widget'),
    _ui_item('banner', 'Banner'),
    _ui_item('allbutton', 'AllButton'),
    _ui_item(
        'karma',
        'Karma',
        widget_table_path=('ui', 'karma', 'karma_widget'),
    ),
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
    _ui_item('favorite_widget', 'Favorite Widget'),
    _ui_item('next_environment_widget', 'Next Environment Widget'),
    _ui_item('next_gamemode_widget', 'Next Gamemode Widget'),
    _ui_item('dedimania_records', 'Dedimania Records'),
    _ui_item('local_records', 'Local Records'),
    _ui_item('live_rankings', 'Live Rankings'),
    _ui_item('round_score', 'Round Score'),
    _ui_item('winning_payout', 'Winning Payout'),
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
    _ui_item('scoretable_lists.top_active_players', 'Scoretable: Top Active Players'),
    _ui_item('scoretable_lists.top_winning_payouts', 'Scoretable: Top Winning Payouts'),
    _ui_item('scoretable_lists.top_betwins', 'Scoretable: Top BetWins'),
    _ui_item('scoretable_lists.top_roundscore', 'Scoretable: Top Roundscore'),
]

UI_DISCOVERY_EXCLUDE_PREFIXES: tuple[tuple[str, ...], ...] = (
    ('ui', 'show_progress_indicator'),
    ('ui', 'links'),
    ('ui', 'style'),
    ('ui', 'images'),
    ('ui', 'menu'),
    ('ui', 'features', 'songlist'),
    ('ui', 'welcome_window', 'image'),
    ('ui', 'challenge_widget', 'icons'),
    ('ui', 'challenge_widget', 'title'),
    ('ui', 'karma', 'images'),
    ('ui', 'karma', 'widget_styles'),
)

STATIC_CONFIG_ITEMS: dict[str, list[dict[str, Any]]] = {
    'ui': UI_CONFIG_ITEMS,
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
        'next_environment_widget',
        'next_gamemode_widget',
        'tmexchange_widget',
        'toplist_widget',
    ),
    'Record Panels': (
        'dedimania_records',
        'local_records',
        'live_rankings',
        'round_score',
        'winning_payout',
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
        'donation_widget',
        'eyepiece_widget',
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
    async def handle_action(self, aseco: 'Aseco', admin, answer: list[Any]) -> bool:
        return await handle_apps_action(aseco, admin, answer)

    async def handle_command(self, aseco: 'Aseco', login: str, admin, args: list[str]) -> bool:
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


def _discover_config_apps(aseco: 'Aseco') -> dict[str, dict[str, str]]:
    discovered = dict(CONFIG_APPS)
    apps_dir = _apps_dir(aseco)
    if not apps_dir.exists():
        return discovered
    for path in sorted(apps_dir.glob('*/app_defaults.toml')):
        app_key = path.parent.name
        if app_key == '00removed' or app_key in CONFIG_APP_DISCOVERY_EXCLUDE:
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

    file_path = _app_defaults_path_for_app(aseco, app_key)
    if file_path.exists():
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


def _apps_action_map(player) -> dict[int, tuple[Any, ...]]:
    action_map = getattr(player, 'apps_action_map', None)
    if not isinstance(action_map, dict):
        action_map = {}
        setattr(player, 'apps_action_map', action_map)
    return action_map


def _reset_apps_action_map(player) -> None:
    setattr(player, 'apps_action_map', {})
    setattr(player, 'apps_action_seed', 12000)


def _register_apps_action(player, payload: tuple[Any, ...]) -> int:
    seed = int(getattr(player, 'apps_action_seed', 12000))
    action_id = seed + 1
    setattr(player, 'apps_action_seed', action_id)
    _apps_action_map(player)[action_id] = payload
    return action_id


def _action_cell(player, label: str, payload: tuple[Any, ...] | None):
    return [label, _register_apps_action(player, payload)] if payload else label


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
    try:
        from apps.ui.config import _state as ui_state
        if bool(getattr(ui_state, 'challenge_show_next', False)):
            return True
    except Exception:
        pass
    return getattr(getattr(aseco.server, 'gameinfo', None), 'state', None) == Gameinfo.SCOR


def _current_ui_runtime_mode_key(aseco: 'Aseco', base_table: dict[str, Any]) -> str | None:
    gamemode_table = base_table.get('gamemode')
    if not isinstance(gamemode_table, dict):
        return None
    if _ui_showing_score(aseco) and isinstance(gamemode_table.get('score'), dict):
        return 'score'
    return _current_ui_mode_key(aseco)


def _current_ui_phase_key(aseco: 'Aseco', mode_table: dict[str, Any]) -> str | None:
    if not isinstance(mode_table, dict):
        return None
    if not any(isinstance(mode_table.get(name), dict) for name in ('race', 'warmup')):
        return None
    return 'warmup' if bool(getattr(aseco, 'warmup_phase', False)) and isinstance(mode_table.get('warmup'), dict) else 'race'


def _config_item_target_info_from_data(
    aseco: 'Aseco',
    item: dict[str, Any],
    data: dict[str, Any],
    *,
    file_path: Path | None = None,
) -> dict[str, Any]:
    if file_path is None:
        file_path = _root_dir(aseco) / item['file']
    base_path = tuple(item['table_path'])
    base_table = _read_nested(data, base_path)
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

    effective = dict(base_table)
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
            mode_key = _current_ui_runtime_mode_key(aseco, widget_root)
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
        mode_key = _current_ui_runtime_mode_key(aseco, base_table)
        mode_table = base_table['gamemode'].get(mode_key) if mode_key else None
        if isinstance(mode_table, dict):
            effective.update(mode_table)
            mode_path = base_path + ('gamemode', mode_key)
            write_path = mode_path
            phase_key = _current_ui_phase_key(aseco, mode_table)
            if phase_key and isinstance(mode_table.get(phase_key), dict):
                phase_table = mode_table[phase_key]
                effective.update(phase_table)
                phase_path = mode_path + (phase_key,)
                write_path = phase_path
    elif _is_ui_item(item):
        direct_phase_key = 'score' if _ui_showing_score(aseco) else 'race'
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
    }


def _config_item_target_info(aseco: 'Aseco', item: dict[str, Any]) -> dict[str, Any]:
    file_path = _root_dir(aseco) / item['file']
    data = read_toml(file_path)
    return _config_item_target_info_from_data(aseco, item, data, file_path=file_path)


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
        return float(parts[0]), float(parts[1])
    except Exception:
        return None


def _config_item_summary_from_info(aseco: 'Aseco', item: dict[str, Any], info: dict[str, Any]) -> str:
    table = info['effective_table']
    if not isinstance(table, dict):
        return '-'

    if item['key'] == 'menu':
        pos = str(table.get('position', '')).strip()
        size = str(table.get('size', '')).strip()
        parts = []
        if pos:
            parts.append(f'pos={pos}')
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
                parts.append(f"x={widget_table['pos_x']}")
            if 'pos_y' in widget_table:
                parts.append(f"y={widget_table['pos_y']}")
        if info.get('mode_key'):
            parts.insert(0, f"mode={info['mode_key']}")
        return ', '.join(parts[:5])

    parts: list[str] = []
    if 'enabled' in table:
        parts.append(f"enabled={_display_value(_coerce_bool(table.get('enabled')))}")
    if 'pos_x' in table:
        parts.append(f"x={table['pos_x']}")
    if 'pos_y' in table:
        parts.append(f"y={table['pos_y']}")
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

    pair_pos = _parse_pair(table.get('position')) if item['key'] == 'menu' else None
    pair_size = _parse_pair(table.get('size')) if item['key'] == 'menu' else None
    if pair_pos is not None:
        fields.append({'field_key': 'position_x', 'label': 'pos_x', 'kind': 'float', 'value': pair_pos[0], 'step_small': 0.1, 'step_big': 10.0})
        fields.append({'field_key': 'position_y', 'label': 'pos_y', 'kind': 'float', 'value': pair_pos[1], 'step_small': 0.1, 'step_big': 10.0})
        handled_fields.update({'position_x', 'position_y', 'position'})
    if pair_size is not None:
        fields.append({'field_key': 'size_w', 'label': 'width', 'kind': 'float', 'value': pair_size[0], 'step_small': 0.1, 'step_big': 10.0})
        fields.append({'field_key': 'size_h', 'label': 'height', 'kind': 'float', 'value': pair_size[1], 'step_small': 0.1, 'step_big': 10.0})
        handled_fields.update({'size_w', 'size_h', 'size'})

    add_numeric('main_pos_x', 'main_pos_x', 0.1, 10.0, table.get('main_pos_x'))
    add_numeric('main_pos_y', 'main_pos_y', 0.1, 10.0, table.get('main_pos_y'))
    add_numeric('submenu_pos_x', 'submenu_pos_x', 0.1, 10.0, table.get('submenu_pos_x'))
    add_numeric('submenu_pos_y', 'submenu_pos_y', 0.1, 10.0, table.get('submenu_pos_y'))
    add_numeric('entries', 'entries', 1, 10, table.get('entries'))
    add_numeric('topcount', 'topcount', 1, 10, table.get('topcount'))
    add_numeric('pos_x', 'pos_x', 0.1, 10.0, table.get('pos_x'))
    add_numeric('pos_y', 'pos_y', 0.1, 10.0, table.get('pos_y'))
    add_numeric('width', 'width', 0.1, 10.0, table.get('width'))
    add_numeric('height', 'height', 0.1, 10.0, table.get('height'))
    add_numeric('row_height', 'row_height', 0.05, 0.25, table.get('row_height'))
    add_numeric('number', '# entries', 1, 10, table.get('number'))
    add_numeric('button_pos_x', 'button_pos_x', 0.1, 10.0, table.get('button_pos_x'))
    add_numeric('button_pos_y', 'button_pos_y', 0.1, 10.0, table.get('button_pos_y'))
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
        if isinstance(value, str) and value.strip().lower() in {'true', 'false', 'on', 'off', 'yes', 'no', '1', '0'}:
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


def _editable_fields(aseco: 'Aseco', item: dict[str, Any]) -> list[dict[str, Any]]:
    return _editable_fields_from_info(aseco, item, _config_item_target_info(aseco, item))


def _update_config_field(aseco: 'Aseco', item: dict[str, Any], field_key: str, delta: float) -> str:
    info = _config_item_target_info(aseco, item)
    table_path = _config_field_write_path(item, info, field_key)
    file_path = info['file_path']
    table = _read_nested(read_toml(file_path), table_path)
    if not isinstance(table, dict):
        return f'{item["key"]}.{field_key}'

    def normalize(value: float, kind: str) -> int | float:
        if kind == 'int':
            return int(round(value))
        return round(float(value), 2)

    editable = {entry['field_key']: entry for entry in _editable_fields(aseco, item)}
    spec = editable.get(field_key)
    if not spec:
        return f'{item["key"]}.{field_key}'

    write_field_key = 'enabled' if field_key == 'widget_enabled' else field_key

    if spec['kind'] == 'bool':
        next_value = True if delta >= 0 else False
        stored_value: Any = str(next_value).lower() if spec.get('storage') == 'string' else next_value
        update_toml_table_scalar(file_path, table_path, write_field_key, stored_value)
        return f'{item["key"]}.{field_key} = {_display_value(next_value)}'

    current = float(spec['value'])
    next_value = normalize(current + delta, spec['kind'])

    if field_key in {'position_x', 'position_y'}:
        pair = _parse_pair(table.get('position')) or (0.0, 0.0)
        x, y = pair
        if field_key == 'position_x':
            x = float(next_value)
        else:
            y = float(next_value)
        update_toml_table_scalar(file_path, table_path, 'position', f'{_display_value(x)} {_display_value(y)}')
    elif field_key in {'size_w', 'size_h'}:
        pair = _parse_pair(table.get('size')) or (0.0, 0.0)
        w, h = pair
        if field_key == 'size_w':
            w = float(next_value)
        else:
            h = float(next_value)
        update_toml_table_scalar(file_path, table_path, 'size', f'{_display_value(w)} {_display_value(h)}')
    else:
        stored_value: Any = str(next_value) if spec.get('storage') == 'string' else next_value
        update_toml_table_scalar(file_path, table_path, write_field_key, stored_value)

    return f'{item["key"]}.{field_key} = {_display_value(next_value)}'


def _config_app_counts(aseco: 'Aseco', app_key: str) -> tuple[int, int]:
    items = _config_items_for_app(aseco, app_key)
    enabled = 0
    for item in items:
        if _config_item_state(aseco, item) in {'enabled', 'config'}:
            enabled += 1
    return enabled, len(items)


def _autosize_widths(
    table_header: list[str],
    entries: list[list[Any]],
    *,
    min_total: float = 1.08,
    max_total: float = 1.38,
) -> list[float]:
    if not table_header:
        return [min_total]

    col_count = len(table_header)
    max_lens = [max(4, len(str(head or ''))) for head in table_header]
    for row in entries:
        for idx in range(min(len(row), col_count)):
            cell = row[idx]
            text = cell[0] if isinstance(cell, list) else cell
            max_lens[idx] = max(max_lens[idx], len(str(text or '')))

    col_widths: list[float] = []
    for idx, length in enumerate(max_lens):
        if idx >= col_count - 2:
            width = 0.12 + min(length, 12) * 0.014
        elif idx == 0:
            width = 0.18 + min(length, 48) * 0.020
        else:
            width = 0.12 + min(length, 40) * 0.015
        col_widths.append(max(0.12, min(width, 1.10)))

    total = sum(col_widths)
    if total < min_total:
        factor = min_total / total if total else 1.0
        col_widths = [width * factor for width in col_widths]
        total = sum(col_widths)
    if total > max_total:
        factor = max_total / total
        col_widths = [width * factor for width in col_widths]
        total = sum(col_widths)

    return [max(min_total, min(total, max_total))] + [round(width, 3) for width in col_widths]


def _show_apps_window(
    aseco: 'Aseco',
    admin,
    header: str,
    icon: list[str | float],
    table_header: list[str],
    entries: list[list[Any]],
    widths: list[float] | None = None,
) -> None:
    pages = []
    page = [table_header]
    lines = 0
    for row in entries:
        page.append(row)
        lines += 1
        if lines >= 14:
            pages.append(page)
            page = [table_header]
            lines = 0
    if len(page) > 1:
        pages.append(page)

    meta_widths = widths or _autosize_widths(table_header, entries)
    admin.msgs = [[1, header, meta_widths, icon]]
    admin.msgs.extend(pages or [[table_header]])
    display_manialink_multi(aseco, admin)


def _ui_config_group_for(item_key: str) -> str:
    if item_key.startswith('scoretable_lists.'):
        return 'Scoretable Lists'
    for group in UI_GROUP_ORDER:
        for prefix in UI_GROUP_PREFIXES.get(group, ()):
            if item_key == prefix or item_key.startswith(prefix + '.'):
                return group
    return 'Misc'


def _ui_group_index(group: str) -> int:
    try:
        return UI_GROUP_ORDER.index(group)
    except ValueError:
        return len(UI_GROUP_ORDER)


def _ui_display_label(item: dict[str, Any]) -> str:
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
    if app_key not in RELOADABLE_APPS:
        return False
    if app_key in MANAGEABLE_STANDALONE_APPS:
        return _standalone_status(aseco, app_key) == 'enabled'
    state = _standalone_loadout_state(aseco, app_key)
    return state != 'disabled'


def _config_save_mode(aseco: 'Aseco', app_key: str) -> str:
    return 'reload' if _can_reload_app(aseco, app_key) else 'restart'


async def _reload_app_runtime(aseco: 'Aseco', app_key: str) -> bool:
    if not _can_reload_app(aseco, app_key):
        return False
    from pyxaseco.app_config import clear_app_defaults_cache as clear_app_catalog_cache
    from pyxaseco.settings_loader import clear_app_defaults_cache as clear_settings_defaults_cache

    clear_app_catalog_cache(getattr(aseco, '_base_dir', None))
    clear_settings_defaults_cache()

    try:
        app_module = importlib.import_module(f'apps.{app_key}.app')
    except Exception:
        logger.warning('[AppsManager] Could not import reload module for %s', app_key, exc_info=True)
        return False
    reload_fn = getattr(app_module, 'reload_runtime', None)
    if not callable(reload_fn):
        return False
    result = reload_fn(aseco)
    if hasattr(result, '__await__'):
        await result
    return True


def _show_apps_manager_window(aseco: 'Aseco', admin) -> None:
    _reset_apps_action_map(admin)
    rows: list[list[Any]] = []

    rows.append(['{#highlite}Configurable App Homes', '', '', '', '', ''])
    config_apps = list(_discover_config_apps(aseco).items())
    config_apps.sort(key=lambda pair: (0 if _standalone_loadout_state(aseco, pair[0]) != 'disabled' else 1, pair[1]['label'].lower()))
    for app_key, spec in config_apps:
        loadout_state = _standalone_loadout_state(aseco, app_key)
        if loadout_state == 'disabled':
            state_text = 'disabled'
        else:
            enabled, total = _config_app_counts(aseco, app_key)
            state_text = f'{enabled}/{total} on'
        rows.append([
            spec['label'],
            'Config',
            state_text,
            _action_cell(admin, 'Config', ('open_config', app_key)),
            '',
            _action_cell(admin, 'Reload', ('reload_app', app_key)) if _can_reload_app(aseco, app_key) else '',
        ])

    while rows and (len(rows) % 14) != 0:
        rows.append(['', '', '', '', '', ''])

    rows.append(['{#highlite}Standalone Optional Apps', '', '', '', '', ''])
    standalone_names = list(_standalone_app_names())
    standalone_names.sort(key=lambda name: (0 if _standalone_loadout_state(aseco, name) != 'disabled' else 1, MANAGEABLE_STANDALONE_APPS.get(name, name).lower()))
    for app_name in standalone_names:
        label = MANAGEABLE_STANDALONE_APPS.get(app_name, app_name)
        status = _standalone_status(aseco, app_name)
        primary = ''
        secondary = ''
        if status == 'enabled':
            primary = _action_cell(admin, 'Disable', ('toggle_app', 'disable', app_name))
            secondary = _action_cell(admin, 'Remove', ('archive_app', app_name))
        elif status == 'disabled':
            primary = _action_cell(admin, 'Enable', ('toggle_app', 'enable', app_name))
            secondary = _action_cell(admin, 'Remove', ('archive_app', app_name))
        elif status == 'removed':
            primary = _action_cell(admin, 'Add', ('restore_app', app_name))
        rows.append([
            label,
            'App',
            status,
            primary,
            secondary,
            _action_cell(admin, 'Reload', ('reload_app', app_name)) if _can_reload_app(aseco, app_name) else '',
        ])

    _show_apps_window(
        aseco,
        admin,
        'Apps Manager',
        ['Icons128x128_1', 'Buddies'],
        ['Name', 'Type', 'State', 'Primary', 'Secondary', 'Reload'],
        rows,
    )


def _show_app_config_window(aseco: 'Aseco', admin, app_key: str) -> None:
    spec = _discover_config_apps(aseco).get(app_key)
    if not spec:
        return

    _reset_apps_action_map(admin)
    rows: list[list[Any]] = []
    last_group = ''
    items = _config_items_for_app(aseco, app_key)
    file_cache: dict[Path, dict[str, Any]] = {}
    if app_key == 'ui':
        items = sorted(items, key=lambda item: (_ui_group_index(_ui_config_group_for(item['key'])), _ui_config_group_for(item['key']), item['label']))
    for item in items:
        if app_key == 'ui':
            group = _ui_config_group_for(item['key'])
            if group != last_group:
                if rows:
                    while (len(rows) % 14) != 0:
                        rows.append(['', '', '', '', '', ''])
                rows.append([f'{{#highlite}}{group}', '', '', '', '', ''])
                last_group = group
        file_path = _root_dir(aseco) / item['file']
        data = file_cache.setdefault(file_path, read_toml(file_path))
        info = _config_item_target_info_from_data(aseco, item, data, file_path=file_path)
        state = _config_item_state_from_info(item, info)
        summary = _config_item_summary_from_info(aseco, item, info)
        editable = _editable_fields_from_info(aseco, item, info)
        rows.append([
            _ui_display_label(item) if app_key == 'ui' else item['label'],
            _config_item_state_text(state),
            summary,
            _action_cell(admin, 'Edit', ('open_edit', app_key, item['key'])) if editable else '',
            _action_cell(admin, 'Enable', ('toggle_config', app_key, item['key'], True)) if state not in {'enabled', 'config', 'missing'} else '',
            _action_cell(admin, 'Disable', ('toggle_config', app_key, item['key'], False)) if state not in {'disabled', 'config', 'missing'} else '',
        ])

    save_note = 'Saved and reloaded' if _config_save_mode(aseco, app_key) == 'reload' else 'Saved. Restart required'
    widths = None
    icon = ['Icons128x128_1', 'ProfileAdvanced']
    if app_key == 'ui':
        widths = [1.38, 0.34, 0.16, 0.40, 0.12, 0.18, 0.18]
        icon = ['Icons128x128_1', 'Buddies']
    _show_apps_window(
        aseco,
        admin,
        f'{spec["label"]} Config ({save_note})',
        icon,
        ['Item', 'State', 'Summary', 'Edit', 'Enable', 'Disable'],
        rows,
        widths=widths,
    )


def _show_item_edit_window(aseco: 'Aseco', admin, app_key: str, item_key: str) -> None:
    item = next((entry for entry in _config_items_for_app(aseco, app_key) if entry['key'] == item_key), None)
    if not item:
        return

    _reset_apps_action_map(admin)
    fields = _editable_fields(aseco, item)
    rows: list[list[Any]] = [[
        '{#highlite}Navigation',
        '',
        '',
        '',
        '',
        '',
        '',
        _action_cell(admin, 'Back', ('open_config', app_key)),
    ]]

    for field in fields:
        label = str(field.get('label') or field.get('field_key') or '')
        value = _display_value(field.get('value'))
        if field.get('kind') == 'bool':
            rows.append([
                label,
                value,
                '',
                '',
                _action_cell(admin, 'Off', ('adjust_field', app_key, item_key, field['field_key'], -1.0)),
                _action_cell(admin, 'On', ('adjust_field', app_key, item_key, field['field_key'], 1.0)),
                '',
                '',
            ])
        else:
            neg_big = _display_value(-float(field['step_big']))
            neg_def = _display_value(-1.0)
            neg_small = _display_value(-float(field['step_small']))
            pos_small = _display_value(float(field['step_small']))
            pos_def = _display_value(1.0)
            pos_big = _display_value(float(field['step_big']))
            rows.append([
                label,
                value,
                _action_cell(admin, neg_big, ('adjust_field', app_key, item_key, field['field_key'], -float(field['step_big']))),
                _action_cell(admin, neg_def, ('adjust_field', app_key, item_key, field['field_key'], -1.0)),
                _action_cell(admin, neg_small, ('adjust_field', app_key, item_key, field['field_key'], -float(field['step_small']))),
                _action_cell(admin, f'+{pos_small}', ('adjust_field', app_key, item_key, field['field_key'], float(field['step_small']))),
                _action_cell(admin, f'+{pos_def}', ('adjust_field', app_key, item_key, field['field_key'], 1.0)),
                _action_cell(admin, f'+{pos_big}', ('adjust_field', app_key, item_key, field['field_key'], float(field['step_big']))),
            ])

    _show_apps_window(
        aseco,
        admin,
        f'{_config_app_spec(aseco, app_key)["label"]}: {item["label"]}',
        ['Icons128x128_1', 'ProfileAdvanced'],
        ['Field', 'Value', '-Big', '-Def', '-Small', '+Small', '+Def', '+Big'],
        rows,
        widths=[1.34, 0.24, 0.18, 0.14, 0.14, 0.14, 0.14, 0.18, 0.18],
    )


async def _apply_config_toggle(
    aseco: 'Aseco',
    app_key: str,
    item_key: str,
    enabled: bool,
) -> str:
    item = _find_config_item(aseco, app_key, item_key)
    if not item:
        return _unknown_apps_target(item_key)

    info = _config_item_target_info(aseco, item)
    write_path = _config_field_write_path(item, info, 'enabled')
    update_toml_table_scalar(info['file_path'], write_path, 'enabled', enabled)

    if _config_save_mode(aseco, app_key) == 'reload' and await _reload_app_runtime(aseco, app_key):
        return _reload_done_message(f'{app_key}.{item_key}.enabled = {str(enabled).lower()}')
    return _restart_required_message(f'{app_key}.{item_key}.enabled = {str(enabled).lower()}')


async def handle_apps_action(aseco: 'Aseco', admin, answer: list[Any]) -> bool:
    if not answer or len(answer) < 3:
        return False
    action_id = int(answer[2])
    payload = _apps_action_map(admin).get(int(action_id))
    if not payload:
        return False

    login = getattr(admin, 'login', '')
    if not _is_masteradmin(aseco, admin, login):
        await _reply(aseco, login, '{#server}> {#error}Only MasterAdmins may use the apps manager.')
        return True

    kind = payload[0]

    if kind == 'open_config':
        _show_app_config_window(aseco, admin, str(payload[1]))
        return True

    if kind == 'open_edit':
        _show_item_edit_window(aseco, admin, str(payload[1]), str(payload[2]))
        return True

    if kind == 'reload_app':
        app_key = str(payload[1])
        if await _reload_app_runtime(aseco, app_key):
            await _reply(aseco, login, _reload_done_message(f'app/{app_key}'))
        else:
            await _reply(aseco, login, _restart_required_message(f'app/{app_key}'))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'toggle_app':
        action, name = str(payload[1]), str(payload[2])
        move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', action == 'enable')
        await _reply(aseco, login, _restart_required_message(f"app/{name} {action}d in apps.toml"))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'archive_app':
        name = str(payload[1])
        app_dir, _archived = _standalone_paths(aseco, name)
        if app_dir.exists():
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', False)
            shutil.move(str(app_dir), str(_archive_destination(aseco, name)))
            await _reply(aseco, login, _restart_required_message(f'app/{name} moved to apps/00removed and disabled'))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'restore_app':
        name = str(payload[1])
        app_dir, archived = _standalone_paths(aseco, name)
        if archived is not None:
            _apps_dir(aseco).mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived), str(app_dir))
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', True)
            await _reply(aseco, login, _restart_required_message(f'app/{name} restored from apps/00removed and enabled'))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'toggle_config':
        app_key, item_key, enabled = str(payload[1]), str(payload[2]), bool(payload[3])
        msg = await _apply_config_toggle(aseco, app_key, item_key, enabled)
        await _reply(aseco, login, msg)
        _show_app_config_window(aseco, admin, app_key)
        return True

    if kind == 'adjust_field':
        app_key = str(payload[1])
        item_key = str(payload[2])
        field_key = str(payload[3])
        delta = float(payload[4])
        item = _find_config_item(aseco, app_key, item_key)
        if not item:
            await _reply(aseco, login, _unknown_apps_target(item_key))
            return True

        action_text = _update_config_field(aseco, item, field_key, delta)
        if _config_save_mode(aseco, app_key) == 'reload' and await _reload_app_runtime(aseco, app_key):
            await _reply(aseco, login, _reload_done_message(action_text))
        else:
            await _reply(aseco, login, _restart_required_message(action_text))
        _show_item_edit_window(aseco, admin, app_key, item_key)
        return True

    return False


async def _handle_apps_command(aseco: 'Aseco', login: str, admin, args: list[str]) -> None:
    if not _is_masteradmin(aseco, admin, login):
        await _reply(aseco, login, '{#server}> {#error}Only MasterAdmins may change app and feature states.')
        return

    if not args or str(args[0]).strip().lower() == 'list':
        _show_apps_manager_window(aseco, admin)
        return

    action = str(args[0]).strip().lower()
    name = _normalize_app_name(args[1]) if len(args) > 1 else ''
    config_apps = _discover_config_apps(aseco)

    if action == 'config':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            _show_app_config_window(aseco, admin, name)
            return
        owner = _config_item_owner(aseco, name)
        if owner:
            await _reply(aseco, login, _unknown_apps_target(name))
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action == 'reload':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if await _reload_app_runtime(aseco, name):
            await _reply(aseco, login, _reload_done_message(f'app/{name}'))
            return
        if name in config_apps or _is_manageable_standalone_app(aseco, name):
            await _reply(aseco, login, _restart_required_message(f'app/{name}'))
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action == 'status':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            state = 'disabled' if _standalone_loadout_state(aseco, name) == 'disabled' else None
            if state == 'disabled':
                await _reply(aseco, login, f'{{#server}}> {{#message}}{config_apps[name]["label"]}: {{#highlite}}disabled')
            else:
                enabled_count, total = _config_app_counts(aseco, name)
                await _reply(aseco, login, f'{{#server}}> {{#message}}{config_apps[name]["label"]}: {{#highlite}}{enabled_count}/{total}{{#message}} items enabled.')
            return
        if _is_manageable_standalone_app(aseco, name):
            await _reply(aseco, login, f'{{#server}}> {{#message}}app/{name}: {{#highlite}}{_standalone_status(aseco, name)}')
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action in {'enable', 'disable'}:
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}Use {#highlite}/admin apps config ' + name + '{#error} for merged features and UI-owned items.')
            return
        if _is_manageable_standalone_app(aseco, name):
            enabled = action == 'enable'
            app_dir, archived = _standalone_paths(aseco, name)
            if enabled and not app_dir.exists() and archived is not None:
                await _reply(aseco, login, '{#server}> {#error}App is archived in {#highlite}apps/00removed{#error}; use {#highlite}/admin apps add ' + name + '{#error} to restore it first.')
                return
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', enabled)
            await _reply(aseco, login, _restart_required_message(f"app/{name} {'enabled' if enabled else 'disabled'} in apps.toml"))
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action == 'add':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}' + name + ' is a core config app and cannot be added or removed through /admin apps.')
            return
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Protected core apps are not managed through /admin apps.')
            return
        app_dir, archived = _standalone_paths(aseco, name)
        if app_dir.exists():
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', True)
            await _reply(aseco, login, _restart_required_message(f'app/{name} enabled in apps.toml'))
            return
        if archived is not None:
            _apps_dir(aseco).mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived), str(app_dir))
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', True)
            await _reply(aseco, login, _restart_required_message(f'app/{name} restored from apps/00removed and enabled'))
            return
        await _reply(aseco, login, '{#server}> {#error}No install source found for {#highlite}' + name + '{#error}. Expected either {#highlite}apps/' + name + '{#error} or {#highlite}apps/00removed/' + name + '{#error}.')
        return

    if action in {'remove', 'rem'}:
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}' + name + ' is a core config app and cannot be removed through /admin apps.')
            return
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Protected core apps may not be removed through /admin apps.')
            return
        app_dir, archived = _standalone_paths(aseco, name)
        if archived is not None and not app_dir.exists():
            await _reply(aseco, login, '{#server}> {#message}App {#highlite}' + name + '{#message} is already archived in {#highlite}apps/00removed{#message}.')
            return
        if not app_dir.exists():
            await _reply(aseco, login, _unknown_apps_target(name))
            return
        move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', False)
        shutil.move(str(app_dir), str(_archive_destination(aseco, name)))
        await _reply(aseco, login, _restart_required_message(f'app/{name} moved to apps/00removed and disabled'))
        return

    if action in {'fremove', 'frem'}:
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if len(args) < 3 or str(args[2]).strip().lower() != 'confirm':
            await _reply(aseco, login, '{#server}> {#error}Destructive removal requires confirmation: ' f'{{#highlite}}/admin apps {action} {name} confirm')
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}' + name + ' is a core config app and cannot be physically deleted through /admin apps.')
            return
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Protected core apps may not be forcibly removed through /admin apps.')
            return
        app_dir, archived = _standalone_paths(aseco, name)
        target = app_dir if app_dir.exists() else archived
        if target is None or not target.exists():
            await _reply(aseco, login, _unknown_apps_target(name))
            return
        move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', False)
        shutil.rmtree(target)
        await _reply(aseco, login, _restart_required_message(f'app/{name} permanently removed from disk'))
        return

    await _reply_apps_usage(aseco, login)
