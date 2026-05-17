"""
pyxaseco/settings_loader.py - Unified plugin settings loader.

Reads settings.toml once at startup and provides overlay functions that each
plugin calls on top of its built-in defaults.

Sections in settings.toml:
    server        core/general settings
    localdatabase local DB settings
    dedimania     dedimania settings
    mania_karma   karma plugin settings
"""

from __future__ import annotations

import logging
import pathlib
import tomllib
from typing import Any

logger = logging.getLogger(__name__)

def _load_structured_settings(path: pathlib.Path) -> dict:
    with path.open('rb') as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


_cache: dict | None = None
_pdef_cache: dict | None = None


def _get_data(base_dir=None) -> dict:
    """Return parsed settings config, loading and caching it on first call."""
    global _cache
    if _cache is not None:
        return _cache
    candidates = []
    if base_dir:
        candidates.append(pathlib.Path(base_dir) / 'settings.toml')
    candidates.append(pathlib.Path('settings.toml'))
    for p in candidates:
        if p.exists():
            try:
                data = _load_structured_settings(p)
                total = sum(len(v) if isinstance(v, dict) else 1 for v in data.values())
                logger.info('[settings_loader] Loaded %d settings from %s', total, p)
                _cache = data
                return _cache
            except Exception as exc:
                logger.error('[settings_loader] Failed to parse %s: %s', p, exc)
    _cache = {}
    return _cache


def _set(target: Any, attr: str, value: Any, coerce=None) -> None:
    """Set attr on target only when the existing value's type matches."""
    if not hasattr(target, attr):
        return
    existing = getattr(target, attr)
    if coerce is not None:
        try:
            setattr(target, attr, coerce(value))
        except Exception as exc:
            logger.debug('[settings_loader] coerce failed for %s.%s: %s', target, attr, exc)
        return
    try:
        if isinstance(existing, bool):
            if isinstance(value, bool):
                setattr(target, attr, value)
            elif isinstance(value, str):
                setattr(target, attr, value.lower() == 'true')
        elif isinstance(existing, int):
            setattr(target, attr, int(value))
        elif isinstance(existing, float):
            setattr(target, attr, float(value))
        elif isinstance(existing, str):
            setattr(target, attr, str(value))
        else:
            setattr(target, attr, value)
    except Exception as exc:
        logger.debug('[settings_loader] type coerce failed for %s: %s', attr, exc)


def overlay_server(settings: Any, base_dir=None) -> None:
    """Overlay server section from settings.toml into a Settings object."""
    data = _get_data(base_dir)
    srv = data.get('server', {})
    if not srv:
        return

    # Accept the exact _validated_pack XML key names too.
    if 'admin_client_version' in srv and 'admin_client' not in srv:
        srv['admin_client'] = srv['admin_client_version']
    if 'player_client_version' in srv and 'player_client' not in srv:
        srv['player_client'] = srv['player_client_version']

    for key in (
        'welcome_msg_window', 'log_all_chat', 'extra_chatlog_file',
        'chatpmlog_times', 'show_recs_range', 'writetracklist_random',
        'help_explanation', 'lists_colornicks', 'lists_colortracks',
        'display_checkpoints', 'enable_cpsspec', 'auto_enable_cps',
        'auto_enable_dedicps', 'auto_admin_addip', 'afk_force_spec',
        'clickable_lists', 'show_rec_logins', 'recs_in_window',
        'rounds_in_window', 'sb_stats_panels',
        'show_tmxrec', 'show_playtime', 'show_curtrack',
        'cheater_action', 'script_timeout', 'show_min_recs',
        'show_recs_before', 'topclans_minplayers', 'global_win_multiple',
        'window_timeout',
        'default_tracklist', 'adminops_file', 'bannedips_file',
        'blacklist_file', 'guestlist_file', 'trackhist_file',
        'admin_client', 'player_client', 'default_rpoints',
        'window_style', 'admin_panel', 'donate_panel',
        'records_panel', 'vote_panel',
    ):
        if key in srv:
            _set(settings, key, srv[key])

    if 'show_recs_after' in srv:
        try:
            setattr(settings, 'show_recs_after', int(srv['show_recs_after']))
        except Exception:
            pass

    logger.debug('[settings_loader] Overlaid server settings')


def overlay_localdatabase(display_ref: list, limit_ref: list, base_dir=None) -> None:
    """Overlay localdatabase section into mutable [value] wrappers."""
    data = _get_data(base_dir)
    ldb = data.get('localdatabase', {})
    if not ldb:
        return
    if 'display' in ldb:
        v = ldb['display']
        display_ref[0] = bool(v) if isinstance(v, bool) else str(v).lower() == 'true'
    if 'limit' in ldb:
        try:
            limit_ref[0] = int(ldb['limit'])
        except (TypeError, ValueError):
            pass
    logger.debug('[settings_loader] Overlaid localdatabase settings')


