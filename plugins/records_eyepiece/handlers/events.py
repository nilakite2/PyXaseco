from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.helpers import format_time, strip_colors
from pyxaseco.models import Gameinfo

from ..config import (
    _state,
    _load_config,
    _effective_mode,
    validate_phase1_runtime,
    validate_phase1_dependencies,
    apply_phase1_defaults,
)
from ..state import _init_player, _clear_per_challenge_state, _loop_time

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Challenge, Player, Record


ML_CPDELTA = 91834
ML_ACTIONKEYS = 91839
_WIDGET_IDS = (91811, 91812, 91813, 91832, 91834)

# Bar widget IDs
_BAR_WIDGET_IDS = (
    91809, 91807, 91808, 91837, 91838,
    91844, 91849, 91810, 91835,
    91841, 91836, 91833,
    5834287, 5834288,
)

# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def _on_sync(aseco: 'Aseco', _data):
    from ..widgets.live import _fetch_live
    from ..widgets.checkpoint import _refresh_cp_targets_all

    validate_phase1_runtime(aseco)
    _load_config(aseco)
    apply_phase1_defaults(aseco)
    validate_phase1_dependencies(aseco)

    # Cache current rpoints for RoundScore widget
    try:
        rp = await aseco.client.query('GetRoundCustomPoints') or []
        _state._rpoints_cache = [int(x) for x in rp] if rp else []
    except Exception:
        _state._rpoints_cache = []

    _clear_per_challenge_state()
    # Record the real game mode now so _effective_mode() works from the start
    _effective_mode(aseco)
    _state.live_cache = await _fetch_live(aseco)
    _state.next_refresh = _loop_time() + _state.refresh_interval

    for player in aseco.server.players.all():
        _init_player(player.login)
        await _apply_custom_ui(aseco, player.login)

    _refresh_cp_targets_all(aseco)

    aseco.console('[Records-Eyepiece] Phase 1 startup complete')

    from ..widgets.bar_widgets import (
        _refresh_server_limits, _refresh_visitor_count,
        draw_all_race_bars, hide_all_score_bars,
    )
    from ..widgets.clock_tz import init_clock_tz
    await init_clock_tz(aseco)
    await _refresh_server_limits(aseco)
    await _refresh_visitor_count(aseco)
    await _redraw_all(aseco)
    await hide_all_score_bars(aseco)
    await draw_all_race_bars(aseco)


async def _on_player_connect(aseco: 'Aseco', player: 'Player'):
    from ..widgets.checkpoint import _refresh_cp_target_for_player

    _init_player(player.login)
    _refresh_cp_target_for_player(aseco, player.login)


async def _on_player_connect2(aseco: 'Aseco', player: 'Player'):
    from ..widgets.bar_widgets import (
        _draw_clock_player, _refresh_server_limits, _refresh_visitor_count,
        _draw_playerspectator_all, draw_all_race_bars, draw_all_score_bars,
    )
    from ..widgets.clock_tz import load_player_tz
    await load_player_tz(aseco, player)
    await _apply_custom_ui(aseco, player.login)
    await _redraw_player(aseco, player.login)
    if not _state.challenge_show_next:
        await _draw_clock_player(aseco, player.login)
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    await _draw_local_all(aseco)
    await _draw_dedi_all(aseco)
    await _refresh_server_limits(aseco)
    await _refresh_visitor_count(aseco)
    if not _state.challenge_show_next:
        await _draw_playerspectator_all(aseco)
    if _state.challenge_show_next:
        await draw_all_score_bars(aseco)
    else:
        await draw_all_race_bars(aseco)


async def _on_player_disconnect(aseco: 'Aseco', player: 'Player'):
    login = player.login
    for d in (
        _state.player_visible,
        _state.player_cp_idx,
        _state.player_cp_lap,
        _state.player_best,
        _state.player_local_digest,
        _state.player_dedi_digest,
        _state.player_live_digest,
        _state.player_cp_delta,
        _state.player_cp_target_mode,
        _state.player_cp_target_name,
        _state.player_cp_target_checks,
    ):
        d.pop(login, None)

    # When a player disconnects, ALL remaining players' widgets must redraw
    # so the online marker (box + icon) for the departed player is removed.
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_timezone.pop(login, None)
    await _draw_local_all(aseco)
    await _draw_dedi_all(aseco)
    from ..widgets.bar_widgets import _refresh_server_limits, _draw_playerspectator_all
    await _refresh_server_limits(aseco)
    if not _state.challenge_show_next:
        await _draw_playerspectator_all(aseco)


