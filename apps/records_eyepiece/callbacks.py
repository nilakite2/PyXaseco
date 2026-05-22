from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Component

from .handlers.actions import _on_manialink_answer
from .handlers.events import (
    _on_begin_round,
    _on_checkpoint,
    _on_dedi_record,
    _on_dedi_recs_loaded,
    _on_end_race,
    _on_end_race1,
    _on_end_round,
    _on_every_second,
    _on_jukebox_changed,
    _on_karma_change,
    _on_local_record,
    _on_new_challenge,
    _on_new_challenge2,
    _on_player_connect,
    _on_player_connect2,
    _on_player_disconnect,
    _on_player_finish,
    _on_player_info_changed,
    _on_player_retire,
    _on_player_wins,
    _on_restart_challenge,
    _on_rpg_record,
    _on_shutdown,
    _on_status_to3,
    _on_status_to5,
    _on_sync,
    _on_tracklist_changed,
    _on_trial_record,
    _on_voting_restart,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


class RecordsEyepieceCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.callbacks',
            description='Records Eyepiece HUD orchestration and event redraw surface.',
        )

    def register(self, aseco: 'Aseco') -> None:
        aseco.register_event('onSync',                      _on_sync)
        aseco.register_event('onPlayerConnect',             _on_player_connect)
        aseco.register_event('onPlayerConnect2',            _on_player_connect2)
        aseco.register_event('onPlayerDisconnect',          _on_player_disconnect)
        aseco.register_event('onPlayerInfoChanged',         _on_player_info_changed)
        aseco.register_event('onPlayerFinish1',             _on_player_finish)
        aseco.register_event('onPlayerRetire',              _on_player_retire)
        aseco.register_event('onLocalRecord',               _on_local_record)
        aseco.register_event('onRpgRecord',                 _on_rpg_record)
        aseco.register_event('onTrialRecord',               _on_trial_record)
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


CALLBACK_SURFACE = RecordsEyepieceCallbackSurface()


def get_component() -> RecordsEyepieceCallbackSurface:
    return CALLBACK_SURFACE


def register(aseco: 'Aseco'):
    """Register the active Records Eyepiece callback/event surface."""
    CALLBACK_SURFACE.register(aseco)


__all__ = [
    'register',
    'get_component',
    '_on_sync',
    '_on_player_connect',
    '_on_player_connect2',
    '_on_player_disconnect',
    '_on_player_info_changed',
    '_on_player_finish',
    '_on_player_retire',
    '_on_local_record',
    '_on_rpg_record',
    '_on_trial_record',
    '_on_dedi_recs_loaded',
    '_on_dedi_record',
    '_on_begin_round',
    '_on_end_round',
    '_on_new_challenge',
    '_on_new_challenge2',
    '_on_restart_challenge',
    '_on_end_race',
    '_on_end_race1',
    '_on_every_second',
    '_on_checkpoint',
    '_on_jukebox_changed',
    '_on_tracklist_changed',
    '_on_player_wins',
    '_on_status_to3',
    '_on_status_to5',
    '_on_shutdown',
    '_on_voting_restart',
    '_on_karma_change',
    '_on_manialink_answer',
]