def overlay_dedimania(dedi_db: dict, base_dir=None) -> None:
    """Overlay dedimania section into dedi_db dict in-place."""
    data = _get_data(base_dir)
    cfg = data.get('dedimania', {})
    if not cfg:
        return

    key_map = {
        'welcome': ('Welcome', str),
        'timeout_msg': ('TimeoutMsg', str),
        'url': ('Url', str),
        'name': ('Name', str),
        'log_news': ('LogNews', bool),
        'show_welcome': ('ShowWelcome', bool),
        'show_min_recs': ('ShowMinRecs', int),
        'show_recs_before': ('ShowRecsBefore', int),
        'show_recs_after': ('ShowRecsAfter', int),
        'show_recs_range': ('ShowRecsRange', bool),
        'display_recs': ('DisplayRecs', bool),
        'show_rec_logins': ('ShowRecLogins', bool),
        'recs_in_window': ('RecsInWindow', bool),
        'limit_recs': ('LimitRecs', int),
    }

    for config_key, (db_key, cast) in key_map.items():
        if config_key in cfg:
            try:
                if cast is bool:
                    v = cfg[config_key]
                    dedi_db[db_key] = bool(v) if isinstance(v, bool) else str(v).lower() == 'true'
                else:
                    dedi_db[db_key] = cast(cfg[config_key])
            except Exception as exc:
                logger.debug('[settings_loader] dedi %s: %s', config_key, exc)

    logger.debug('[settings_loader] Overlaid dedimania settings')


def overlay_mania_karma(cfg: Any, base_dir=None) -> None:
    """
    Overlay mania_karma section into a KarmaConfig dataclass.
    Call at the end of plugin_mania_karma._load_config.
    """
    data = _get_data(base_dir)
    mk = data.get('mania_karma', {})
    if not mk:
        return

    scalars = (
        'number_format', 'show_welcome', 'allow_public_vote', 'show_at_start',
        'show_details', 'show_votes', 'show_karma', 'require_finish',
        'remind_to_vote', 'messages_in_window', 'show_player_vote_public',
        'save_karma_also_local', 'sync_global_karma_local', 'score_mx_window',
        'karma_calculation_method', 'uptodate_check', 'uptodate_info',
        'connect_timeout', 'wait_timeout', 'keepalive_min_timeout',
        'nation',
    )
    for key in scalars:
        if key in mk:
            _set(cfg, key, mk[key])

    urls = mk.get('urls', {})
    if 'website' in urls:
        _set(cfg, 'website', urls['website'])
    if 'api_auth' in urls:
        _set(cfg, 'api_auth_url', urls['api_auth'])

    images = mk.get('images', {})
    for attr, config_key in (
        ('img_open_left', 'widget_open_left'),
        ('img_open_right', 'widget_open_right'),
        ('img_tmx_logo_normal', 'tmx_logo_normal'),
        ('img_tmx_logo_focus', 'tmx_logo_focus'),
        ('img_cup_gold', 'cup_gold'),
        ('img_cup_silver', 'cup_silver'),
        ('img_maniakarma_logo', 'maniakarma_logo'),
        ('img_progress_indicator', 'progress_indicator'),
    ):
        if config_key in images and hasattr(cfg, attr):
            _set(cfg, attr, images[config_key])

    rw = mk.get('reminder_window', {})
    if rw:
        if 'display' in rw:
            _set(cfg, 'reminder_window_display', str(rw['display']).upper())
        for state in ('race', 'score'):
            state_cfg = rw.get(state, {})
            reminder_attr = f'reminder_{state}'
            if state_cfg and hasattr(cfg, reminder_attr):
                obj = getattr(cfg, reminder_attr)
                if 'pos_x' in state_cfg:
                    try:
                        obj.pos_x = float(state_cfg['pos_x'])
                    except Exception:
                        pass
                if 'pos_y' in state_cfg:
                    try:
                        obj.pos_y = float(state_cfg['pos_y'])
                    except Exception:
                        pass

    lottery = mk.get('karma_lottery', {})
    for attr, config_key in (
        ('karma_lottery_enabled', 'enabled'),
        ('karma_lottery_min_players', 'minimum_players'),
        ('karma_lottery_coppers_win', 'coppers_win'),
        ('karma_lottery_min_srv_coppers', 'minimum_server_coppers'),
    ):
        if config_key in lottery and hasattr(cfg, attr):
            _set(cfg, attr, lottery[config_key])

    ws = mk.get('widget_styles', {})
    vb = ws.get('vote_buttons', {})
    for attr, path_keys in (
        ('bg_pos_default', ('positive', 'bgcolor_default')),
        ('bg_pos_focus', ('positive', 'bgcolor_focus')),
        ('text_pos_color', ('positive', 'text_color')),
        ('bg_neg_default', ('negative', 'bgcolor_default')),
        ('bg_neg_focus', ('negative', 'bgcolor_focus')),
        ('text_neg_color', ('negative', 'text_color')),
        ('bg_vote', ('votes', 'bgcolor_vote')),
        ('bg_disabled', ('votes', 'bgcolor_disabled')),
    ):
        node = vb.get(path_keys[0], {})
        if path_keys[1] in node:
            _set(cfg, attr, node[path_keys[1]])

    for state in ('race', 'score'):
        node = ws.get(state, {})
        for attr_suffix, config_key in (
            ('_title', 'title'),
            ('_icon_style', 'icon_style'),
            ('_icon_substyle', 'icon_substyle'),
            ('_bg_style', 'background_style'),
            ('_bg_substyle', 'background_substyle'),
            ('_title_style', 'title_style'),
            ('_title_substyle', 'title_substyle'),
        ):
            attr = state + attr_suffix
            if config_key in node and hasattr(cfg, attr):
                _set(cfg, attr, node[config_key])

    kw = mk.get('karma_widget', {})
    if kw and hasattr(cfg, 'gamemodes'):
        try:
            from pyxaseco.plugins.plugin_mania_karma import GM_TAG, WidgetGamemodeCfg
            tag_to_mode = {v: k for k, v in GM_TAG.items()}
            for tag, gm_cfg in kw.items():
                if not isinstance(gm_cfg, dict):
                    continue
                mode = tag_to_mode.get(tag)
                if mode is None:
                    continue
                existing = cfg.gamemodes.get(mode)
                if existing is None:
                    cfg.gamemodes[mode] = WidgetGamemodeCfg(
                        enabled=bool(gm_cfg.get('enabled', True)),
                        pos_x=float(gm_cfg.get('pos_x', 49.2)),
                        pos_y=float(gm_cfg.get('pos_y', 32.86)),
                    )
                else:
                    if 'enabled' in gm_cfg:
                        existing.enabled = bool(gm_cfg['enabled'])
                    if 'pos_x' in gm_cfg:
                        existing.pos_x = float(gm_cfg['pos_x'])
                    if 'pos_y' in gm_cfg:
                        existing.pos_y = float(gm_cfg['pos_y'])
        except Exception as exc:
            logger.debug('[settings_loader] karma_widget gamemodes: %s', exc)

    logger.debug('[settings_loader] Overlaid mania_karma settings')