async def _on_player_info_changed(aseco: 'Aseco', player: 'Player'):
    from ..widgets.bar_widgets import _draw_playerspectator_all
    from ..widgets.score_widgets import draw_round_score

    await _draw_live_player(aseco, player.login)
    # Spectator status may have changed — redraw CP widgets so the
    # player/spectator pos_y shift is applied immediately.
    await _draw_cp_player(aseco, player.login)
    await _draw_cpdelta_player(aseco, player.login)

    updated_round_score = False
    try:
        team_id = int(getattr(player, 'teamid', 0) or 0)
    except Exception:
        team_id = 0
    for _score, _entries in getattr(_state, 'round_scores', {}).items():
        if not isinstance(_entries, list):
            continue
        for _entry in _entries:
            if isinstance(_entry, dict) and _entry.get('login') == player.login and _entry.get('team') != team_id:
                _entry['team'] = team_id
                updated_round_score = True

    if updated_round_score:
        await draw_round_score(aseco)

    if not _state.challenge_show_next:
        await _draw_playerspectator_all(aseco)


async def _on_player_retire(aseco: 'Aseco', player: 'Player'):
    from ..widgets.common import _hide

    if not player:
        return

    login = player.login
    if not login:
        return

    _state.player_cp_idx[login] = max(0, int(_state.player_cp_idx.get(login, 0) or 0))
    _state.player_cp_delta[login] = ''
    await _hide(aseco, login, ML_CPDELTA)
    await _draw_cp_player(aseco, login)


async def _on_player_finish(aseco: 'Aseco', finish: 'Record'):
    from ..widgets.common import _hide
    from ..widgets.live import _fetch_live

    login = finish.player.login if finish and finish.player else ''
    score = finish.score if finish else 0

    if score == 0:
        if login:
            finish.player.retired = True
            finish.player.finished_waiting = False
            _state.player_cp_idx[login] = 0
            await _draw_cp_player(aseco, login)
        return

    finish.player.retired = False
    finish.player.finished_waiting = True

    if login:
        _state.player_cp_idx[login] = getattr(aseco.server.challenge, 'nbchecks', 0)
        _state.player_cp_delta[login] = ''
        await _hide(aseco, login, ML_CPDELTA)
        await _draw_cp_player(aseco, login)

    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    is_stunts = (mode == Gameinfo.STNT)
    prev = _state.player_best.get(login, -1)
    is_better = (
        prev == -1 or
        (not is_stunts and score < prev) or
        (is_stunts and score > prev)
    )

    # ── Phase 3: RoundScore accumulation ─────────────────────────────────
    _rs_enabled_modes = (Gameinfo.RNDS, Gameinfo.TEAM, Gameinfo.LAPS, Gameinfo.CUP)
    if mode in _rs_enabled_modes and score > 0 and login:
        from pyxaseco.helpers import format_time as _fmt_t
        _player = aseco.server.players.get_player(login)
        _nick   = getattr(_player, 'nickname', login) or login
        _pid    = getattr(_player, 'pid', 0) or 0
        _team   = getattr(_player, 'teamid', 0) or 0
        _cp_idx = _state.player_cp_idx.get(login, 0)
        _entry  = {
            'team': _team, 'playerid': _pid, 'login': login,
            'nickname': _nick,
            'score': _fmt_t(score) if mode != Gameinfo.STNT else str(score),
            'score_plain': score,
            'checkpointid': _cp_idx,
        }
        _state.round_scores.setdefault(score, []).append(_entry)
        # Personal best for tie-breaking
        pb = _state.round_score_pb.get(login, None)
        if pb is None or score < pb:
            _state.round_score_pb[login] = score
        # Broadcast updated widget
        from ..widgets.score_widgets import draw_round_score
        await draw_round_score(aseco)

    # ── Phase 4: TopAverageTimes accumulation ─────────────────────────────
    if score > 0 and login:
        _avg_cfg = getattr(_state, 'stl_top_average_times', {})
        if _avg_cfg.get('enabled', True):
            _state.avg_times.setdefault(login, []).append(score)

    if is_better:
        _state.player_best[login] = score
        if mode != Gameinfo.RNDS:
            _state.live_cache = await _fetch_live(aseco)
            _state.next_refresh = _loop_time() + _state.refresh_interval
            await _draw_live_all(aseco)


