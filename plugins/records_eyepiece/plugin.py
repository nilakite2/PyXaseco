from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import _state, _load_config

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


def register(aseco: 'Aseco'):
    """
    Package entry-point for Records Eyepiece.

    This preserves the original register() behavior from the monolithic
    plugin_records_eyepiece.py, but delegates implementation to split modules.
    """

    # Delayed imports avoid circular dependencies during package startup.
    from .handlers.events import (
        _on_sync,
        _on_player_connect,
        _on_player_connect2,
        _on_player_disconnect,
        _on_player_info_changed,
        _on_player_finish,
        _on_local_record,
        _on_dedi_recs_loaded,
        _on_dedi_record,
        _on_begin_round,
        _on_end_round,
        _on_new_challenge,
        _on_new_challenge2,
        _on_restart_challenge,
        _on_end_race,
        _on_end_race1,
        _on_every_second,
        _on_checkpoint,
        _on_jukebox_changed,
        _on_tracklist_changed,
        _on_player_wins,
        _on_status_to3,
        _on_status_to5,
        _on_shutdown,
        _on_voting_restart,
        _on_karma_change,
    )
    from .handlers.actions import _on_manialink_answer
    from .handlers.chat import (
        chat_togglewidgets,
        chat_eyepiece,
        _elist_redirect,
        chat_estat,
        chat_eyeset,
    )

    # ------------------------------------------------------------------
    # Event registration
    # ------------------------------------------------------------------

    aseco.register_event('onSync',                      _on_sync)
    aseco.register_event('onPlayerConnect',             _on_player_connect)
    aseco.register_event('onPlayerConnect2',            _on_player_connect2)
    aseco.register_event('onPlayerDisconnect',          _on_player_disconnect)
    aseco.register_event('onPlayerInfoChanged',         _on_player_info_changed)
    aseco.register_event('onPlayerFinish1',             _on_player_finish)
    aseco.register_event('onLocalRecord',               _on_local_record)
    aseco.register_event('onDediRecsLoaded',            _on_dedi_recs_loaded)
    aseco.register_event('onDedimaniaRecord',           _on_dedi_record)
    aseco.register_event('onBeginRound',                _on_begin_round)
    aseco.register_event('onEndRound',                  _on_end_round)
    aseco.register_event('onNewChallenge',              _on_new_challenge)
    aseco.register_event('onNewChallenge2',             _on_new_challenge2)
    aseco.register_event('onRestartChallenge2',         _on_restart_challenge)
    aseco.register_event('onEndRace',                   _on_end_race)
    aseco.register_event('onEndRace1',                  _on_end_race1)
    aseco.register_event('onEverySecond',               _on_every_second)
    aseco.register_event('onCheckpoint',                _on_checkpoint)
    aseco.register_event('onJukeboxChanged',            _on_jukebox_changed)
    aseco.register_event('onTracklistChanged',          _on_tracklist_changed)
    aseco.register_event('onChallengeListModified',     _on_tracklist_changed)
    aseco.register_event('onPlayerWins',                _on_player_wins)
    aseco.register_event('onStatusChangeTo3',           _on_status_to3)
    aseco.register_event('onStatusChangeTo5',           _on_status_to5)
    aseco.register_event('onShutdown',                  _on_shutdown)
    aseco.register_event('onVotingRestartChallenge',    _on_voting_restart)
    aseco.register_event('onKarmaChange',               _on_karma_change)
    aseco.register_event('onPlayerManialinkPageAnswer', _on_manialink_answer)

    # ------------------------------------------------------------------
    # Chat commands
    # ------------------------------------------------------------------

    aseco.add_chat_command('togglewidgets', 'Toggle the display of the Records-Eyepiece widgets')
    aseco.add_chat_command('eyepiece',      'Displays help for the Records-Eyepiece widgets')
    aseco.add_chat_command('elist',         'Lists tracks currently on the server')
    aseco.add_chat_command('estat',         'Display one of the MoreRankingLists')
    aseco.add_chat_command('eyeset',        'Adjust Records-Eyepiece settings', True)

    aseco.register_event('onChat_togglewidgets', chat_togglewidgets)
    aseco.register_event('onChat_eyepiece',      chat_eyepiece)

    aseco.register_event('onChat_elist',         _elist_redirect)

    aseco.register_event('onChat_estat',         chat_estat)
    aseco.register_event('onChat_eyeset',        chat_eyeset)


def get_state():
    """
    Small helper for other modules/tests that want the shared Eyepiece state.
    """
    return _state


def reload_config(aseco: 'Aseco') -> None:
    """
    Convenience wrapper for split modules that want to reload the XML config.
    """
    _load_config(aseco)