def _get_plugin_defaults(base_dir=None) -> dict:
    """Return parsed plugin_defaults config, loading and caching on first call."""
    global _pdef_cache
    if _pdef_cache is not None:
        return _pdef_cache
    candidates = []
    if base_dir:
        candidates.append(pathlib.Path(base_dir) / 'plugin_defaults.toml')
    candidates.append(pathlib.Path('plugin_defaults.toml'))
    for p in candidates:
        if p.exists():
            try:
                data = _load_structured_settings(p)
                total = sum(len(v) if isinstance(v, dict) else 1 for v in data.values())
                logger.info('[settings_loader] Loaded %d plugin defaults from %s', total, p)
                _pdef_cache = data
                return _pdef_cache
            except Exception as exc:
                logger.error('[settings_loader] Failed to parse %s: %s', p, exc)
    _pdef_cache = {}
    return _pdef_cache


def _pdef(section: str, key: str, base_dir=None):
    """Read a single value from plugin_defaults config[section][key]."""
    return _get_plugin_defaults(base_dir).get(section, {}).get(key)


def overlay_plugin_defaults(plugin_name: str, target: Any, attr_map: dict[str, str] | None = None, base_dir=None) -> None:
    """
    Generic overlay: read plugin_defaults config[plugin_name] and set matching
    attributes on *target*.
    """
    data = _get_plugin_defaults(base_dir)
    section = data.get(plugin_name, {})
    if not section:
        return
    count = 0
    for config_key, value in section.items():
        attr = (attr_map or {}).get(config_key, config_key.upper())
        if not hasattr(target, attr):
            attr_lower = config_key.lower()
            if not hasattr(target, attr_lower):
                continue
            attr = attr_lower
        _set(target, attr, value)
        count += 1
    if count:
        logger.debug('[settings_loader] Overlaid %d defaults for %s', count, plugin_name)