async def _on_local_record(aseco: 'Aseco', _rec):
    from ..widgets.checkpoint import _refresh_cp_targets_all

    _state.player_local_digest.clear()
    _refresh_cp_targets_all(aseco)
    await _draw_local_all(aseco)


async def _on_dedi_recs_loaded(aseco: 'Aseco', valid):
    from ..widgets.checkpoint import _refresh_cp_targets_all

    _state.player_dedi_digest.clear()
    _refresh_cp_targets_all(aseco)
    await _draw_dedi_all(aseco)


async def _on_dedi_record(aseco: 'Aseco', _rec):
    from ..widgets.checkpoint import _refresh_cp_targets_all

    _state.player_dedi_digest.clear()
    _refresh_cp_targets_all(aseco)
    await _draw_dedi_all(aseco)


async def _on_begin_round(aseco: 'Aseco', _p=None):
    from ..widgets.common import _hide
    from ..widgets.checkpoint import _refresh_cp_targets_all
    from ..widgets.score_widgets import hide_round_score

    # Refresh last_real_mode — round start always has the real game mode
    _effective_mode(aseco)
    _state.challenge_show_next = False

    for d in (_state.player_cp_idx, _state.player_cp_lap):
        for k in list(d):
            d[k] = 0

    for _player in aseco.server.players.all():
        _player.retired = False
        _player.finished_waiting = False

    for login in list(_state.player_cp_delta):
        _state.player_cp_delta[login] = ''
        await _hide(aseco, login, ML_CPDELTA)

    _state.round_scores.clear()
    _state.round_score_pb.clear()
    await hide_round_score(aseco)
    _refresh_cp_targets_all(aseco)
    await _apply_custom_ui_all(aseco)
    await _draw_cp_all(aseco)
    await _draw_live_all(aseco)


async def _on_end_round(aseco: 'Aseco', _p=None):
    from ..widgets.live import _fetch_live

    # Lock in real mode before score screen (mode 7) is reported
    _effective_mode(aseco)
    _state.live_cache = await _fetch_live(aseco)
    _state.player_live_digest.clear()
    await _draw_live_all(aseco)


async def _on_new_challenge(aseco: 'Aseco', challenge: 'Challenge'):
    from ..widgets.common import _hide

    _state.challenge_show_next = False
    cur = getattr(aseco.server, 'challenge', None)
    if cur and getattr(cur, 'uid', '') and (not challenge or cur.uid != getattr(challenge, 'uid', '')):
        mode = getattr(aseco.server.gameinfo, 'mode', -1)

        def _fmt(v):
            if mode == Gameinfo.STNT:
                return str(int(v or 0))
            return format_time(int(v or 0))

        _state.last_challenge = {
            'name': getattr(cur, 'name', '-') or '-',
            'author': getattr(cur, 'author', '-') or '-',
            'authortime': _fmt(getattr(cur, 'authortime', 0)),
            'goldtime': _fmt(getattr(cur, 'goldtime', 0)),
            'silvertime': _fmt(getattr(cur, 'silvertime', 0)),
            'bronzetime': _fmt(getattr(cur, 'bronzetime', 0)),
            'environment': getattr(cur, 'environment', '') or getattr(cur, 'environnement', '') or '',
        }

    _clear_per_challenge_state()
    _state.round_scores.clear()
    _state.round_score_pb.clear()
    _state.avg_times.clear()

    for _player in aseco.server.players.all():
        _player.retired = False
        _player.finished_waiting = False

    for p in aseco.server.players.all():
        await _hide(aseco, p.login, ML_CPDELTA)


async def _on_new_challenge2(aseco: 'Aseco', _challenge):
    from ..widgets.live import _fetch_live
    from ..widgets.checkpoint import _refresh_cp_targets_all
    from ..widgets.bar_widgets import (
        draw_all_race_bars, hide_all_score_bars,
        _refresh_visitor_count, _refresh_server_limits,
    )
    from ..widgets.score_widgets import hide_all_score_lists, hide_round_score
    from ..toplists import hide_all_score_columns

    _effective_mode(aseco)
    _state.challenge_show_next = False
    _state.next_challenge = {}

    await _apply_custom_ui_all(aseco)
    _state.live_cache = await _fetch_live(aseco)
    _state.next_refresh = _loop_time() + _state.refresh_interval
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_live_digest.clear()
    _refresh_cp_targets_all(aseco)

    # Hide all score-state UI first so stale score columns cannot survive the
    # map transition, then redraw the race widgets for the new challenge.
    await hide_all_score_bars(aseco)
    await hide_all_score_lists(aseco)
    await hide_all_score_columns(aseco)
    await hide_round_score(aseco)

    await _redraw_all(aseco)
    await _refresh_server_limits(aseco)
    await _refresh_visitor_count(aseco)
    await draw_all_race_bars(aseco)


