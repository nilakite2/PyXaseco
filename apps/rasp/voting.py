"""RASP voting domain facade.

This module provides a stable app-level surface for vote state and callbacks
while the implementation still lives in ``rasp_votes.py``.
"""

from __future__ import annotations

from pyxaseco.core.base import Callback, Command, Component

from . import rasp_votes as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


def register_commands(aseco) -> None:
    cmds = [
        ('helpvote', 'Displays info about the chat-based votes', _impl.chat_helpvote),
        ('votehelp', 'Displays info about the chat-based votes', _impl.chat_helpvote),
        ('endround', 'Starts a vote to end current round', _impl.chat_endround),
        ('ladder', 'Starts a vote to restart track for ladder', _impl.chat_ladder),
        ('replay', 'Starts a vote to replay this track', _impl.chat_replay),
        ('skip', 'Starts a vote to skip this track', _impl.chat_skip),
        ('ignore', 'Starts a vote to ignore a player', _impl.chat_ignore),
        ('kick', 'Starts a vote to kick a player', _impl.chat_kick),
        ('cancel', 'Cancels your current vote', _impl.chat_cancel),
    ]
    for name, help_text, handler in cmds:
        aseco.add_chat_command(name, help_text)
        aseco.register_event(f'onChat_{name}', handler)


def register_callbacks(aseco) -> None:
    aseco.register_event('onSync', _impl._init_votes)
    aseco.register_event('onSync', _impl._reset_votes)
    aseco.register_event('onEndRace1', _impl._reset_votes)
    aseco.register_event('onNewChallenge', _impl._enable_votes)
    aseco.register_event('onNewChallenge2', _impl._enable_votes)
    aseco.register_event('onPlayerConnect', _impl._explain_votes)
    aseco.register_event('onPlayerDisconnect', _impl._cancel_kick)
    aseco.register_event('onPlayerInfoChanged', _impl._on_player_info_changed)
    aseco.register_event('onEndRound', _impl._r_expire_votes)
    aseco.register_event('onCheckpoint', _impl._ta_expire_votes)


class RaspVotingCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.voting.commands',
            description='RASP vote state and player/server vote command surface.',
            commands=(
                Command('helpvote', 'Displays info about the chat-based votes', _impl.chat_helpvote),
                Command('votehelp', 'Displays info about the chat-based votes', _impl.chat_helpvote),
                Command('endround', 'Starts a vote to end current round', _impl.chat_endround),
                Command('ladder', 'Starts a vote to restart track for ladder', _impl.chat_ladder),
                Command('replay', 'Starts a vote to replay this track', _impl.chat_replay),
                Command('skip', 'Starts a vote to skip this track', _impl.chat_skip),
                Command('ignore', 'Starts a vote to ignore a player', _impl.chat_ignore),
                Command('kick', 'Starts a vote to kick a player', _impl.chat_kick),
                Command('cancel', 'Cancels your current vote', _impl.chat_cancel),
            ),
        )

    def register(self, aseco) -> None:
        super().register(aseco)


class RaspVotingCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.voting.callbacks',
            description='RASP vote lifecycle, expiry, and moderation callback surface.',
            callbacks=(
                Callback('onSync', _impl._init_votes),
                Callback('onSync', _impl._reset_votes),
                Callback('onEndRace1', _impl._reset_votes),
                Callback('onNewChallenge', _impl._enable_votes),
                Callback('onNewChallenge2', _impl._enable_votes),
                Callback('onPlayerConnect', _impl._explain_votes),
                Callback('onPlayerDisconnect', _impl._cancel_kick),
                Callback('onPlayerInfoChanged', _impl._on_player_info_changed),
                Callback('onEndRound', _impl._r_expire_votes),
                Callback('onCheckpoint', _impl._ta_expire_votes),
            ),
        )

    def register(self, aseco) -> None:
        super().register(aseco)


VOTING_COMMAND_SURFACE = RaspVotingCommandSurface()
VOTING_CALLBACK_SURFACE = RaspVotingCallbackSurface()


def get_command_component() -> RaspVotingCommandSurface:
    return VOTING_COMMAND_SURFACE


def get_callback_component() -> RaspVotingCallbackSurface:
    return VOTING_CALLBACK_SURFACE


def get_component():
    return VOTING_COMMAND_SURFACE


__all__ = [
    'register',
    'register_commands',
    'register_callbacks',
    'RaspVotingCommandSurface',
    'RaspVotingCallbackSurface',
    'VOTING_COMMAND_SURFACE',
    'VOTING_CALLBACK_SURFACE',
    'get_component',
    'get_command_component',
    'get_callback_component',
    'chatvote',
    'tmxadd',
    'plrvotes',
    'chat_helpvote',
    'chat_endround',
    'chat_ladder',
    'chat_replay',
    'chat_skip',
    'chat_ignore',
    'chat_kick',
    'chat_cancel',
]
