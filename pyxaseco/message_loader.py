"""
pyxaseco/message_loader.py - Unified message and color loader.

Reads messages.toml once at startup.
Each consumer overlays its own section after loading built-in defaults:

    # core/config.py - colors and sys messages:
    from pyxaseco.message_loader import overlay_colors, overlay_core, _get_data
    _get_data(base_dir)
    overlay_colors(settings, base_dir)
    overlay_core(settings, base_dir)

    # Each plugin's config loader - its own section:
    from pyxaseco.message_loader import overlay_section
    overlay_section(_rasp_messages, 'rasp_messages',
                    strip_prefix='rasp_', base_dir=aseco._base_dir)

Key naming in messages.toml:
    sys_*    core/general
    local_*  local records
    dedi_*   dedimania
    rasp_*   RASP engine
    mk_*     ManiaKarma
"""

from __future__ import annotations

import logging
import pathlib
import tomllib
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, Any] | None = None


def _load_structured_messages(path: pathlib.Path) -> dict[str, Any]:
    with path.open('rb') as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


def _get_data(base_dir=None) -> dict[str, Any]:
    """Return parsed messages config, loading and caching it on first call."""
    global _cache
    if _cache is not None:
        return _cache
    candidates: list[pathlib.Path] = []
    if base_dir:
        candidates.append(pathlib.Path(base_dir) / 'messages.toml')
    candidates.append(pathlib.Path('messages.toml'))
    for p in candidates:
        if p.exists():
            try:
                _cache = load_messages(p)
                logger.info(
                    '[message_loader] Loaded %d keys from %s',
                    sum(len(v) for v in _cache.values() if isinstance(v, dict)),
                    p,
                )
                return _cache
            except Exception as exc:
                logger.error('[message_loader] Failed to parse %s: %s', p, exc)
    _cache = {}
    return _cache


def load_messages(path: str | pathlib.Path = 'messages.toml') -> dict[str, Any]:
    """Parse messages.toml and return the raw section dict."""
    p = pathlib.Path(path)
    if not p.exists():
        logger.debug('[message_loader] %s not found - using built-in defaults', path)
        return {}
    return _load_structured_messages(p)


def overlay_colors(settings: Any, base_dir=None) -> None:
    """
    Merge colors section from messages.toml into settings.chat_colors.
    """
    data = _get_data(base_dir)
    if not data or 'colors' not in data:
        return
    colors = dict(settings.chat_colors or {})
    colors.update(data['colors'])
    settings.chat_colors = colors
    logger.debug('[message_loader] Overlaid %d colors', len(data['colors']))


def overlay_core(settings: Any, base_dir=None) -> None:
    """
    Merge sys_messages section from messages.toml into settings.chat_messages.
    Keys are stored uppercased (without the sys_ prefix) to match the existing
    {KEY: [value]} structure that aseco.get_chat_message() expects.
    Call after config.toml has been loaded.
    """
    data = _get_data(base_dir)
    if not data or 'sys_messages' not in data:
        return
    msgs = dict(settings.chat_messages or {})
    count = 0
    for k, v in data['sys_messages'].items():
        store_key = k[len('sys_'):].upper() if k.startswith('sys_') else k.upper()
        msgs[store_key] = [v]
        count += 1
    settings.chat_messages = msgs
    logger.debug('[message_loader] Overlaid %d sys messages', count)


def overlay_section(target_dict: dict, section: str, strip_prefix: str = '', base_dir=None) -> None:
    """
    Merge one named section from messages.toml into *target_dict* in-place.

    target_dict  : the dict the plugin already uses (e.g. _rasp_messages)
    section      : section key in messages config (e.g. 'rasp_messages')
    strip_prefix : prefix removed from structured-config keys before storing
                   (e.g. 'rasp_' so 'rasp_jukebox' -> 'JUKEBOX')

    Keys are stored uppercased and wrapped in [value] to match
    the existing {KEY: [value]} structure plugins expect.
    """
    data = _get_data(base_dir)
    if not data or section not in data:
        return
    count = 0
    for k, v in data[section].items():
        store_key = k[len(strip_prefix):] if strip_prefix and k.startswith(strip_prefix) else k
        target_dict[store_key.upper()] = [v]
        count += 1
    logger.debug('[message_loader] Overlaid %d keys into %s', count, section)


_MK_TO_ATTR: dict[str, str] = {
    'mk_welcome': 'msg_welcome',
    'mk_uptodate_ok': 'msg_uptodate_ok',
    'mk_uptodate_new': 'msg_uptodate_new',
    'mk_uptodate_failed': 'msg_uptodate_failed',
    'mk_karma_message': 'msg_karma_message',
    'mk_karma_your_vote': 'msg_karma_your_vote',
    'mk_karma_not_voted': 'msg_karma_not_voted',
    'mk_karma_details': 'msg_karma_details',
    'mk_karma_done': 'msg_karma_done',
    'mk_karma_change': 'msg_karma_change',
    'mk_karma_voted': 'msg_karma_voted',
    'mk_karma_remind': 'msg_karma_remind',
    'mk_karma_require_finish': 'msg_require_finish',
    'mk_karma_no_public': 'msg_no_public',
    'mk_karma_list_help': 'msg_karma_list_help',
    'mk_karma_help': 'msg_karma_help',
    'mk_karma_reminder_at_score': 'msg_reminder_at_score',
    'mk_karma_vote_singular': 'msg_vote_singular',
    'mk_karma_vote_plural': 'msg_vote_plural',
    'mk_karma_you_have_voted': 'msg_you_have_voted',
    'mk_karma_fantastic': 'msg_fantastic',
    'mk_karma_beautiful': 'msg_beautiful',
    'mk_karma_good': 'msg_good',
    'mk_karma_undecided': 'msg_undecided',
    'mk_karma_bad': 'msg_bad',
    'mk_karma_poor': 'msg_poor',
    'mk_karma_waste': 'msg_waste',
    'mk_karma_show_opinion': 'msg_show_opinion',
    'mk_karma_show_undecided': 'msg_show_undecided',
    'mk_lottery_help': 'msg_lottery_help',
    'mk_lottery_low_coppers': 'msg_lottery_low_coppers',
    'mk_lottery_mail_body': 'msg_lottery_mail_body',
    'mk_lottery_player_won': 'msg_lottery_player_won',
    'mk_lottery_to_few_players': 'msg_lottery_to_few_players',
    'mk_lottery_total_player_win': 'msg_lottery_total_player_win',
}


def overlay_karma_cfg(cfg: Any, base_dir=None) -> None:
    """
    Set msg_* attributes on a KarmaConfig dataclass from mk_messages section.
    Uses an explicit config-key -> attr-name mapping table because the XML tags
    inside <messages> don't follow a consistent prefix pattern.
    """
    data = _get_data(base_dir)
    if not data or 'mk_messages' not in data:
        return
    count = 0
    for config_key, v in data['mk_messages'].items():
        attr = _MK_TO_ATTR.get(config_key)
        if not attr or not hasattr(cfg, attr):
            continue
        if not isinstance(getattr(cfg, attr), str):
            continue
        setattr(cfg, attr, v)
        count += 1
    logger.debug('[message_loader] Overlaid %d keys into KarmaConfig', count)
