"""Optional FAST-style presentation using PyXaseco's existing UI and services."""

from math import isfinite
from time import monotonic

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_float, as_int, as_str,
    bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase
from apps.platform_ui.uistyle_catalog import Preset

from . import competition, live, providers, views


SCHEMA = AppSettingsSchema(app_id='ui_fast', settings=(
    AppSetting('enabled', True, as_bool, 'Offer FAST in /uistyle list.'),
    AppSetting('preset_id', 8, as_int, 'Unused UI preset ID, at least 2. Classic/Modern IDs are reserved.'),
    AppSetting('refresh_seconds', 3, as_int, 'Refresh cached records every 1-60 seconds; no new API polling.'),
    AppSetting('show_on_score', True, as_bool, 'Keep FAST panels visible on the score screen.'),
    AppSetting('menu/enabled', True, as_bool, 'Use FAST menu; off restores the configured standard menu.'),
    AppSetting('menu/pos_x', -49.9, as_float, 'Menu X position.'),
    AppSetting('menu/pos_y', 47.8, as_float, 'Menu Y position.'),
    AppSetting('menu/width', 23.0, as_float, 'Menu bar width, 21-40.'),
    AppSetting('map/enabled', True, as_bool, 'Use FAST map panel; off restores the configured standard panel.'),
    AppSetting('map/pos_x', 49.05, as_float, 'Map panel X position.'),
    AppSetting('map/pos_y', 48.0, as_float, 'Map panel Y position.'),
    AppSetting('map/width', 15.5, as_float, 'Map panel width, 15.5-40; leaves the existing clock column clear.'),
    AppSetting('records/enabled', True, as_bool, 'Use FAST times panel; off restores standard record widgets.'),
    AppSetting('records/pos_x', 43.1, as_float, 'Times panel X position.'),
    AppSetting('records/pos_y', 21.95, as_float, 'Times panel Y position.'),
    AppSetting('records/width', 21.0, as_float, 'Times panel width, 21-40.'),
    AppSetting('records/entries', 10, as_int, 'Visible records, 1-20; unused rows are omitted.'),
    AppSetting('records/topcount', 3, as_int, 'Pinned leaders; fewer than entries.'),
    AppSetting('records/row_height', 1.8, as_float, 'Record row height, 1.8-2.5.'),
    AppSetting('splits/enabled', True, as_bool, 'Show live checkpoint times and differences in FAST.'),
    AppSetting('splits/pos_x', -23.0, as_float, 'Live splits X position (left edge).'),
    AppSetting('splits/pos_y', 30.7, as_float, 'Live splits Y position.'),
    AppSetting('splits/width', 46.0, as_float, 'Live splits width, 30-80.'),
    AppSetting('splits/comparison', 'best', as_str, 'Initial comparison: best, ideal or reference. Click to cycle.'),
    AppSetting('splits/reference_rank', 1, as_int, 'Record rank in the selected FAST source, 1-10000.'),
    AppSetting('splits/show_position', True, as_bool, 'Live checkpoint position in Rounds, Team, Laps and Cup.'),
    AppSetting('splits/show_gaps', True, as_bool, 'Compare the last shared checkpoint with the leader and nearby racers.'),
    AppSetting('competition/enabled', True, as_bool, 'Offer manual-start Team matches, independent of UI selection.'),
    AppSetting('competition/blue', 'Blue Team', as_str, 'Default Blue team name for new matches.'),
    AppSetting('competition/red', 'Red Team', as_str, 'Default Red team name for new matches.'),
    AppSetting('competition/show_panel', True, as_bool, 'Show match totals/history for FAST users in Team mode.'),
    AppSetting('competition/show_round', True, as_bool, 'Show estimated native Team round points for FAST users.'),
    AppSetting('competition/round_history', True, as_bool, 'Retain individual round results for match exports.'),
    AppSetting('competition/scoring', 'native', as_str, 'New matches: sum native map scores or count map_wins.'),
    AppSetting('competition/target', 0, as_int, 'New matches: stop collecting at this overall target, 0 means manual stop.'),
    AppSetting('competition/win_margin', 1, as_int, 'New matches: minimum overall lead to reach the target; 2 for win by two.'),
    AppSetting('competition/history_rows', 5, as_int, 'Recent counted maps in the FAST panel, 1-10.'),
    AppSetting('competition/pos_x', -64.7, as_float, 'Team match panel X position.'),
    AppSetting('competition/pos_y', 23.65, as_float, 'Team match panel Y position.'),
    AppSetting('competition/width', 28.0, as_float, 'Team match panel width, 21-40.'),
))
APP_METADATA = {
    'id': 'ui_fast', 'display_name': 'FAST UI',
    'description': 'Optional compact FAST-style menu, map, times panels and live checkpoint splits.',
    'modules': ['apps/ui_fast/app.py', 'apps/ui_fast/providers.py', 'apps/ui_fast/views.py',
                'apps/ui_fast/live.py', 'apps/ui_fast/competition.py', 'apps/ui_fast/team_rounds.py',
                'apps/ui_fast/reports.py'],
    'entries': ['app/ui_fast'], 'provides': ['feature/ui_fast', 'feature/team_competition'],
    'depends_on': ['platform_ui', 'ui', 'records_local'],
}


