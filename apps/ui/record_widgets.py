"""Eyepiece-owned layout and rendering interface for record HUD widgets."""

from .config import _effective_mode as game_mode, _state
from .hud import append_window_start, append_window_end, append_four_player_columns
from .internal.utils import _handle_special_chars as clean_nickname, _safe_ml_text as label_text
from .widgets.common import _hide as hide, _send as send
from .widgets.records_common import (
    ML_DEDI, ML_SUBWIN, ML_WINDOW,
    _build_record_widget as build_record_widget,
    _dedi_close_to_you as close_to_you,
    _digest_entries as digest_entries,
    _same_login as same_login,
)


def shows_next_map():
    return _state.challenge_show_next


def runtime():
    return getattr(_state, 'aseco', None)


def visible(login):
    return _state.player_visible.get(login, True)


def panel(mode, *, local=False, fallback=False):
    configs = _state.local if local else _state.dedi
    return configs.get(mode, _state.challenge if fallback else None)


def style():
    return _state.style


def marks_online():
    return _state.mark_online


def online_logins(aseco):
    return {player.login for player in aseco.server.players.all()} if marks_online() else set()


def _digests(local):
    return _state.player_local_digest if local else _state.player_dedi_digest


def current_digest(login, *, local=False):
    return _digests(local).get(login)


def set_digest(login, value, *, local=False):
    _digests(local)[login] = value


def clear_digest(login, *, local=False):
    _digests(local).pop(login, None)
