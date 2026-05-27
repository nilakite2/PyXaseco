"""Jukebox app facade."""

from __future__ import annotations

from pyxaseco.core.base import Callback, Command, Component

from . import backend as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


def register_commands(aseco) -> None:
    _impl._runtime_aseco = aseco
    _impl._apply_app_defaults(aseco)
    cmds = [
        ('list', 'Lists tracks currently on the server (see: /list help)', _impl.chat_list),
        ('jukebox', 'Sets track to be played next (see: /jukebox help)', _impl.chat_jukebox),
        ('jb', 'Alias for /jukebox', _impl.chat_jukebox),
        ('autojuke', 'Jukeboxes track from /list (see: /autojuke help)', _impl.chat_autojuke),
        ('aj', 'Alias for /autojuke', _impl.chat_autojuke),
        ('add', 'Adds a track directly from TMX (<ID> {sec})', _impl.chat_add),
        ('y', 'Votes Yes for a TMX track or chat-based vote', _impl.chat_y),
        ('history', 'Shows the 10 most recently played tracks', _impl.chat_history),
        ('xlist', 'Lists tracks on TMX (see: /xlist help)', _impl.chat_xlist),
    ]
    for name, help_text, handler in cmds:
        aseco.add_chat_command(name, help_text)
        aseco.register_event(f'onChat_{name}', handler)


def register_callbacks(aseco) -> None:
    _impl._runtime_aseco = aseco
    aseco.register_event('onSync', _impl._init_jbhistory)
    aseco.register_event('onEndRace', _impl._rasp_endrace)
    aseco.register_event('onNewChallenge2', _impl._rasp_newtrack)
    aseco.register_event('onPlayerManialinkPageAnswer', _impl._event_jukebox)


class JukeboxCommandSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='jukebox.commands',
            description='Jukebox, TMX add, history, xlist, and autojuke command surface.',
            commands=(
                Command('list', 'Lists tracks currently on the server (see: /list help)', _impl.chat_list),
                Command('jukebox', 'Sets track to be played next (see: /jukebox help)', _impl.chat_jukebox),
                Command('jb', 'Alias for /jukebox', _impl.chat_jukebox),
                Command('autojuke', 'Jukeboxes track from /list (see: /autojuke help)', _impl.chat_autojuke),
                Command('aj', 'Alias for /autojuke', _impl.chat_autojuke),
                Command('add', 'Adds a track directly from TMX (<ID> {sec})', _impl.chat_add),
                Command('y', 'Votes Yes for a TMX track or chat-based vote', _impl.chat_y),
                Command('history', 'Shows the 10 most recently played tracks', _impl.chat_history),
                Command('xlist', 'Lists tracks on TMX (see: /xlist help)', _impl.chat_xlist),
            ),
        )

    def register(self, aseco) -> None:
        register_commands(aseco)


class JukeboxCallbackSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='jukebox.callbacks',
            description='Jukebox lifecycle and manialink callback surface.',
            callbacks=(
                Callback('onSync', _impl._init_jbhistory),
                Callback('onEndRace', _impl._rasp_endrace),
                Callback('onNewChallenge2', _impl._rasp_newtrack),
                Callback('onPlayerManialinkPageAnswer', _impl._event_jukebox),
            ),
        )

    def register(self, aseco) -> None:
        _impl._runtime_aseco = aseco
        super().register(aseco)


JUKEBOX_COMMAND_SURFACE = JukeboxCommandSurface()
JUKEBOX_CALLBACK_SURFACE = JukeboxCallbackSurface()


def get_command_component() -> JukeboxCommandSurface:
    return JUKEBOX_COMMAND_SURFACE


def get_callback_component() -> JukeboxCallbackSurface:
    return JUKEBOX_CALLBACK_SURFACE


def get_component():
    return JUKEBOX_COMMAND_SURFACE


__all__ = [
    'register',
    'register_commands',
    'register_callbacks',
    'JukeboxCommandSurface',
    'JukeboxCallbackSurface',
    'JUKEBOX_COMMAND_SURFACE',
    'JUKEBOX_CALLBACK_SURFACE',
    'get_component',
    'get_command_component',
    'get_callback_component',
    'get_jukebox',
    'choose_jukebox_next',
    'force_jukebox_next',
    'admin_add_tmx_track',
    'download_tmx_track',
    'jukebox',
    'jb_buffer',
    'jukebox_check',
    'tmxplaying',
    'tmxplayed',
    'chat_list',
    'chat_jukebox',
    'chat_autojuke',
    'chat_add',
    'chat_y',
    'chat_history',
    'chat_xlist',
]
