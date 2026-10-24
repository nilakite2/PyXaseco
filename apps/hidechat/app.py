"""Personal chat controls, ported from schmidi's hideChat plugin (2009)."""

import logging

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_float, as_str,
    bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.core.base import App
from pyxaseco.core.chat_visibility import forget, overrides, set_override
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase


logger = logging.getLogger(__name__)
ML_ID = 5834291
ACTION = 8551100
MODES = ('on', 'auto', 'off')
SCHEMA = AppSettingsSchema(app_id='hidechat', settings=(
    AppSetting('enabled', True, as_bool, 'Enable personal chat visibility controls.'),
    AppSetting('default_mode', 'on', as_str, 'Initial chat mode: on, off or auto.'),
    AppSetting('auto_rounds', False, as_bool, 'Auto hides from round start in Rounds, Team and Cup.'),
    AppSetting('global_messages', False, as_bool, 'Announce player mode changes to everyone.'),
    AppSetting('button/enabled', True, as_bool, 'Show the small chat mode cycle button.'),
    AppSetting('button/pos_x', -63.9, as_float, 'Chat button X position.'),
    AppSetting('button/pos_y', -40.0, as_float, 'Chat button Y position.'),
    AppSetting('button/size', 1.6, as_float, 'Chat button size.'),
))
APP_METADATA = {
    'id': 'hidechat', 'display_name': 'Hide Chat',
    'description': 'Personal on/off/auto chat visibility and a small cycle button.',
    'modules': ['apps/hidechat/app.py'], 'entries': ['app/hidechat'],
    'provides': ['feature/hidechat'], 'depends_on': ['platform_core'],
}


def _spectator(player):
    return bool(getattr(player, 'isspectator', False) or
                int(getattr(player, 'spectatorstatus', 0) or 0) % 10)