async def _on_restart_challenge(aseco: 'Aseco', _p=None):
    from ..widgets.live import _fetch_live

    _clear_per_challenge_state()
    for _player in aseco.server.players.all():
        _player.retired = False
        _player.finished_waiting = False
    _state.live_cache = await _fetch_live(aseco)
    _state.next_refresh = _loop_time() + _state.refresh_interval
    await _redraw_all(aseco)


async def _on_end_race(aseco: 'Aseco', _p=None):
    from ..widgets.common import _hide
    from ..widgets.live import _fetch_live
    from ..widgets.challenge import _get_next_track_info

    _state.challenge_show_next = True

    # Fetch and cache next track data before any redraw so the small
    # challenge widget can show it immediately in score-state.
    try:
        _state.next_challenge = await _get_next_track_info(aseco, _effective_mode(aseco))
    except Exception:
        _state.next_challenge = {}

    await _apply_custom_ui_all(aseco)
    _state.live_cache = await _fetch_live(aseco)

    for p in aseco.server.players.all():
        _state.player_cp_delta[p.login] = ''
    # Broadcast empty manialinks to hide local/dedi/CP widgets for all players at once.
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPage',
        '<manialink id="91812"></manialink>'
        '<manialink id="91811"></manialink>'
        '<manialink id="91832"></manialink>'
        '<manialink id="91834"></manialink>',
        0,
        False,
    )

    # Redraw challenge widget so players see next track info immediately
    await _draw_challenge_all(aseco)
    await _draw_live_all(aseco)

    from ..widgets.bar_widgets import draw_all_score_bars, hide_all_race_bars
    from ..widgets.score_widgets import draw_all_score_lists
    from ..toplists import draw_all_score_columns
    await hide_all_race_bars(aseco)
    await draw_all_score_bars(aseco)
    await draw_all_score_lists(aseco)
    await draw_all_score_columns(aseco)


async def _on_end_race1(aseco: 'Aseco', _p=None):
    # Keep score-screen widgets visible while the server still reports Score mode (7).
    current_mode = getattr(aseco.server.gameinfo, 'mode', -1)
    if current_mode == Gameinfo.SCOR:
        _state.challenge_show_next = True
        return

    _state.challenge_show_next = False
    _state.next_challenge = {}
    await _apply_custom_ui_all(aseco)
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_live_digest.clear()
    await _redraw_all(aseco)

    from ..widgets.bar_widgets import draw_all_race_bars, hide_all_score_bars
    from ..widgets.score_widgets import hide_all_score_lists, hide_round_score
    from ..toplists import hide_all_score_columns
    await hide_all_score_bars(aseco)
    await hide_all_score_lists(aseco)
    await hide_all_score_columns(aseco)
    await hide_round_score(aseco)
    await draw_all_race_bars(aseco)


async def _on_jukebox_changed(aseco: 'Aseco', _data=None):
    from ..widgets.challenge import _get_next_track_info

    _state.last_challenge = {}
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_live_digest.clear()
    if _state.challenge_show_next:
        try:
            _state.next_challenge = await _get_next_track_info(aseco, _effective_mode(aseco))
        except Exception:
            _state.next_challenge = {}
    await _redraw_all(aseco)


async def _on_tracklist_changed(aseco: 'Aseco', _data=None):
    setattr(aseco.server, '_re_trackcount', 0)
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_live_digest.clear()
    await _redraw_all(aseco)
    from ..widgets.bar_widgets import _draw_trackcount_all, _hide_trackcount
    if _state.challenge_show_next:
        await _hide_trackcount(aseco)
    else:
        await _draw_trackcount_all(aseco)


async def _on_player_wins(aseco: 'Aseco', _player=None):
    _state.player_live_digest.clear()
    await _draw_live_all(aseco)


async def _on_status_to3(aseco: 'Aseco', _data=None):
    setattr(_state, 'warmup', getattr(aseco, 'warmup_phase', False))


