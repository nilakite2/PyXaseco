"""Optional port of Chris92/TheM's matchOverlay (GPLv2 or later), TMF only."""

import logging
from time import monotonic

from pyxaseco.app_config import (AppSetting, AppSettingsSchema, as_bool, as_float, as_int, as_str,
                                bind_app_settings, clear_app_defaults_cache)
from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
from pyxaseco.core.base import App
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase
from pyxaseco.helpers import strip_colors

from . import views


logger = logging.getLogger(__name__)
POLICY = JobPolicy(capacity=1, deadline_seconds=15)
SCHEMA = AppSettingsSchema(app_id='match_overlay', settings=(
    AppSetting('enabled', True, as_bool, 'Enable the optional Match Overlay app.'),
    AppSetting('autoenable', False, as_bool, 'Start displaying automatically in Team mode.'),
    AppSetting('audience', 'spectators', as_str, 'Audience: all, players or spectators.'),
    AppSetting('refresh_interval', 5, as_int, 'Live score refresh, 2-60 seconds; round changes also refresh.'),
    AppSetting('show_on_score', False, as_bool, 'Also show during the end-of-map score screen.'),
    AppSetting('teams/blue', 'Blue Team', as_str, 'Default name for team 1 / blue.'),
    AppSetting('teams/red', 'Red Team', as_str, 'Default name for team 2 / red.'),
    AppSetting('display/pos_x', -42.5, as_float, 'Overlay X position.'),
    AppSetting('display/pos_y', 45.0, as_float, 'Overlay Y position.'),
    AppSetting('display/width', 85.0, as_float, 'Overlay width, 40-120.'),
))
APP_METADATA = {
    'id': 'match_overlay', 'display_name': 'Match Overlay',
    'description': 'Team-mode live map points and manually managed overall match score.',
    'modules': ['apps/match_overlay/app.py', 'apps/match_overlay/views.py'],
    'entries': ['app/match_overlay'], 'provides': ['feature/match_overlay'],
    'depends_on': ['platform_core', 'ui'],
}


def validate_values(values):
    if values['audience'] not in ('all', 'players', 'spectators'):
        raise ValueError('Match Overlay audience must be all, players or spectators.')
    for key, minimum, maximum in (('refresh_interval', 2, 60), ('display/width', 40, 120)):
        if not minimum <= values[key] <= maximum:
            raise ValueError(f'Match Overlay {key} must be {minimum}-{maximum}.')
    for key in ('teams/blue', 'teams/red'):
        if not values[key].strip() or len(values[key]) > 80:
            raise ValueError('Match Overlay team names must contain 1-80 characters.')
    return values


def validate_config(document, _root):
    section = document.get('match_overlay', {})
    validate_values({setting.key: setting.read(section) for setting in SCHEMA.settings})


def spectator(player):
    return bool(getattr(player, 'isspectator', False) or int(getattr(player, 'spectatorstatus', 0) or 0) % 10)


def team_index(value):
    mapping = {'1': 0, 'blue': 0, '2': 1, 'red': 1}
    if value.lower() not in mapping:
        raise ValueError('Choose team 1/blue or 2/red.')
    return mapping[value.lower()]


def team_scores(rows):
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError('Expected exactly two team ranking entries.')
    result = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Invalid team ranking entry.')
        team, score = row.get('TeamId', index), row.get('Score')
        if type(team) is not int or team not in (0, 1) or team in result or type(score) is not int or score < 0:
            raise ValueError('Invalid or duplicate team identifier/score.')
        result[team] = score
    return (result[0], result[1])


def common_name(players, team):
    names = [strip_colors(str(getattr(player, 'nickname', '') or ''))[:80]
             for player in players if not spectator(player) and getattr(player, 'teamid', -1) == team][:32]
    if len(names) < 2:
        raise ValueError('At least two players are needed to guess a team name; set it manually instead.')
    names.sort(key=len)
    shortest = names[0]
    for size in range(len(shortest), 1, -1):
        for start in range(len(shortest) - size + 1):
            candidate = shortest[start:start + size].strip()
            if len(candidate) >= 2 and all(candidate.casefold() in name.casefold() for name in names[1:]):
                return candidate
    raise ValueError('No common team name found; set it manually instead.')


