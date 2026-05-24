from __future__ import annotations

from pyxaseco.core.base import Command, Component

from . import rasp_chat as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


def register_commands(aseco) -> None:
    _impl._apply_app_defaults(aseco)
    cmds = [
        ('pm', 'Sends a private message to login or Player_ID'),
        ('pma', 'Sends a private message to player & admins'),
        ('pmlog', 'Displays log of your recent private messages'),
        ('hi', 'Sends a Hi message to everyone'),
        ('bye', 'Sends a Bye message to everyone'),
        ('thx', 'Sends a Thanks message to everyone'),
        ('lol', 'Sends a Lol message to everyone'),
        ('lool', 'Sends a Lool message to everyone'),
        ('brb', 'Sends a Be Right Back message to everyone'),
        ('afk', 'Sends an Away From Keyboard message to everyone'),
        ('gg', 'Sends a Good Game message to everyone'),
        ('gr', 'Sends a Good Race message to everyone'),
        ('n1', 'Sends a Nice One message to everyone'),
        ('bgm', 'Sends a Bad Game message to everyone'),
        ('official', 'Shows a helpful message ;-)'),
        ('bootme', 'Boot yourself from the server'),
    ]
    for name, help_text in cmds:
        aseco.add_chat_command(name, help_text)
        aseco.register_event(f'onChat_{name}', getattr(_impl, f'chat_{name}'))


class RaspSocialSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='rasp.social',
            description='RASP private-message and social chat command surface.',
            commands=(
                Command('pm', 'Sends a private message to login or Player_ID', _impl.chat_pm),
                Command('pma', 'Sends a private message to player & admins', _impl.chat_pma),
                Command('pmlog', 'Displays log of your recent private messages', _impl.chat_pmlog),
                Command('hi', 'Sends a Hi message to everyone', _impl.chat_hi),
                Command('bye', 'Sends a Bye message to everyone', _impl.chat_bye),
                Command('thx', 'Sends a Thanks message to everyone', _impl.chat_thx),
                Command('lol', 'Sends a Lol message to everyone', _impl.chat_lol),
                Command('lool', 'Sends a Lool message to everyone', _impl.chat_lool),
                Command('brb', 'Sends a Be Right Back message to everyone', _impl.chat_brb),
                Command('afk', 'Sends an Away From Keyboard message to everyone', _impl.chat_afk),
                Command('gg', 'Sends a Good Game message to everyone', _impl.chat_gg),
                Command('gr', 'Sends a Good Race message to everyone', _impl.chat_gr),
                Command('n1', 'Sends a Nice One message to everyone', _impl.chat_n1),
                Command('bgm', 'Sends a Bad Game message to everyone', _impl.chat_bgm),
                Command('official', 'Shows a helpful message ;-)', _impl.chat_official),
                Command('bootme', 'Boot yourself from the server', _impl.chat_bootme),
            ),
        )

    def register(self, aseco) -> None:
        register_commands(aseco)


SOCIAL_SURFACE = RaspSocialSurface()


def get_component() -> RaspSocialSurface:
    return SOCIAL_SURFACE


__all__ = [
    'register',
    'register_commands',
    'RaspSocialSurface',
    'SOCIAL_SURFACE',
    'get_component',
    'chat_pm',
    'chat_pma',
    'chat_pmlog',
    'chat_hi',
    'chat_bye',
    'chat_thx',
    'chat_lol',
    'chat_lool',
    'chat_brb',
    'chat_afk',
    'chat_gg',
    'chat_gr',
    'chat_n1',
    'chat_bgm',
    'chat_official',
    'chat_bootme',
]
