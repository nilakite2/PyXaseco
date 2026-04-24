from __future__ import annotations

import asyncio

from .config import _state


def get_state():
    return _state


def _init_player(login: str):
    _state.player_visible.setdefault(login, True)
    _state.player_cp_idx[login] = 0
    _state.player_cp_lap[login] = 0
    _state.player_cp_delta[login] = ''
    _state.player_cp_target_mode.setdefault(login, '')
    _state.player_cp_target_name.setdefault(login, '')
    _state.player_cp_target_checks.setdefault(login, [])


def _clear_per_challenge_state():
    _state.player_best.clear()
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_live_digest.clear()

    for login in list(_state.player_visible):
        _state.player_cp_idx[login] = 0
        _state.player_cp_lap[login] = 0
        _state.player_cp_delta[login] = ''
        _state.player_cp_target_mode[login] = ''
        _state.player_cp_target_name[login] = ''
        _state.player_cp_target_checks[login] = []


def _loop_time() -> float:
    try:
        return asyncio.get_running_loop().time()
    except RuntimeError:
        import time
        return time.monotonic()