def configuration(section):
    if not isinstance(section, dict):
        raise ValueError('ui_fast must be a TOML table.')
    values = {setting.key: setting.read(section) for setting in SCHEMA.settings}
    if not 2 <= values['preset_id'] <= 2147483647:
        raise ValueError('FAST preset_id must be an unused ID from 2 to 2147483647.')
    if not 1 <= values['refresh_seconds'] <= 60:
        raise ValueError('FAST refresh_seconds must be 1-60.')
    if not 1 <= values['records/entries'] <= 20 or not 0 <= values['records/topcount'] < values['records/entries']:
        raise ValueError('FAST entries must be 1-20; topcount must be non-negative and smaller than entries.')
    for prefix in ('menu', 'map', 'records', 'splits', 'competition'):
        minimum_width = 30 if prefix == 'splits' else 15.5 if prefix == 'map' else 21
        maximum_width = 80 if prefix == 'splits' else 40
        for key, low, high in (('pos_x', -64.7, 64.7), ('pos_y', -48, 48),
                               ('width', minimum_width, maximum_width)):
            value = values[f'{prefix}/{key}']
            if not isfinite(value) or not low <= value <= high:
                raise ValueError(f'FAST {prefix}/{key} must be {low}-{high}.')
    if not isfinite(values['records/row_height']) or not 1.8 <= values['records/row_height'] <= 2.5:
        raise ValueError('FAST row_height must be 1.8-2.5.')
    values['splits/comparison'] = values['splits/comparison'].strip().lower()
    if values['splits/comparison'] not in live.MODES:
        raise ValueError('FAST splits/comparison must be best, ideal or reference.')
    if not 1 <= values['splits/reference_rank'] <= 10000:
        raise ValueError('FAST splits/reference_rank must be 1-10000.')
    if not 1 <= values['competition/history_rows'] <= 10:
        raise ValueError('FAST competition/history_rows must be 1-10.')
    values['competition/scoring'] = values['competition/scoring'].strip().lower()
    if values['competition/scoring'] not in ('native', 'map_wins'):
        raise ValueError('FAST competition/scoring must be native or map_wins.')
    if not 0 <= values['competition/target'] <= competition.MAX_SCORE:
        raise ValueError('FAST competition/target must be 0-2147483647.')
    if not 1 <= values['competition/win_margin'] <= competition.MAX_SCORE:
        raise ValueError('FAST competition/win_margin must be 1-2147483647.')
    for key in ('competition/blue', 'competition/red'):
        if not 1 <= len(values[key].strip()) <= 80 or any(ord(c) < 32 for c in values[key]):
            raise ValueError('FAST competition team names must contain 1-80 characters without line breaks.')
    return values


def validate_config(document, _root):
    configuration(document.get('ui_fast', {}))