async def _on_status_to5(aseco: 'Aseco', _data=None):
    setattr(_state, 'warmup', getattr(aseco, 'warmup_phase', False))
    _state.player_local_digest.clear()
    _state.player_dedi_digest.clear()
    _state.player_live_digest.clear()

    from ..widgets.score_widgets import draw_all_score_lists
    from ..toplists import draw_all_score_columns

    if getattr(aseco.server.gameinfo, 'mode', -1) == Gameinfo.SCOR or _state.challenge_show_next:
        _state.challenge_show_next = True
        await _redraw_all(aseco)
        await draw_all_score_lists(aseco)
        await draw_all_score_columns(aseco)


async def _on_shutdown(aseco: 'Aseco', _data=None):
    try:
        await aseco.client.query_ignore_result('ManualFlowControlEnable', False)
    except Exception:
        pass


async def _on_voting_restart(aseco: 'Aseco', _data=None):
    await _redraw_all(aseco)


async def _on_karma_change(aseco: 'Aseco', _data=None):
    _state.player_live_digest.clear()
    await _draw_live_all(aseco)


async def _on_every_second(aseco: 'Aseco', _p=None):
    from ..widgets.live import _fetch_live
    from ..widgets.bar_widgets import (
        _draw_clock_all, _draw_playerspectator_all, _draw_currentranking_all,
        _refresh_visitor_count, _draw_visitors_all,
    )

    if not _state.loaded:
        return

    if _state.clock.enabled:
        await _draw_clock_all(aseco)

    if _loop_time() >= _state.next_refresh:
        _state.live_cache = await _fetch_live(aseco)
        _state.next_refresh = _loop_time() + max(1, _state.refresh_interval)
        await _draw_live_all(aseco)
        if not _state.challenge_show_next:
            await _refresh_visitor_count(aseco)
            await _draw_visitors_all(aseco)
            await _draw_playerspectator_all(aseco)
            await _draw_currentranking_all(aseco)


async def _on_checkpoint(aseco: 'Aseco', params: list):
    from ..widgets.common import _hide
    from ..widgets.checkpoint import _format_cp_delta, _resolve_display_login
    from ..widgets.live import _fetch_live

    if len(params) < 5:
        return

    login = params[1]
    if login not in _state.player_cp_idx:
        return

    _player = aseco.server.players.get_player(login)
    if _player:
        _player.retired = False
        _player.finished_waiting = False

    try:
        cp_time = int(params[2])
        lap = int(params[3])
        cp_zero = int(params[4])
    except Exception:
        return

    cp_index = cp_zero + 1
    _state.player_cp_idx[login] = cp_index
    _state.player_cp_lap[login] = lap

    checks = _state.player_cp_target_checks.get(login, []) or []
    if cp_zero < len(checks):
        try:
            target_cp = int(checks[cp_zero])
            delta = cp_time - target_cp
            _state.player_cp_delta[login] = _format_cp_delta(delta)
            await _draw_cpdelta_player(aseco, login)
        except Exception:
            _state.player_cp_delta[login] = ''
            await _hide(aseco, login, ML_CPDELTA)
    else:
        _state.player_cp_delta[login] = ''
        await _hide(aseco, login, ML_CPDELTA)

    await _draw_cp_player(aseco, login)

    # Also redraw the CP widget for any spectators or retired viewers watching
    # this player, so their display updates immediately when the target crosses
    # a checkpoint.
    for _sp in aseco.server.players.all():
        if _resolve_display_login(aseco, _sp.login) == login and _sp.login != login:
            await _draw_cp_player(aseco, _sp.login)

    # XAseco refreshes Live Rankings progress during LAPS as checkpoints are hit.
    # Without this, Eyepiece waits for the periodic 1-second refresh loop and
    # feels noticeably behind the CP widget.
    mode = _effective_mode(aseco)
    live_cfg = _state.live.get(mode)
    if (
        mode == Gameinfo.LAPS
        and live_cfg
        and live_cfg.enabled
        and live_cfg.display_type != 'time'
        and not _state.challenge_show_next
    ):
        _state.live_cache = await _fetch_live(aseco)
        _state.next_refresh = _loop_time() + max(1, _state.refresh_interval)
        await _draw_live_all(aseco)


# ---------------------------------------------------------------------------
# Custom UI — hides native TM HUD elements
# ---------------------------------------------------------------------------

