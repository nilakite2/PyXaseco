"""
mistral_idlekick.py — Port of plugins/mistral.idlekick.php

Kicks (or specs) players that are idle for too many consecutive challenges.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from pyxaseco.helpers import format_text

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

# Configuration
KICK_PLAY_AFTER    = 2      # kick/spec players idle this many challenges
KICK_SPEC_AFTER    = 4      # kick spectators idle this many challenges
KICK_SPEC_TOO      = True   # kick spectators as well
SPEC_PLAY_FIRST    = False  # force to spec before kicking (TMF only)
RESET_ON_CHAT      = True   # reset idle counter on chat
RESET_ON_CHECKPOINT = True  # reset idle counter on checkpoint
RESET_ON_FINISH    = False  # reset idle counter on finish

_start = True  # first challenge flag


def register(aseco: 'Aseco'):
    aseco.register_event('onNewChallenge',  kick_idle_new_challenge)
    aseco.register_event('onPlayerConnect', kick_idle_init)
    aseco.register_event('onChat',          kick_idle_chat)
    aseco.register_event('onCheckpoint',    kick_idle_checkpoint)
    aseco.register_event('onPlayerFinish',  kick_idle_finish)
    aseco.register_event('onEndRace',       kick_idle_players)


async def kick_idle_init(aseco: 'Aseco', player: 'Player'):
    if not hasattr(player, 'mistral'):
        player.mistral = {}
    player.mistral['idleCount'] = 0


async def kick_idle_chat(aseco: 'Aseco', params: list):
    if not RESET_ON_CHAT:
        return
    if len(params) < 2:
        return
    if params[0] == aseco.server.id:
        return
    player = aseco.server.players.get_player(params[1])
    if player:
        if not hasattr(player, 'mistral'):
            player.mistral = {}
        player.mistral['idleCount'] = 0


async def kick_idle_checkpoint(aseco: 'Aseco', params: list):
    if not RESET_ON_CHECKPOINT or len(params) < 2:
        return
    player = aseco.server.players.get_player(params[1])
    if player:
        if not hasattr(player, 'mistral'):
            player.mistral = {}
        player.mistral['idleCount'] = 0


async def kick_idle_finish(aseco: 'Aseco', params: list):
    if not RESET_ON_FINISH or len(params) < 2:
        return
    player = aseco.server.players.get_player(params[1])
    if player:
        if not hasattr(player, 'mistral'):
            player.mistral = {}
        player.mistral['idleCount'] = 0


async def kick_idle_new_challenge(aseco: 'Aseco', _challenge):
    global _start
    if _start:
        _start = False
        for player in aseco.server.players.all():
            await kick_idle_init(aseco, player)
        return

    for player in aseco.server.players.all():
        is_spec = player.isspectator
        if is_spec and aseco.allow_ability(player, 'noidlekick_spec'):
            continue
        if not is_spec and aseco.allow_ability(player, 'noidlekick_play'):
            continue
        if KICK_SPEC_TOO or not is_spec:
            if not hasattr(player, 'mistral'):
                player.mistral = {}
            player.mistral['idleCount'] = player.mistral.get('idleCount', 0) + 1


async def kick_idle_players(aseco: 'Aseco', _params):
    for player in aseco.server.players.all():
        is_spec = player.isspectator
        idle = getattr(getattr(player, 'mistral', {}), 'get',
                       lambda k, d=0: player.mistral.get(k, d) if hasattr(player, 'mistral') else d)('idleCount', 0)
        threshold = KICK_SPEC_AFTER if is_spec else KICK_PLAY_AFTER

        if idle < threshold:
            continue

        do_kick = False
        if is_spec:
            do_kick = True
            msg_key = 'IDLEKICK_SPEC'
            message = format_text(aseco.get_chat_message(msg_key),
                                  player.nickname, threshold, '' if threshold == 1 else 's')
        else:
            if SPEC_PLAY_FIRST:
                msg_key = 'IDLESPEC_PLAY'
                message = format_text(aseco.get_chat_message(msg_key),
                                      player.nickname, threshold, '' if threshold == 1 else 's')
                try:
                    await aseco.client.query('ForceSpectator', player.login, 1)
                    await aseco.client.query('ForceSpectator', player.login, 0)
                    mc = aseco.client.build_multicall()
                    mc.add('ForceSpectatorTarget', player.login, '', 2)
                    await mc.query_ignore_result()
                except Exception:
                    pass
            else:
                do_kick = True
                msg_key = 'IDLEKICK_PLAY'
                message = format_text(aseco.get_chat_message(msg_key),
                                      player.nickname, threshold, '' if threshold == 1 else 's')

        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(message))
        if do_kick:
            await aseco.client.query_ignore_result('Kick', player.login)