class FastUiApp(App):
    def __init__(self):
        super().__init__(app_id='ui_fast', display_name='FAST UI',
                         description=APP_METADATA['description'],
                         depends_on=('platform_ui', 'ui', 'records_local'),
                         entry_modules=('app/ui_fast',), settings_schema=SCHEMA)
        self.enabled = False
        self.values = {}
        self.sources = []
        self.uid = ''
        self.next_at = 0
        self.selected = {}
        self.menus = {}
        self.menu_actions = {}
        self.drawn = set()
        self.splits = live.LiveSplits()
        self.comparisons = {}
        self.hidden_panels = {}
        self.competition = competition.TeamCompetition()

    def register_runtime(self, aseco):
        aseco.add_chat_command('fastui', 'Open the FAST menu or toggle your panels', app='ui_fast',
                               owner='feature/ui_fast', usage='/fastui [panels|toggle <panel>]')
        for event, callback in (
            ('onEverySecond', self.tick), ('onChat_fastui', self.command),
            ('onPlayerConnect2', self.connect), ('onPlayerDisconnect', self.disconnect),
            ('onUiStyleChanged', self.style), ('onWidgetVisibilityChanged', self.style),
            ('onPlayerManialinkPageAnswer', self.answer),
            ('onCheckpoint', self.checkpoint), ('onPlayerFinish1', self.finish),
            ('onPlayerRetire', self.retire), ('onPlayerInfoChanged', self.player_info),
            ('onBeginRound', self.round_start), ('onNewChallenge', self.new_map),
            ('onRestartChallenge', self.round_start),
            ('onSync', self.refresh), ('onNewChallenge2', self.refresh),
            ('onRestartChallenge2', self.refresh), ('onEndRace', self.refresh),
            ('onStatusChangeTo3', self.refresh), ('onStatusChangeTo5', self.refresh),
            ('onLocalRecord', self.refresh), ('onDediRecsLoaded', self.refresh),
            ('onTrialRecordsLoaded', self.refresh), ('onRpgRecordsLoaded', self.refresh),
            ('onWRManiaRecordsLoaded', self.refresh), ('onUltimaniaRecordsLoaded', self.refresh),
            (competition.EVENT, self.refresh),
        ):
            aseco.register_event(event, callback)
        self.competition.register(aseco)

    async def configure(self, aseco):
        bound = await file_io(bind_app_settings, SCHEMA, aseco._base_dir)
        values = configuration(bound.section)
        styles = aseco.get_service('ui/uistyle')
        before = {player.login: styles.resolve(player) for player in aseco.server.players.all()}
        components_changed = any(self.values.get(key) != values[key] for key in
                                 ('menu/enabled', 'map/enabled', 'records/enabled', 'splits/enabled'))
        if values['enabled']:
            styles.register_renderer('ui_fast', Preset(values['preset_id'], 'FAST',
                'Compact FAST menu, map information and switchable record sources.', renderer='ui_fast'), self)
        else:
            styles.unregister_renderer('ui_fast')
        self.values, self.enabled = values, values['enabled']
        self.menus.clear()
        self.menu_actions.clear()
        self.comparisons.clear()
        await self.competition.configure(aseco, values)
        for player in list(aseco.server.players.all()):
            if (before.get(player.login) != styles.resolve(player) or
                    (components_changed and self.active(aseco, player))):
                await styles.changed(player)
        await self.refresh(aseco)

    async def startup(self, context):
        await self.configure(context.aseco)

    async def shutdown(self, context):
        aseco = context.aseco
        styles = aseco.get_service('ui/uistyle')
        affected = [player for player in aseco.server.players.all() if self.active(aseco, player)]
        self.enabled = False
        await self.competition.shutdown(aseco)
        styles.unregister_renderer('ui_fast')
        for player in affected:
            await self.clear(aseco, player)
            await styles.changed(player)
        self.sources.clear()
        self.menus.clear()
        self.menu_actions.clear()
        self.selected.clear()
        self.splits.reset()
        self.comparisons.clear()
        self.hidden_panels.clear()

    def active(self, aseco, player):
        styles = aseco.get_service('ui/uistyle')
        return self.enabled and styles is not None and styles.resolve(player).renderer == 'ui_fast'

    def shown(self, aseco, player):
        from apps.ui.config import _state
        return (self.active(aseco, player) and _state.player_visible.get(player.login, True)
                and (self.values['show_on_score'] or not is_score_phase(aseco)))

    def transform_xml(self, _player, xml):
        return views.suppress(xml, menu=self.values['menu/enabled'], track=self.values['map/enabled'],
                              records=self.values['records/enabled'],
                              live_splits=self.values['splits/enabled']) if self.enabled else xml

    def panel_available(self, panel):
        if panel == 'team':
            return self.competition.enabled and (self.values['competition/show_panel'] or
                                                 self.values['competition/show_round'])
        return self.values.get(panel + '/enabled', False)

    def panel_visible(self, player, panel):
        return self.panel_available(panel) and panel not in self.hidden_panels.get(player.login, ())

    async def send(self, aseco, player, xml):
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def clear(self, aseco, player):
        if player.login in self.drawn:
            await self.send(aseco, player, ''.join(views.empty(page) for page in
                            (views.ML_BAR, views.ML_MAP, views.ML_RECORDS, views.ML_MENU,
                             views.ML_SPLITS, views.ML_TEAM)))
            self.drawn.discard(player.login)
        self.menus.pop(player.login, None)
        self.menu_actions.pop(player.login, None)

    async def tick(self, aseco, _data=None):
        if self.enabled and monotonic() >= self.next_at:
            await self.refresh(aseco)

    async def refresh(self, aseco, _data=None):
        players = list(aseco.server.players.all())
        visible = [player for player in players if self.shown(aseco, player)]
        self.next_at = monotonic() + self.values.get('refresh_seconds', 3)
        uid = str(getattr(aseco.server.challenge, 'uid', '') or '')
        if uid != self.uid:
            self.splits.reset()
            self.sources.clear()
            self.menus.clear()
            self.menu_actions.clear()
            self.uid = uid
        if visible:
            self.sources = await providers.snapshots(aseco)
            self.splits.update_references(aseco, self.sources)
        for player in players:
            await self.draw(aseco, player)

    async def draw(self, aseco, player):
        from apps.ui.config import _state, _effective_mode
        from pyxaseco.models import Gameinfo

        if not self.shown(aseco, player):
            await self.clear(aseco, player)
            return
        if not self.sources:
            return
        position = next((index for index, source in enumerate(self.sources)
                         if source.key == self.selected.get(player.login)), 0)
        source = self.sources[position]
        rows = providers.nearby(source.rows, player.login, self.values['records/entries'],
                                self.values['records/topcount'])
        connected = list(aseco.server.players.all())
        specs = sum(bool(getattr(other, 'isspectator', False) or
                    int(getattr(other, 'spectatorstatus', 0) or 0) % 10) for other in connected)
        mode = _effective_mode(aseco)
        mode_name = {0: 'Rounds', 1: 'TA', 2: 'Team', 3: 'Laps', 4: 'Stunts', 5: 'Cup'}.get(mode, 'Race')
        next_track = getattr(_state, 'next_challenge', None) if is_score_phase(aseco) else None
        xml = (views.bar(self.values, mode_name, len(connected) - specs, specs)
               if self.values['menu/enabled'] else views.empty(views.ML_BAR))
        xml += (views.map_panel(self.values, aseco.server.challenge, next_track)
                if self.panel_visible(player, 'map') else views.empty(views.ML_MAP))
        xml += (views.records(self.values, source, rows, player.login, position, len(self.sources),
                             stunts=mode == Gameinfo.STNT)
                if self.panel_visible(player, 'records') else views.empty(views.ML_RECORDS))
        xml += (self.menu_xml(aseco, player) if self.values['menu/enabled'] and player.login in self.menus
                else views.empty(views.ML_MENU))
        xml += self.splits_xml(aseco, player)
        match = round_ = None
        if mode == Gameinfo.TEAM and self.panel_visible(player, 'team'):
            if self.values['competition/show_panel']:
                match = self.competition.snapshot()
            if self.values['competition/show_round']:
                round_ = self.competition.rounds.snapshot()
                if round_ and is_score_phase(aseco) and not round_['final']:
                    round_ = None
        xml += (views.team_match(self.values, match, round_, player.login) if match or round_
                else views.empty(views.ML_TEAM))
        await self.send(aseco, player, xml)
        self.drawn.add(player.login)

    def splits_xml(self, aseco, player, race=None):
        from apps.ui.widgets.checkpoint import _resolve_display_login
        from pyxaseco.models import Gameinfo

        if (not self.panel_visible(player, 'splits') or not self.shown(aseco, player) or
                is_score_phase(aseco) or aseco.server.gameinfo.mode == Gameinfo.STNT or not self.sources):
            return views.empty(views.ML_SPLITS)
        login = _resolve_display_login(aseco, player.login)
        target = aseco.server.players.get_player(login)
        if target is None or getattr(target, 'retired', False) or getattr(target, 'isspectator', False):
            return views.empty(views.ML_SPLITS)
        source = next((source for source in self.sources if source.key == self.selected.get(player.login)),
                      self.sources[0])
        mode = self.comparisons.get(player.login, self.values['splits/comparison'])
        model = self.splits.model(aseco, login, mode, source, self.values['splits/reference_rank'],
                                  self.values['splits/show_position'], self.values['splits/show_gaps'], race=race)
        return (views.splits(self.values, model, target.nickname if login != player.login else '')
                if model else views.empty(views.ML_SPLITS))

    async def draw_splits(self, aseco):
        race = None
        for player in list(aseco.server.players.all()):
            if self.shown(aseco, player):
                if race is None and (self.values['splits/show_position'] or self.values['splits/show_gaps']):
                    race = self.splits.race_order(aseco)
                await self.send(aseco, player, self.splits_xml(aseco, player, race=race))

    async def checkpoint(self, aseco, data):
        from pyxaseco.models import Gameinfo
        if (self.enabled and self.values['splits/enabled'] and not is_score_phase(aseco) and
                aseco.server.gameinfo.mode != Gameinfo.STNT and self.splits.checkpoint(aseco, data)):
            await self.draw_splits(aseco)

    async def finish(self, aseco, record):
        if self.enabled and self.values['splits/enabled']:
            self.splits.finish(aseco, record)
            self.splits.update_references(aseco, self.sources)
            await self.draw_splits(aseco)

    async def retire(self, aseco, player):
        self.splits.discard(player.login)
        if self.enabled:
            await self.draw_splits(aseco)

    async def player_info(self, aseco, player):
        if getattr(player, 'isspectator', False):
            self.splits.discard(player.login)
        if self.enabled:
            await self.draw_splits(aseco)

    async def round_start(self, aseco, _data=None):
        self.splits.round_start()
        if self.enabled:
            await self.draw_splits(aseco)

    async def new_map(self, aseco, _data=None):
        self.splits.reset()
        self.sources.clear()
        self.menus.clear()
        self.menu_actions.clear()
        self.uid = str(getattr(aseco.server.challenge, 'uid', '') or '')
        if self.enabled:
            await self.draw_splits(aseco)

    def menu_entries(self, aseco, player):
        from apps.ui.menu import _fufi_menu, _allow_menu_entry

        path, page = self.menus.get(player.login, ('0000', 0))
        if _fufi_menu is None:
            return None, [], 0
        # Walk only permission-visible descendants, never arbitrary forged entry IDs.
        def find(node):
            entries = (node.get_valid_entries(player.login) if node is _fufi_menu else
                       node.get_valid_entries(_fufi_menu, player.login))
            entries = [entry for entry in entries if entry.type != 'separator'
                       and _allow_menu_entry(aseco, player, entry)]
            if node.id == path:
                return node, entries
            for entry in entries:
                if entry.is_group():
                    found = find(entry)
                    if found:
                        return found
            return None
        found = find(_fufi_menu)
        if found is None:
            self.menus[player.login] = ('0000', 0)
            return self.menu_entries(aseco, player)
        return *found, page

    def menu_xml(self, aseco, player):
        node, entries, page = self.menu_entries(aseco, player)
        count = max(1, (len(entries) + views.PAGE_SIZE - 1) // views.PAGE_SIZE)
        page = min(max(0, page), count - 1)
        visible = entries[page * views.PAGE_SIZE:(page + 1) * views.PAGE_SIZE]
        self.menu_actions[player.login] = {views.ITEM_BASE + index: entry.id for index, entry in enumerate(visible)}
        self.menus[player.login] = (getattr(node, 'id', '0000'), page)
        title = getattr(node, 'caption', '') or 'Menu'
        return views.menu(self.values, title, visible, page, count)

    async def dispatch(self, aseco, player, command):
        from apps.ui.menu import _fufi_menu
        if _fufi_menu is not None:
            await _fufi_menu.dispatch_chat_command(getattr(player, 'id', 0), player.login, command)
        else:
            name, _, params = command.lstrip('/').partition(' ')
            if aseco.get_command(name):
                await aseco.release_event('onChat_' + name, {'author': player, 'command': name, 'params': params})

    async def command(self, aseco, command):
        player = command['author']
        args = str(command.get('params') or '').lower().split()
        if args and self.active(aseco, player):
            panels = ('map', 'records', 'splits', 'team')
            reply = aseco.get_service('ui/uistyle').reply
            if args == ['panels']:
                states = ', '.join(f"{panel}: " + ('off (server)' if not self.panel_available(panel) else
                                   'on' if self.panel_visible(player, panel) else 'off') for panel in panels)
                await reply(player, states + '. Use /fastui toggle <panel>.')
            elif len(args) == 2 and args[0] == 'toggle' and args[1] in panels:
                panel = args[1]
                if not self.panel_available(panel):
                    await reply(player, 'This FAST panel is disabled in the server settings.')
                    return
                hidden = self.hidden_panels.setdefault(player.login, set())
                hidden.symmetric_difference_update({panel})
                await self.draw(aseco, player)
                await reply(player, f"FAST {panel}: {'off' if panel in hidden else 'on'} for this session.")
            else:
                await reply(player, 'Use /fastui, /fastui panels, or /fastui toggle <map|records|splits|team>.')
            return
        if self.enabled and not self.values['menu/enabled']:
            await aseco.get_service('ui/uistyle').reply(player, 'FAST menu is disabled in the server settings.')
        elif self.shown(aseco, player):
            self.menus[player.login] = ('0000', 0)
            await self.refresh(aseco)
        else:
            await aseco.get_service('ui/uistyle').reply(player, 'Select FAST using /uistyle list and show widgets with F7.')

    async def answer(self, aseco, answer):
        if len(answer) < 3:
            return
        try:
            action = int(answer[2])
        except (ValueError, TypeError):
            return
        if not views.TOGGLE <= action < views.ITEM_BASE + views.PAGE_SIZE:
            return
        player = aseco.server.players.get_player(answer[1])
        if player is None or not self.shown(aseco, player):
            return
        menu_action = (action == views.TOGGLE or views.BACK <= action <= views.STYLES or
                       views.ITEM_BASE <= action < views.ITEM_BASE + views.PAGE_SIZE)
        if menu_action and not self.values['menu/enabled']:
            return
        if action in (views.SOURCE_PREV, views.SOURCE_NEXT, views.OPEN_RECORDS) and not self.panel_visible(player, 'records'):
            return
        if action == views.OPEN_MAP and not self.panel_visible(player, 'map'):
            return
        if action == views.SPLIT_MODE and not self.panel_visible(player, 'splits'):
            return
        if action == views.TOGGLE:
            if player.login in self.menus:
                self.menus.pop(player.login)
            else:
                self.menus[player.login] = ('0000', 0)
        elif action in (views.SOURCE_PREV, views.SOURCE_NEXT, views.OPEN_RECORDS):
            await self.refresh(aseco)
            if not self.sources:
                return
            position = next((index for index, source in enumerate(self.sources)
                             if source.key == self.selected.get(player.login)), 0)
            if action == views.OPEN_RECORDS:
                self.menus.pop(player.login, None)
                await self.dispatch(aseco, player, self.sources[position].command)
            else:
                position = (position + (1 if action == views.SOURCE_NEXT else -1)) % len(self.sources)
                self.selected[player.login] = self.sources[position].key
        elif action == views.OPEN_MAP:
            self.menus.pop(player.login, None)
            from apps.ui.challenge_widget import _open_challenge_window
            await _open_challenge_window(aseco, player.login)
        elif action == views.SPLIT_MODE:
            mode = self.comparisons.get(player.login, self.values['splits/comparison'])
            self.comparisons[player.login] = live.MODES[(live.MODES.index(mode) + 1) % len(live.MODES)]
        elif player.login in self.menus:
            node, entries, page = self.menu_entries(aseco, player)
            if action == views.CLOSE:
                self.menus.pop(player.login, None)
            elif action == views.STYLES:
                self.menus.pop(player.login, None)
                await aseco.get_service('ui/uistyle').picker(player)
            elif action == views.BACK:
                self.menus[player.login] = (getattr(node, 'parentid', '0000'), 0)
            elif action in (views.MENU_PREV, views.MENU_NEXT):
                self.menus[player.login] = (getattr(node, 'id', '0000'), page + (1 if action == views.MENU_NEXT else -1))
            else:
                identifier = self.menu_actions.get(player.login, {}).get(action)
                entry = next((entry for entry in entries if entry.id == identifier), None)
                if entry is None:
                    return
                if entry.is_group():
                    self.menus[player.login] = (entry.id, 0)
                else:
                    from apps.ui.menu import _fufi_menu
                    await _fufi_menu.execute_action(getattr(player, 'id', 0), player.login, entry.id)
                    self.menus.pop(player.login, None)
        await self.draw(aseco, player)

    async def connect(self, aseco, player):
        await self.refresh(aseco)

    async def style(self, aseco, data):
        player = aseco.server.players.get_player(data.get('login'))
        if player is not None:
            if self.shown(aseco, player):
                await self.refresh(aseco)
            else:
                await self.clear(aseco, player)

    async def disconnect(self, aseco, player):
        self.selected.pop(player.login, None)
        self.menus.pop(player.login, None)
        self.menu_actions.pop(player.login, None)
        self.drawn.discard(player.login)
        self.comparisons.pop(player.login, None)
        self.hidden_panels.pop(player.login, None)
        self.splits.discard(player.login)
        if self.enabled:
            await self.draw_splits(aseco)


APP_CLASS = FastUiApp
APP_INSTANCE = FastUiApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(aseco._base_dir)
    await APP_INSTANCE.configure(aseco)