async def _apply_custom_ui_all(aseco: 'Aseco'):
    def b(v: bool) -> str:
        return 'true' if v else 'false'

    if _state.custom_ui_enabled:
        hide_challenge = _state.challenge.enabled
        net_infos = _state.custom_ui_net_infos
        chat = _state.custom_ui_chat
        checkpoint_list = _state.custom_ui_checkpoint_list
        round_scores = _state.custom_ui_round_scores
        scoretable = _state.custom_ui_scoretable
    else:
        hide_challenge = False
        net_infos = True
        chat = True
        checkpoint_list = True
        round_scores = True
        scoretable = True

    xml = (
        '<manialinks>'
        '<manialink id="0"><line></line></manialink>'
        '<custom_ui>'
        f'<challenge_info visible="{b(not hide_challenge)}"/>'
        f'<net_infos visible="{b(net_infos)}"/>'
        f'<chat visible="{b(chat)}"/>'
        f'<checkpoint_list visible="{b(checkpoint_list)}"/>'
        f'<round_scores visible="{b(round_scores)}"/>'
        f'<scoretable visible="{b(scoretable)}"/>'
        '</custom_ui>'
        '</manialinks>'
    )

    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPage', xml, 0, False
    )


async def _apply_custom_ui(aseco: 'Aseco', login: str):
    await _apply_custom_ui_all(aseco)


# ---------------------------------------------------------------------------
# Redraw helpers
# ---------------------------------------------------------------------------

async def _redraw_all(aseco: 'Aseco'):
    for p in aseco.server.players.all():
        await _redraw_player(aseco, p.login)


async def _redraw_player(aseco: 'Aseco', login: str):
    from ..widgets.common import _hide, _send

# Keep F7 bound through an always-present hidden actionkey manialink.
    # so widgets can be restored even while they are currently hidden.
    await _send(
        aseco,
        login,
        f'<manialink id="{ML_ACTIONKEYS}"><quad posn="70 70 1" sizen="0 0" action="382009003" actionkey="3"/></manialink>',
    )

    if not _state.player_visible.get(login, True):
        for ml_id in _WIDGET_IDS:
            await _hide(aseco, login, ml_id)
        for ml_id in _BAR_WIDGET_IDS:
            await _hide(aseco, login, ml_id)
        return

    await _draw_challenge_player(aseco, login)
    await _draw_cp_player(aseco, login)
    await _draw_local_player(aseco, login)
    await _draw_dedi_player(aseco, login)
    await _draw_live_player(aseco, login)
    await _draw_cpdelta_player(aseco, login)


async def _draw_challenge_all(aseco: 'Aseco'):
    for p in aseco.server.players.all():
        await _draw_challenge_player(aseco, p.login)


async def _draw_local_all(aseco: 'Aseco'):
    for p in aseco.server.players.all():
        await _draw_local_player(aseco, p.login)


async def _draw_dedi_all(aseco: 'Aseco'):
    for p in aseco.server.players.all():
        await _draw_dedi_player(aseco, p.login)


async def _draw_live_all(aseco: 'Aseco'):
    for p in aseco.server.players.all():
        await _draw_live_player(aseco, p.login)


async def _draw_cp_all(aseco: 'Aseco'):
    for p in aseco.server.players.all():
        await _draw_cp_player(aseco, p.login)


# ---------------------------------------------------------------------------
# Widget dispatchers
# ---------------------------------------------------------------------------

async def _draw_challenge_player(aseco: 'Aseco', login: str):
    from ..widgets.challenge import _draw_challenge_player as impl
    await impl(aseco, login)


async def _draw_cp_player(aseco: 'Aseco', login: str):
    from ..widgets.checkpoint import _draw_cp_player as impl
    await impl(aseco, login)


async def _draw_cpdelta_player(aseco: 'Aseco', login: str):
    from ..widgets.checkpoint import _draw_cpdelta_player as impl
    await impl(aseco, login)


async def _draw_local_player(aseco: 'Aseco', login: str):
    from ..widgets.records_local import _draw_local_player as impl
    await impl(aseco, login)


async def _draw_dedi_player(aseco: 'Aseco', login: str):
    from ..widgets.records_dedi import _draw_dedi_player as impl
    await impl(aseco, login)


async def _draw_live_player(aseco: 'Aseco', login: str):
    from ..widgets.live import _draw_live_player as impl
    await impl(aseco, login)