class HideChatApp(App):
    def __init__(self):
        super().__init__(app_id='hidechat', display_name='Hide Chat',
                         description=APP_METADATA['description'], depends_on=('platform_core',),
                         entry_modules=('app/hidechat',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.modes = {}
        self.driving = set()
        self.hidden_buttons = set()

    def register_runtime(self, aseco):
        aseco.add_chat_command('chat', 'Personal chat visibility: /chat on, off or auto',
                               app='hidechat', owner='feature/hidechat',
                               usage='/chat [on|off|auto]', category='chat')
        for event, callback in (
            ('onChat_chat', self.command), ('onPlayerConnect', self.connect),
            ('onPlayerDisconnect', self.disconnect), ('onCheckpoint', self.checkpoint),
            ('onPlayerFinish1', self.finish), ('onPlayerRetire', self.retire),
            ('onPlayerInfoChanged', self.info_changed), ('onNewChallenge', self.reset),
            ('onRestartChallenge', self.reset), ('onBeginRound', self.begin_round),
            ('onEndRound', self.reset), ('onEndRace', self.reset),
            ('onStatusChangeTo3', self.reset), ('onStatusChangeTo5', self.reset),
            ('onPlayerManialinkPageAnswer', self.answer),
            ('onWidgetVisibilityChanged', self.widget_visibility), ('onMenuLoaded', self.menu),
        ):
            aseco.register_event(event, callback)

    def configure(self, aseco):
        self.values = bind_app_settings(SCHEMA, getattr(aseco, '_base_dir', None)).values
        self.enabled = self.values['enabled']
        default = self.values['default_mode'].lower().strip()
        if default not in MODES:
            logger.warning('[HideChat] Invalid default_mode; using on')
            default = 'on'
        self.values['default_mode'] = default

    async def startup(self, context):
        self.configure(context.aseco)
        await self.refresh(context.aseco)

    async def shutdown(self, context):
        self.enabled = False
        await self.refresh(context.aseco)
        self.modes.clear()
        self.driving.clear()
        self.hidden_buttons.clear()

    def mode(self, player):
        return self.modes.get(player.login, self.values.get('default_mode', 'on'))

    def visible(self, aseco, player):
        mode = self.mode(player)
        return (mode == 'on' or (mode == 'auto' and
                (player.login not in self.driving or _spectator(player) or is_score_phase(aseco))))

    async def apply(self, aseco, player):
        value = self.visible(aseco, player) if self.enabled else None
        await set_override(aseco, player.login, 'hidechat', value)

    async def refresh(self, aseco):
        if not self.enabled:
            for login in list(overrides(aseco)):
                forget(aseco, login, 'hidechat')
        for player in aseco.server.players.all():
            await self.apply(aseco, player)
            await self.draw_button(aseco, player)

    async def connect(self, aseco, player):
        self.modes.pop(player.login, None)
        self.driving.discard(player.login)
        self.hidden_buttons.discard(player.login)
        if self.enabled:
            await self.apply(aseco, player)
            await self.draw_button(aseco, player)

    async def disconnect(self, aseco, player):
        self.modes.pop(player.login, None)
        self.driving.discard(player.login)
        self.hidden_buttons.discard(player.login)
        forget(aseco, player.login, 'hidechat')

    async def command(self, aseco, command):
        player = command['author']
        parameter = str(command.get('params') or '').strip().lower()
        if not self.enabled:
            await self.reply(aseco, player, '{#error}Hide Chat is disabled.')
            return
        if parameter not in MODES:
            await self.reply(aseco, player, '{#message}/chat on: always show; /chat off: hide; '
                             '/chat auto: hide while racing. Current: {#highlite}' + self.mode(player))
            return
        self.modes[player.login] = parameter
        await self.apply(aseco, player)
        message = '{#message}Chat panel: {#highlite}' + parameter
        if self.values['global_messages']:
            await aseco.client.query_ignore_result('ChatSendServerMessage',
                aseco.format_colors('{#server}> ' + player.nickname + '$z$s ' + message))
        else:
            await self.reply(aseco, player, message)

    async def reply(self, aseco, player, message):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> ' + message), player.login)

    async def checkpoint(self, aseco, data):
        if not self.enabled or len(data) < 5:
            return
        player = aseco.server.players.get_player(data[1])
        if player is None or _spectator(player) or is_score_phase(aseco) or player.login in self.driving:
            return
        if int(data[4]) == 0:
            self.driving.add(player.login)
            if self.mode(player) == 'auto':
                await self.apply(aseco, player)

    async def finish(self, aseco, record):
        player = getattr(record, 'player', None)
        if player is not None:
            await self.retire(aseco, player)

    async def retire(self, aseco, player):
        self.driving.discard(player.login)
        if self.enabled and self.mode(player) == 'auto':
            await self.apply(aseco, player)

    async def info_changed(self, aseco, player):
        if _spectator(player):
            await self.retire(aseco, player)

    async def reset(self, aseco, _data=None):
        self.driving.clear()
        if self.enabled:
            await self.refresh(aseco)

    async def begin_round(self, aseco, _data=None):
        self.driving.clear()
        if self.enabled:
            if self.values['auto_rounds'] and aseco.server.gameinfo.mode in (0, 2, 5):
                self.driving.update(player.login for player in aseco.server.players.all() if not _spectator(player))
            await self.refresh(aseco)

    def button_xml(self):
        size = max(.8, min(4.0, self.values['button/size']))
        return (f'<manialink id="{ML_ID}"><frame posn="{self.values["button/pos_x"]} '
                f'{self.values["button/pos_y"]} 0">'
                f'<quad sizen="{size} {size}" style="BgsPlayerCard" substyle="BgPlayerCardSmall"/>'
                f'<quad posn="{size * .06} {-size * .06} .01" sizen="{size * .88} {size * .88}"'
                f' style="Icons64x64_1" substyle="Close" action="{ACTION}"/></frame></manialink>')

    async def draw_button(self, aseco, player):
        shown = (self.enabled and self.values['button/enabled'] and
                 player.login not in self.hidden_buttons and not is_score_phase(aseco))
        xml = self.button_xml() if shown else f'<manialink id="{ML_ID}"></manialink>'
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def answer(self, aseco, data):
        if not self.enabled or not self.values['button/enabled'] or len(data) < 3:
            return
        try:
            action = int(data[2])
        except (ValueError, TypeError):
            return
        player = aseco.server.players.get_player(data[1])
        if action == ACTION and player and player.login not in self.hidden_buttons and not is_score_phase(aseco):
            mode = MODES[(MODES.index(self.mode(player)) + 1) % len(MODES)]
            await self.command(aseco, {'author': player, 'params': mode})

    async def widget_visibility(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player is not None:
            if data['visible']:
                self.hidden_buttons.discard(player.login)
            else:
                self.hidden_buttons.add(player.login)
            await self.draw_button(aseco, player)

    async def menu(self, _aseco, menu):
        if not self.enabled:
            return
        menu.addEntry('custommenu', '', True, 'Chat', 'hidechat')
        for mode in MODES:
            menu.addEntry('hidechat', '', True, 'Chat ' + mode, 'hidechat_' + mode, '/chat ' + mode)


APP_CLASS = HideChatApp
APP_INSTANCE = HideChatApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(getattr(aseco, '_base_dir', None))
    APP_INSTANCE.configure(aseco)
    await APP_INSTANCE.refresh(aseco)