class MatchOverlayApp(App):
    def __init__(self):
        super().__init__(app_id='match_overlay', display_name='Match Overlay',
                         description=APP_METADATA['description'], depends_on=('platform_core', 'ui'),
                         entry_modules=('app/match_overlay',), settings_schema=SCHEMA)
        self.enabled = self.active = False
        self.values = {}
        self.names = ['Blue Team', 'Red Team']
        self.match_score = [0, 0]
        self.scores = None
        self.stale = False
        self.audience = 'spectators'
        self.last_mode = -1
        self.hidden = set()
        self.dirty = True
        self.next_at = self.warn_at = 0

    def register_runtime(self, aseco):
        aseco.add_chat_command('moverlay', 'Admin/MA controls for the Team match overlay', is_admin=True,
                               app='match_overlay', owner='feature/match_overlay',
                               usage='/moverlay [help|status|enable|disable|team|mscore|to]', category='chat-admin')
        for event, callback in (
            ('onChat_moverlay', self.command), ('onEverySecond', self.tick),
            ('onEndRound', self.round_end), ('onBeginRound', self.round_start),
            ('onNewChallenge2', self.reset), ('onRestartChallenge2', self.reset),
            ('onEndRace', self.score_phase), ('onStatusChangeTo5', self.score_phase),
            ('onEndRaceRanking', self.final_scores), ('onPlayerConnect', self.connect),
            ('onPlayerInfoChanged', self.info), ('onPlayerDisconnect', self.disconnect),
            ('onWidgetVisibilityChanged', self.visibility), ('onUiStyleChanged', self.style),
        ):
            aseco.register_event(event, callback)

    def configuration(self, aseco):
        return validate_values(bind_app_settings(SCHEMA, aseco._base_dir).values)

    def apply_configuration(self, values, aseco):
        self.values, self.enabled = values, values['enabled']
        self.names = [values['teams/blue'], values['teams/red']]
        self.audience = values['audience']
        self.active = self.enabled and values['autoenable'] and self.mode(aseco) == 2
        self.next_at, self.dirty = 0, True

    def mode(self, aseco):
        mode = getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1)
        if mode in range(6):
            self.last_mode = mode
        elif self.last_mode == -1:
            from apps.ui.config import _state
            self.last_mode = _state.last_real_mode
        return self.last_mode

    def showing(self, aseco):
        return (self.enabled and self.active and self.mode(aseco) == 2 and
                (self.values['show_on_score'] or not is_score_phase(aseco)))

    def eligible(self, player):
        from apps.ui.config import _state
        return (player.login not in self.hidden and _state.player_visible.get(player.login, True) and
                (self.audience == 'all' or (self.audience == 'spectators') == spectator(player)))

    async def startup(self, context):
        self.apply_configuration(self.configuration(context.aseco), context.aseco)
        await self.refresh(context.aseco)
        await self.tick(context.aseco)

    async def shutdown(self, context):
        self.enabled = self.active = False
        if context.aseco.jobs.running:
            context.aseco.jobs.service('match_overlay_scores', POLICY).invalidate()
        await self.refresh(context.aseco)
        self.hidden.clear()

    def xml(self):
        return views.render(self.values, self.names, self.match_score, self.scores, self.stale)

    async def draw(self, aseco, player):
        xml = self.xml() if self.showing(aseco) and self.eligible(player) else f'<manialink id="{views.ML_ID}"></manialink>'
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def refresh(self, aseco):
        showing = self.showing(aseco)
        shown, hidden = [], []
        for player in aseco.server.players.all():
            (shown if showing and self.eligible(player) else hidden).append(player.login)
        for recipients, xml in ((shown, self.xml() if showing else ''),
                                (hidden, f'<manialink id="{views.ML_ID}"></manialink>')):
            for start in range(0, len(recipients), 100):
                await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', ','.join(recipients[start:start + 100]), xml, 0, False)

    async def tick(self, aseco, _data=None):
        if not self.showing(aseco) or (not self.dirty and monotonic() < self.next_at):
            return
        if not any(self.eligible(player) for player in aseco.server.players.all()):
            return
        service = aseco.jobs.service('match_overlay_scores', POLICY)
        if service.outstanding:
            return
        self.dirty, self.next_at = False, monotonic() + self.values['refresh_interval']
        job = JobEnvelope.capture(aseco.capture_job_context(), {})

        async def operation(_envelope):
            return team_scores(await aseco.client.query('GetCurrentRanking', 2, 0))

        async def apply(result):
            if not self.showing(aseco):
                return
            if result.status == 'completed':
                self.scores, self.stale = result.value, False
            else:
                self.stale = True
                if monotonic() >= self.warn_at:
                    logger.warning('[MatchOverlay] Team score lookup failed (%s); cached scores retained', result.failure_label)
                    self.warn_at = monotonic() + 60
            await self.refresh(aseco)

        if service.submit(job, operation, apply) != Admission.ACCEPTED:
            self.next_at = monotonic() + self.values['refresh_interval']

    async def round_end(self, aseco, _data=None):
        self.dirty = True
        aseco.jobs.service('match_overlay_scores', POLICY).invalidate()
        await self.tick(aseco)

    async def round_start(self, aseco, _data=None):
        await self.refresh(aseco)
        await self.round_end(aseco)

    async def reset(self, aseco, _data=None):
        aseco.jobs.service('match_overlay_scores', POLICY).invalidate()
        self.scores, self.stale, self.dirty, self.next_at = None, False, True, 0
        if self.mode(aseco) != 2:
            self.active = False
        await self.refresh(aseco)
        await self.tick(aseco)

    async def score_phase(self, aseco, _data=None):
        aseco.jobs.service('match_overlay_scores', POLICY).invalidate()
        self.dirty = True
        await self.refresh(aseco)

    async def final_scores(self, aseco, rankings):
        if not self.enabled or self.mode(aseco) != 2:
            return
        try:
            self.scores, self.stale = team_scores(rankings), False
        except ValueError:
            self.stale = True
        await self.refresh(aseco)

    async def connect(self, aseco, player):
        self.hidden.discard(player.login)
        await self.draw(aseco, player)
        await self.tick(aseco)

    async def info(self, aseco, player):
        await self.draw(aseco, player)
        await self.tick(aseco)

    async def disconnect(self, _aseco, player):
        self.hidden.discard(player.login)

    async def visibility(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player is not None:
            if data['visible']:
                self.hidden.discard(player.login)
            else:
                self.hidden.add(player.login)
            await self.draw(aseco, player)
            await self.tick(aseco)

    async def style(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player is not None:
            await self.draw(aseco, player)

    async def reply(self, aseco, player, text):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors('{#server}> ' + text), player.login)

    async def command(self, aseco, command):
        player = command['author']
        if not (aseco.is_master_admin(player) or aseco.is_admin(player)):
            await self.reply(aseco, player, '{#error}Only Admins and MasterAdmins may manage Match Overlay.')
            return
        parts = str(command.get('params') or '').strip().split()
        action = parts[0].lower() if parts else 'help'
        try:
            if action in ('help', 'about'):
                await self.reply(aseco, player, '/moverlay enable|disable|status; team <1|2|blue|red> <name>; '
                                 'team auto <1|2>; mscore <blue> <red>; to <all|players|spectators>. '
                                 'Port of Chris92/TheM matchOverlay. Overall match score is manual.')
                return
            if not self.enabled:
                raise ValueError('Match Overlay is disabled in app settings.')
            if action == 'status' and len(parts) == 1:
                await self.reply(aseco, player, f'Match Overlay: {"active" if self.active else "inactive"}; '
                    f'audience={self.audience}; match {self.names[0]} {self.match_score[0]} - '
                    f'{self.match_score[1]} {self.names[1]}; Team mode only.')
                return
            if action in ('enable', 'activate') and len(parts) == 1:
                if self.mode(aseco) != 2:
                    raise ValueError('Match Overlay only works in Team mode.')
                self.active, self.dirty, self.next_at = True, True, 0
            elif action == 'disable' and len(parts) == 1:
                self.active = False
                aseco.jobs.service('match_overlay_scores', POLICY).invalidate()
            elif action == 'to' and len(parts) == 2 and parts[1].lower() in ('all', 'players', 'spectators'):
                self.audience = parts[1].lower()
            elif action == 'mscore' and len(parts) == 3:
                scores = [int(value) for value in parts[1:]]
                if any(not 0 <= value <= 999999 for value in scores):
                    raise ValueError('Match scores must be whole numbers from 0 to 999999.')
                self.match_score = scores
            elif action == 'team' and len(parts) >= 3:
                if parts[1].lower() == 'auto' and len(parts) == 3:
                    index = team_index(parts[2])
                    name = common_name(aseco.server.players.all(), index)
                else:
                    index, name = team_index(parts[1]), ' '.join(parts[2:])
                if not name.strip() or len(name) > 80:
                    raise ValueError('Team names must contain 1-80 characters.')
                self.names[index] = name
            else:
                raise ValueError('Unknown command or invalid arguments. Use /moverlay help.')
            await self.refresh(aseco)
            await self.tick(aseco)
            await self.reply(aseco, player, 'Match Overlay updated. Use /moverlay status to review.')
        except ValueError as error:
            await self.reply(aseco, player, '{#error}' + str(error))


APP_CLASS = MatchOverlayApp
APP_INSTANCE = MatchOverlayApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(aseco._base_dir)
    values = APP_INSTANCE.configuration(aseco)
    aseco.jobs.service('match_overlay_scores', POLICY).invalidate()
    APP_INSTANCE.apply_configuration(values, aseco)
    await APP_INSTANCE.refresh(aseco)
    await APP_INSTANCE.tick(aseco)
