"""
plugin_rasp_votes.py — Port of plugins/plugin.rasp_votes.php

Chat-based voting system: /endround /ladder /replay /skip /kick /ignore /cancel
Works with plugin_rasp_jukebox which provides /y and the actual vote-pass logic.

Config read from rasp.settings via plugin_rasp globals.
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, strip_colors, format_time_h

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# Shared vote state (imported by plugin_rasp_jukebox)
chatvote: dict = {}     # {login, nick, votes, type, desc, target?}
tmxadd: dict = {}       # {login, nick, name, votes, uid, filename, environment, source, section}
plrvotes: list = []     # logins who already voted this round

# Per-track counters
num_laddervotes: int = 0
num_replayvotes: int = 0
num_skipvotes: int = 0

# Expire counters (Rounds mode)
r_expire_num: int = 0
ta_expire_start: float = 0.0
ta_show_num: int = 0

# Settings loaded from config
feature_votes: bool = True
vote_ratios: list = [0.5, 0.5, 0.5, 0.5, 0.6, 0.5, 0.5]
vote_in_window: bool = False
allow_spec_startvote: bool = False
allow_spec_voting: bool = False
disable_upon_admin: bool = False
disable_while_sb: bool = False
allow_kickvotes: bool = True
allow_admin_kick: bool = False
allow_ignorevotes: bool = True
allow_admin_ignore: bool = False
ladder_fast_restart: bool = False
auto_vote_starter: bool = True
max_laddervotes: int = 1
max_replayvotes: int = 1
max_skipvotes: int = 1
replays_limit: int = 0
replays_counter: int = 0
r_expire_limit: list = [1, 3, 3, 3, 3, 3, 3]
r_show_reminder: bool = True
r_points_limits: bool = False
ta_expire_limit: list = [120, 240, 240, 180, 180, 180, 180]
ta_show_reminder: bool = True
ta_show_interval: int = 60
ta_time_limits: bool = False
r_ladder_max: float = 0.5
r_replay_min: float = 0.5
r_skip_max: float = 0.8
ta_ladder_max: float = 0.5
ta_replay_min: float = 0.5
ta_skip_max: float = 0.8
global_explain: int = 1
disabled_scoreboard: bool = False


def _plugin_module(module_name: str):
    try:
        return __import__(f'pyxaseco.plugins.{module_name}', fromlist=['*'])
    except ImportError:
        return __import__(f'pyxaseco_plugins.{module_name}', fromlist=['*'])



def _is_spectator(player) -> bool:
    """
    Canonical spectator check.
    """
    raw = getattr(player, 'spectatorstatus', None)
    if raw is not None:
        try:
            return (int(raw) % 10) != 0
        except (TypeError, ValueError):
            pass
    return bool(getattr(player, 'isspectator', False))


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',             _init_votes)
    aseco.register_event('onSync',             _reset_votes)
    aseco.register_event('onEndRace1',         _reset_votes)  # pre-event: reset before other handlers
    aseco.register_event('onNewChallenge',     _enable_votes)
    aseco.register_event('onNewChallenge2',    _enable_votes)
    aseco.register_event('onPlayerConnect',    _explain_votes)
    aseco.register_event('onPlayerDisconnect',  _cancel_kick)
    aseco.register_event('onPlayerInfoChanged',  _on_player_info_changed)
    aseco.register_event('onEndRound',           _r_expire_votes)
    aseco.register_event('onCheckpoint',         _ta_expire_votes)

    aseco.add_chat_command('helpvote', 'Displays info about the chat-based votes')
    aseco.add_chat_command('votehelp', 'Displays info about the chat-based votes')
    aseco.add_chat_command('endround',  'Starts a vote to end current round')
    aseco.add_chat_command('ladder',    'Starts a vote to restart track for ladder')
    aseco.add_chat_command('replay',    'Starts a vote to replay this track')
    aseco.add_chat_command('skip',      'Starts a vote to skip this track')
    aseco.add_chat_command('ignore',    'Starts a vote to ignore a player')
    aseco.add_chat_command('kick',      'Starts a vote to kick a player')
    aseco.add_chat_command('cancel',    'Cancels your current vote')

    aseco.register_event('onChat_helpvote', chat_helpvote)
    aseco.register_event('onChat_votehelp', chat_helpvote)
    aseco.register_event('onChat_endround', chat_endround)
    aseco.register_event('onChat_ladder',   chat_ladder)
    aseco.register_event('onChat_replay',   chat_replay)
    aseco.register_event('onChat_skip',     chat_skip)
    aseco.register_event('onChat_ignore',   chat_ignore)
    aseco.register_event('onChat_kick',     chat_kick)
    aseco.register_event('onChat_cancel',   chat_cancel)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _vote_panels_off(aseco: 'Aseco'):
    try:
        game = getattr(aseco.server, 'get_game', None)
        if callable(game):
            is_tmf = game() == 'TMF'
        else:
            is_tmf = str(getattr(aseco.server, 'game', '')).upper() == 'TMF'

        if not is_tmf:
            return

        from pyxaseco.plugins.plugin_panels import allvotepanels_off
        result = allvotepanels_off(aseco)
        if hasattr(result, '__await__'):
            await result
    except Exception:
        pass


async def _vote_panels_on(aseco: 'Aseco', login: str):
    try:
        game = getattr(aseco.server, 'get_game', None)
        if callable(game):
            is_tmf = game() == 'TMF'
        else:
            is_tmf = str(getattr(aseco.server, 'game', '')).upper() == 'TMF'

        if not is_tmf:
            return

        from pyxaseco.plugins.plugin_panels import allvotepanels_on
        result = allvotepanels_on(aseco, login, aseco.format_colors('{#vote}'))
        if hasattr(result, '__await__'):
            await result
    except Exception:
        pass

def _required_votes(aseco: 'Aseco', ratio: float) -> int:
    """Compute required votes based on active player count."""
    total = sum(1 for pl in aseco.server.players.all()
                if allow_spec_voting or not _is_spectator(pl))
    if total <= 7:
        votes = round(total * ratio)
    else:
        votes = int(total * ratio)
    if votes == 0:
        votes = 1
    elif 2 <= total <= 3 and votes == 1:
        votes = 2
    return votes


def _admin_online(aseco: 'Aseco') -> bool:
    return any(aseco.is_any_admin(pl) for pl in aseco.server.players.all())


async def _broadcast(aseco: 'Aseco', msg: str):
    if vote_in_window:
        try:
            from pyxaseco.plugins.helpers import send_window_message
            await send_window_message(aseco, msg, False)
            return
        except Exception:
            pass

    await aseco.client.query_ignore_result(
        'ChatSendServerMessage',
        aseco.format_colors(msg)
    )


async def _broadcast_tmxadd(aseco: 'Aseco', msg: str):
    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import jukebox_in_window
    except Exception:
        jukebox_in_window = False

    if jukebox_in_window:
        try:
            from pyxaseco.plugins.helpers import send_window_message
            await send_window_message(aseco, msg, False)
            return
        except Exception:
            pass

    await aseco.client.query_ignore_result(
        'ChatSendServerMessage',
        aseco.format_colors(msg)
    )


async def _reply(aseco: 'Aseco', login: str, msg: str):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(msg), login)


def _get_rasp_msg(aseco: 'Aseco', key: str) -> str:
    try:
        _rasp_mod = _plugin_module('plugin_rasp')
        _rasp = getattr(_rasp_mod, '_rasp', {})
        msgs = _rasp.get('messages', {}) if isinstance(_rasp, dict) else getattr(_rasp, 'messages', {})
        items = msgs.get(key, ['{#server}> {#error}' + key])
        return items[0] if items else '{#server}> {#error}' + key
    except Exception:
        return '{#server}> {#error}' + key

async def _check_mode_vote_window(
    aseco: 'Aseco',
    login: str,
    vote_kind: str,
) -> bool:
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    RNDS, TA = 0, 1

    if mode == RNDS and r_points_limits:
        try:
            ranking = await aseco.client.query('GetCurrentRanking', 1, 0) or []
            points = ranking[0].get('Score', 0) if ranking else 0

            info = await aseco.client.query('GetRoundPointsLimit') or {}
            limit = info.get('CurrentValue', 0)

            if vote_kind == 'ladder' and points > (limit * r_ladder_max):
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}First player already has {{#highlite}}$i {points}'
                    '{#error} points - too late for ladder restart!'
                )
                return False

            if vote_kind == 'replay' and points < (limit * r_replay_min):
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}First player has only {{#highlite}}$i {points}'
                    '{#error} points - too early for replay!'
                )
                return False

            if vote_kind == 'skip' and points > (limit * r_skip_max):
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}First player already has {{#highlite}}$i {points}'
                    '{#error} points - too late for skip!'
                )
                return False

        except Exception:
            # keep behavior permissive if the dedicated call fails
            pass

    elif mode == TA and ta_time_limits:
        try:
            from pyxaseco.plugins.plugin_track import time_playing

            played = time_playing(aseco)

            info = await aseco.client.query('GetTimeAttackLimit') or {}
            limit = int(info.get('CurrentValue', 0)) / 1000

            shown = format_time_h(int(played * 1000), False)
            if shown.startswith('00:'):
                shown = shown[3:]

            if vote_kind == 'ladder' and played > (limit * ta_ladder_max):
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}Track is already playing for {{#highlite}}$i {shown}'
                    '{#error} minutes - too late for ladder restart!'
                )
                return False

            if vote_kind == 'replay' and played < (limit * ta_replay_min):
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}Track is only playing for {{#highlite}}$i {shown}'
                    '{#error} minutes - too early for replay!'
                )
                return False

            if vote_kind == 'skip' and played > (limit * ta_skip_max):
                await _reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}Track is already playing for {{#highlite}}$i {shown}'
                    '{#error} minutes - too late for skip!'
                )
                return False

        except Exception:
            pass

    return True

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def _init_votes(aseco: 'Aseco', _data):
    global chatvote, plrvotes, replays_counter
    global feature_votes, vote_ratios, allow_spec_startvote, allow_spec_voting
    global disable_upon_admin, disable_while_sb, allow_kickvotes, allow_admin_kick
    global allow_ignorevotes, allow_admin_ignore, ladder_fast_restart, auto_vote_starter
    global max_laddervotes, max_replayvotes, max_skipvotes, replays_limit
    global r_expire_limit, r_show_reminder, r_points_limits
    global ta_expire_limit, ta_show_reminder, ta_show_interval, ta_time_limits
    global r_ladder_max, r_replay_min, r_skip_max
    global ta_ladder_max, ta_replay_min, ta_skip_max
    global global_explain, vote_in_window, disabled_scoreboard

    chatvote = {}
    plrvotes = []
    replays_counter = 0
    disabled_scoreboard = False

    try:
        _rasp_mod = _plugin_module('plugin_rasp')
        s = _rasp_mod
        feature_votes        = getattr(s, 'feature_votes', feature_votes)
        vote_ratios          = getattr(s, 'vote_ratios', vote_ratios)
        vote_in_window       = getattr(s, 'vote_in_window', vote_in_window)
        allow_spec_startvote = getattr(s, 'allow_spec_startvote', allow_spec_startvote)
        allow_spec_voting    = getattr(s, 'allow_spec_voting', allow_spec_voting)
        disable_upon_admin   = getattr(s, 'disable_upon_admin', disable_upon_admin)
        disable_while_sb     = getattr(s, 'disable_while_sb', disable_while_sb)
        allow_kickvotes      = getattr(s, 'allow_kickvotes', allow_kickvotes)
        allow_admin_kick     = getattr(s, 'allow_admin_kick', allow_admin_kick)
        allow_ignorevotes    = getattr(s, 'allow_ignorevotes', allow_ignorevotes)
        allow_admin_ignore   = getattr(s, 'allow_admin_ignore', allow_admin_ignore)
        ladder_fast_restart  = getattr(s, 'ladder_fast_restart', ladder_fast_restart)
        auto_vote_starter    = getattr(s, 'auto_vote_starter', auto_vote_starter)
        max_laddervotes      = getattr(s, 'max_laddervotes', max_laddervotes)
        max_replayvotes      = getattr(s, 'max_replayvotes', max_replayvotes)
        max_skipvotes        = getattr(s, 'max_skipvotes', max_skipvotes)
        replays_limit        = getattr(s, 'replays_limit', replays_limit)
        r_expire_limit       = getattr(s, 'r_expire_limit', r_expire_limit)
        r_show_reminder      = getattr(s, 'r_show_reminder', r_show_reminder)
        r_points_limits      = getattr(s, 'r_points_limits', r_points_limits)
        ta_expire_limit      = getattr(s, 'ta_expire_limit', ta_expire_limit)
        ta_show_reminder     = getattr(s, 'ta_show_reminder', ta_show_reminder)
        ta_show_interval     = getattr(s, 'ta_show_interval', ta_show_interval)
        ta_time_limits       = getattr(s, 'ta_time_limits', ta_time_limits)
        r_ladder_max         = getattr(s, 'r_ladder_max', r_ladder_max)
        r_replay_min         = getattr(s, 'r_replay_min', r_replay_min)
        r_skip_max           = getattr(s, 'r_skip_max', r_skip_max)
        ta_ladder_max        = getattr(s, 'ta_ladder_max', ta_ladder_max)
        ta_replay_min        = getattr(s, 'ta_replay_min', ta_replay_min)
        ta_skip_max          = getattr(s, 'ta_skip_max', ta_skip_max)
        global_explain       = getattr(s, 'global_explain', global_explain)
    except Exception:
        pass


async def _reset_votes(aseco: 'Aseco', _data):
    global chatvote, num_laddervotes, num_replayvotes, num_skipvotes, disabled_scoreboard

    if chatvote:
        aseco.console('Vote by {1} to {2} reset!',
                      chatvote.get('login', '?'), chatvote.get('desc', '?'))
        await _broadcast(aseco, _get_rasp_msg(aseco, 'VOTE_CANCEL'))
        chatvote = {}
        await _vote_panels_off(aseco)

    num_laddervotes = 0
    num_replayvotes = 0
    num_skipvotes = 0

    if disable_while_sb:
        disabled_scoreboard = True


async def _enable_votes(aseco: 'Aseco', _data):
    global disabled_scoreboard
    disabled_scoreboard = False


async def _explain_votes(aseco: 'Aseco', player):
    if aseco.startup_phase or not feature_votes:
        return
    msg = _get_rasp_msg(aseco, 'VOTE_EXPLAIN')
    if global_explain == 2:
        await _broadcast(aseco, msg)
    elif global_explain == 1:
        msg = msg.replace('{#server}>> ', '{#server}> ')
        await _reply(aseco, player.login, msg)


async def _cancel_kick(aseco: 'Aseco', player):
    global chatvote
    if feature_votes and chatvote:
        if chatvote.get('type') == 4 and chatvote.get('target') == player.login:
            aseco.console('Vote by {1} to {2} reset!',
                          chatvote.get('login', '?'), chatvote.get('desc', '?'))
            await _broadcast(aseco, _get_rasp_msg(aseco, 'VOTE_CANCEL'))
            chatvote = {}
            await _vote_panels_off(aseco)


async def _on_player_info_changed(aseco: 'Aseco', player) -> None:
    """
    Called on every PlayerInfoChanged GBX callback.
    Spec state is read via _is_spectator() which uses spectatorstatus % 10

    - Player -> Spectator: hide vote panel (if not allowed to vote as spec),
      remove from plrvotes so they can vote again if they return.
    - Spectator -> Player: show vote panel if a vote is active and they haven't voted.
    """
    if not feature_votes:
        return

    login = player.login
    is_spec = _is_spectator(player)

    if is_spec:
        if not allow_spec_voting and not aseco.is_any_admin(player):
            try:
                from pyxaseco.plugins.plugin_panels import votepanel_off
                await votepanel_off(aseco, login)
            except Exception:
                pass
            if login in plrvotes:
                plrvotes.remove(login)
    else:
        # Returned to play — show vote panel if a vote is active and they haven't voted yet
        if (chatvote or tmxadd) and login not in plrvotes:
            try:
                from pyxaseco.plugins.plugin_panels import display_votepanel
                ycolor = aseco.format_colors('{#vote}')
                await display_votepanel(aseco, player,
                                        ycolor + 'Yes - F5', '$333No - F6', 0)
            except Exception:
                pass


async def _r_expire_votes(aseco: 'Aseco', _param=None):
    global chatvote, tmxadd, r_expire_num

    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    TA, LAPS, STNT = 1, 3, 4  # Gameinfo constants
    if mode in (TA, LAPS, STNT):
        return

    if chatvote and chatvote.get('type') == 0:
        # endround vote expires immediately at end of round
        msg = format_text(
            _get_rasp_msg(aseco, 'VOTE_END'),
            chatvote.get('desc', ''),
            'expired',
            'Server'
        )
        await _broadcast(aseco, msg)
        chatvote = {}
        await _vote_panels_off(aseco)
        return

    if chatvote or tmxadd:
        expire_limit = r_expire_limit[5] if tmxadd else r_expire_limit[chatvote.get('type', 3)]
        r_expire_num += 1
        if r_expire_num >= expire_limit:
            if chatvote:
                aseco.console('Vote by {1} to {2} expired!',
                              chatvote.get('login', '?'), chatvote.get('desc', '?'))
                msg = format_text(_get_rasp_msg(aseco, 'VOTE_END'),
                                  chatvote.get('desc', ''), 'expired', 'Server')
                await _broadcast(aseco, msg)
                chatvote = {}
            elif tmxadd:
                aseco.console('Vote by {1} to add {2} expired!',
                              tmxadd.get('login', '?'), strip_colors(tmxadd.get('name', '?')))
                msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_END'),
                                  strip_colors(tmxadd.get('name', '')), 'expired', 'Server')
                await _broadcast_tmxadd(aseco, msg)
                tmxadd = {}
            await _vote_panels_off(aseco)
        elif r_show_reminder:
            if chatvote:
                msg = format_text(_get_rasp_msg(aseco, 'VOTE_Y'),
                                  chatvote.get('votes', 0),
                                  '' if chatvote.get('votes', 0) == 1 else 's',
                                  chatvote.get('desc', ''))
                await _broadcast(aseco, msg)
            elif tmxadd:
                msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_Y'),
                                  tmxadd.get('votes', 0),
                                  '' if tmxadd.get('votes', 0) == 1 else 's',
                                  strip_colors(tmxadd.get('name', '')))
                await _broadcast_tmxadd(aseco, msg)


async def _ta_expire_votes(aseco: 'Aseco', _data):
    global chatvote, tmxadd, ta_show_num

    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    RNDS, TEAM, CUP = 0, 2, 5
    if mode in (RNDS, TEAM, CUP):
        return

    if not (chatvote or tmxadd):
        return

    try:
        from pyxaseco.plugins.plugin_track import time_playing
        played = time_playing(aseco)
    except Exception:
        return

    expire_limit = ta_expire_limit[5] if tmxadd else ta_expire_limit[chatvote.get('type', 3)]
    if (played - ta_expire_start) >= expire_limit:
        if chatvote:
            aseco.console(
                'Vote by {1} to {2} expired!',
                chatvote.get('login', '?'),
                chatvote.get('desc', '?')
            )
            msg = format_text(
                _get_rasp_msg(aseco, 'VOTE_END'),
                chatvote.get('desc', ''),
                'expired',
                'Server'
            )
            await _broadcast(aseco, msg)
            chatvote = {}

        elif tmxadd:
            aseco.console(
                'Vote by {1} to add {2} expired!',
                tmxadd.get('login', '?'),
                strip_colors(tmxadd.get('name', '?'))
            )
            msg = format_text(
                _get_rasp_msg(aseco, 'JUKEBOX_END'),
                strip_colors(tmxadd.get('name', '')),
                'expired',
                'Server'
            )
            await _broadcast_tmxadd(aseco, msg)
            tmxadd = {}

        await _vote_panels_off(aseco)
    elif ta_show_reminder:
        intervals = int((played - ta_expire_start) / ta_show_interval)
        if intervals > ta_show_num:
            ta_show_num = intervals
            if chatvote:
                msg = format_text(_get_rasp_msg(aseco, 'VOTE_Y'),
                                  chatvote.get('votes', 0),
                                  '' if chatvote.get('votes', 0) == 1 else 's',
                                  chatvote.get('desc', ''))
                await _broadcast(aseco, msg)
            elif tmxadd:
                msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_Y'),
                                  tmxadd.get('votes', 0),
                                  '' if tmxadd.get('votes', 0) == 1 else 's',
                                  strip_colors(tmxadd.get('name', '')))
                await _broadcast_tmxadd(aseco, msg)


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

async def chat_helpvote(aseco: 'Aseco', command: dict):
    login = command['author'].login
    if not feature_votes:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_VOTE'))
        return
    header = '{#vote}Chat-based votes$g are available for these actions:'
    data = [
        ['Ratio', '{#black}Command', ''],
        [f"{vote_ratios[0]*100:.0f}%", '{#black}/endround', 'Starts a vote to end current round'],
        [f"{vote_ratios[1]*100:.0f}%", '{#black}/ladder',   'Starts a vote to restart track for ladder'],
        [f"{vote_ratios[2]*100:.0f}%", '{#black}/replay',   'Starts a vote to play this track again'],
        [f"{vote_ratios[3]*100:.0f}%", '{#black}/skip',     'Starts a vote to skip this track'],
    ]
    if allow_ignorevotes:
        data.append([f"{vote_ratios[6]*100:.0f}%", '{#black}/ignore', 'Starts a vote to ignore a player'])
    if allow_kickvotes:
        data.append([f"{vote_ratios[4]*100:.0f}%", '{#black}/kick', 'Starts a vote to kick a player'])
    data += [['', '{#black}/cancel', 'Cancels your current vote'], [],
             ['Players can vote with {#black}/y$g until the required number of votes'],
             ['is reached, or the vote expires.']]
    from pyxaseco.helpers import display_manialink
    display_manialink(aseco, login, header,
                      ['Icons64x64_1', 'TrackInfo', -0.01],
                      data, [1.0, 0.1, 0.2, 0.7], 'OK')


async def _start_vote(aseco: 'Aseco', command: dict,
                      vote_type: int, desc: str,
                      ratio: float, target_login: str = '') -> bool:
    """Common vote-start logic. Returns True if vote started."""
    global chatvote, plrvotes, r_expire_num, ta_expire_start, ta_show_num
    player = command['author']
    login = player.login

    if not feature_votes:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_VOTE'))
        return False
    if disabled_scoreboard:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_SB_VOTE'))
        return False
    if not allow_spec_startvote and _is_spectator(player):
        await _reply(aseco, login, _get_rasp_msg(aseco, 'NO_SPECTATORS'))
        return False
    if disable_upon_admin and _admin_online(aseco):
        await _reply(aseco, login,
                     _get_rasp_msg(aseco, 'ASK_ADMIN') + ' {#highlite}' + desc)
        return False
    if chatvote or tmxadd:
        await _reply(aseco, login, _get_rasp_msg(aseco, 'VOTE_ALREADY'))
        return False

    chatvote.update({
        'login': login,
        'nick':  player.nickname,
        'votes': _required_votes(aseco, ratio),
        'type':  vote_type,
        'desc':  desc,
    })
    if target_login:
        chatvote['target'] = target_login

    plrvotes.clear()
    r_expire_num = 0
    ta_show_num = 0
    try:
        from pyxaseco.plugins.plugin_track import time_playing
        ta_expire_start = time_playing(aseco)
    except Exception:
        ta_expire_start = 0.0

    msg = format_text(_get_rasp_msg(aseco, 'VOTE_START'),
                      strip_colors(player.nickname), desc, chatvote['votes'])
    msg = msg.replace('{br}', '\n')
    await _broadcast(aseco, msg)

    await _vote_panels_on(aseco, login)

    if auto_vote_starter:
        from pyxaseco.plugins.plugin_rasp_jukebox import chat_y
        await chat_y(aseco, command)
    return True

async def chat_endround(aseco: 'Aseco', command: dict):
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    TA, LAPS, STNT = 1, 3, 4

    if mode in (TA, LAPS, STNT):
        try:
            mode_name = aseco.server.gameinfo.get_mode()
        except Exception:
            mode_name = str(mode)

        await _reply(
            aseco,
            command['author'].login,
            f'{{#server}}> {{#error}}Running {{#highlite}}$i {mode_name}'
            '{#error} mode - end round disabled!'
        )
        return

    await _start_vote(aseco, command, 0, 'End this Round', vote_ratios[0])


async def chat_ladder(aseco: 'Aseco', command: dict):
    global num_laddervotes
    login = command['author'].login

    if max_laddervotes == 0:
        await _reply(aseco, login, '{#server}> {#error}Ladder restart votes not allowed!')
        return

    if num_laddervotes >= max_laddervotes:
        msg = format_text(
            _get_rasp_msg(aseco, 'VOTE_LIMIT'),
            max_laddervotes,
            '/ladder',
            '' if max_laddervotes == 1 else 's'
        )
        await _reply(aseco, login, msg)
        return

    if not await _check_mode_vote_window(aseco, login, 'ladder'):
        return

    if await _start_vote(aseco, command, 1, 'Restart Track for Ladder', vote_ratios[1]):
        num_laddervotes += 1


async def chat_replay(aseco: 'Aseco', command: dict):
    global num_replayvotes
    login = command['author'].login

    if max_replayvotes == 0:
        await _reply(aseco, login, '{#server}> {#error}Replay votes not allowed!')
        return

    if num_replayvotes >= max_replayvotes:
        msg = format_text(
            _get_rasp_msg(aseco, 'VOTE_LIMIT'),
            max_replayvotes,
            '/replay',
            '' if max_replayvotes == 1 else 's'
        )
        await _reply(aseco, login, msg)
        return

    if replays_limit > 0 and replays_counter >= replays_limit:
        msg = format_text(
            _get_rasp_msg(aseco, 'NO_MORE_REPLAY'),
            replays_limit,
            '' if replays_limit == 1 else 's'
        )
        await _reply(aseco, login, msg)
        return

    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import jukebox
        if aseco.server.challenge.uid in jukebox:
            await _reply(aseco, login, '{#server}> {#error}Track is already getting replayed!')
            return
    except Exception:
        pass

    if not await _check_mode_vote_window(aseco, login, 'replay'):
        return

    if await _start_vote(aseco, command, 2, 'Replay Track after Finish', vote_ratios[2]):
        num_replayvotes += 1


async def chat_skip(aseco: 'Aseco', command: dict):
    global num_skipvotes
    login = command['author'].login

    if max_skipvotes == 0:
        await _reply(aseco, login, '{#server}> {#error}Skip votes not allowed!')
        return

    if num_skipvotes >= max_skipvotes:
        msg = format_text(
            _get_rasp_msg(aseco, 'VOTE_LIMIT'),
            max_skipvotes,
            '/skip',
            '' if max_skipvotes == 1 else 's'
        )
        await _reply(aseco, login, msg)
        return

    if not await _check_mode_vote_window(aseco, login, 'skip'):
        return

    if await _start_vote(aseco, command, 3, 'Skip this Track', vote_ratios[3]):
        num_skipvotes += 1


async def chat_ignore(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    if not allow_ignorevotes:
        await _reply(aseco, login, '{#server}> {#error}Ignore votes not allowed!')
        return
    target = _get_player_param(aseco, player, command.get('params', ''))
    if not target:
        return
    if not allow_admin_ignore and aseco.is_any_admin(target):
        msg = format_text(_get_rasp_msg(aseco, 'NO_ADMIN_IGNORE'),
                          strip_colors(player.nickname),
                          strip_colors(target.nickname))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(msg))
        return
    await _start_vote(aseco, command, 6,
                      f'Ignore {strip_colors(target.nickname)}',
                      vote_ratios[6], target.login)


async def chat_kick(aseco: 'Aseco', command: dict):
    player = command['author']
    login = player.login
    if not allow_kickvotes:
        await _reply(aseco, login, '{#server}> {#error}Kick votes not allowed!')
        return
    target = _get_player_param(aseco, player, command.get('params', ''))
    if not target:
        return
    if not allow_admin_kick and aseco.is_any_admin(target):
        msg = format_text(_get_rasp_msg(aseco, 'NO_ADMIN_KICK'),
                          strip_colors(player.nickname),
                          strip_colors(target.nickname))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(msg))
        return
    await _start_vote(aseco, command, 4,
                      f'Kick {strip_colors(target.nickname)}',
                      vote_ratios[4], target.login)


async def chat_cancel(aseco: 'Aseco', command: dict):
    global chatvote, tmxadd
    player = command['author']
    login = player.login

    if chatvote:
        if login == chatvote.get('login') or aseco.allow_ability(player, 'cancel'):
            aseco.console('Vote to {1} cancelled by {2}!', chatvote.get('desc', '?'), login)
            msg = format_text(_get_rasp_msg(aseco, 'VOTE_END'),
                              chatvote.get('desc', ''), 'cancelled',
                              strip_colors(player.nickname))
            await _broadcast(aseco, msg)
            chatvote = {}
            await _vote_panels_off(aseco)
        else:
            await _reply(aseco, login, "{#server}> {#error}You didn't start the current vote!")
    elif tmxadd:
        if login == tmxadd.get('login') or aseco.allow_ability(player, 'cancel'):
            aseco.console('Vote to add {1} cancelled by {2}!',
                          strip_colors(tmxadd.get('name', '?')), login)
            msg = format_text(_get_rasp_msg(aseco, 'JUKEBOX_END'),
                              strip_colors(tmxadd.get('name', '')), 'cancelled',
                              strip_colors(player.nickname))
            await _broadcast_tmxadd(aseco, msg)
            tmxadd = {}
            await _vote_panels_off(aseco)
        else:
            await _reply(aseco, login, "{#server}> {#error}You didn't start the current vote!")
    else:
        await _reply(aseco, login, '{#server}> {#error}There is no vote in progress!')


def _get_player_param(aseco, requester, param: str, offline: bool = False):
    """Find a player by login or numeric ID from a parameter string."""
    if not param or not param.strip():
        return None
    param = param.strip()
    # Numeric ID -> look up in requester's playerlist
    if param.isdigit():
        pid = int(param) - 1
        pl_list = getattr(requester, 'playerlist', [])
        if 0 <= pid < len(pl_list):
            entry = pl_list[pid]
            param = entry.get('login', '') if isinstance(entry, dict) else str(entry)
    # Try online players
    player = aseco.server.players.get_player(param)
    if player:
        return player
    if offline:
        from pyxaseco.models import Player as _P
        stub = _P()
        stub.login    = param
        stub.nickname = param
        stub.teamname = ''
        stub.ladderrank = 0
        return stub
    return None
