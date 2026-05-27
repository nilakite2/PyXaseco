from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import Callback, Component

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
            callbacks=(
                Callback('onSync', _on_sync),
                Callback('onPlayerConnect', _on_player_connect),
                Callback('onPlayerConnect2', _on_player_connect2),
                Callback('onPlayerDisconnect', _on_player_disconnect),
                Callback('onPlayerInfoChanged', _on_player_info_changed),
                Callback('onPlayerFinish1', _on_player_finish),
                Callback('onPlayerRetire', _on_player_retire),
                Callback('onLocalRecord', _on_local_record),
                Callback('onRpgRecord', _on_rpg_record),
                Callback('onTrialRecord', _on_trial_record),
                Callback('onDediRecsLoaded', _on_dedi_recs_loaded),
                Callback('onDedimaniaRecord', _on_dedi_record),
                Callback('onBeginRound', _on_begin_round),
                Callback('onEndRound', _on_end_round),
                Callback('onNewChallenge', _on_new_challenge),
                Callback('onNewChallenge2', _on_new_challenge2),
                Callback('onRestartChallenge2', _on_restart_challenge),
                Callback('onEndRace', _on_end_race),
                Callback('onEndRace1', _on_end_race1),
                Callback('onEverySecond', _on_every_second),
                Callback('onCheckpoint', _on_checkpoint),
                Callback('onJukeboxChanged', _on_jukebox_changed),
                Callback('onTracklistChanged', _on_tracklist_changed),
                Callback('onChallengeListModified', _on_tracklist_changed),
                Callback('onPlayerWins', _on_player_wins),
                Callback('onStatusChangeTo3', _on_status_to3),
                Callback('onStatusChangeTo5', _on_status_to5),
                Callback('onShutdown', _on_shutdown),
                Callback('onVotingRestartChallenge', _on_voting_restart),
                Callback('onKarmaChange', _on_karma_change),
                Callback('onPlayerManialinkPageAnswer', _on_manialink_answer),
            ),
        )

    def register(self, aseco: 'Aseco') -> None:
        super().register(aseco)


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
