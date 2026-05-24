"""RASP ranking domain facade.

This module provides a stable app-level surface for ranking state, commands,
and callbacks while the implementation still lives in ``rasp.py``.
"""

from __future__ import annotations

from pyxaseco.core.base import Component

from . import rasp as _impl


def get_runtime_state() -> dict:
    return getattr(_impl, '_rasp', {})


def get_messages() -> dict:
    return getattr(_impl, '_rasp_messages', {})


def __getattr__(name: str):
    return getattr(_impl, name)


def register_commands(aseco) -> None:
    aseco.add_chat_command('pb', 'Shows your personal best on current track')
    aseco.add_chat_command('rank', 'Shows your current server rank')
    aseco.add_chat_command('top10', 'Displays top 10 best ranked players')
    aseco.add_chat_command('top100', 'Displays top 100 best ranked players')
    aseco.add_chat_command('topwins', 'Displays top 100 victorious players')
    aseco.add_chat_command('active', 'Displays top 100 most active players')

    aseco.register_event('onChat_pb', _impl.chat_pb)
    aseco.register_event('onChat_rank', _impl.chat_rank)
    aseco.register_event('onChat_top10', _impl.chat_top10)
    aseco.register_event('onChat_top100', _impl.chat_top100)
    aseco.register_event('onChat_topwins', _impl.chat_topwins)
    aseco.register_event('onChat_active', _impl.chat_active)


def register_callbacks(aseco) -> None:
    aseco.register_event('onStartup', _impl.rasp_startup)
    aseco.register_event('onSync', _impl.rasp_sync)
    aseco.register_event('onNewChallenge2', _impl.rasp_new_challenge)
    aseco.register_event('onEndRace', _impl.rasp_end_race)
    aseco.register_event('onPlayerFinish', _impl.rasp_player_finish)
    aseco.register_event('onPlayerConnect', _impl.rasp_player_connect)


class RaspRankingCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.rankings.commands',
            description='RASP ranking commands and leaderboard chat surface.',
        )

    def register(self, aseco) -> None:
        register_commands(aseco)


class RaspRankingCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.rankings.callbacks',
            description='RASP ranking lifecycle, finish, and leaderboard callback surface.',
        )

    def register(self, aseco) -> None:
        register_callbacks(aseco)


RANKING_COMMAND_SURFACE = RaspRankingCommandSurface()
RANKING_CALLBACK_SURFACE = RaspRankingCallbackSurface()


def get_command_component() -> RaspRankingCommandSurface:
    return RANKING_COMMAND_SURFACE


def get_callback_component() -> RaspRankingCallbackSurface:
    return RANKING_CALLBACK_SURFACE


def get_component():
    return RANKING_COMMAND_SURFACE


__all__ = [
    'register',
    'register_commands',
    'register_callbacks',
    'get_runtime_state',
    'get_messages',
    'RaspRankingCommandSurface',
    'RaspRankingCallbackSurface',
    'RANKING_COMMAND_SURFACE',
    'RANKING_CALLBACK_SURFACE',
    'get_component',
    'get_command_component',
    'get_callback_component',
    '_rasp',
    '_rasp_messages',
    '_challenge_list_cache',
    'feature_ranks',
    'feature_votes',
    'maxrecs',
    'chat_pb',
    'chat_rank',
    'chat_top10',
    'chat_top100',
    'chat_topwins',
    'chat_active',
]
