"""Private, non-interactive previews of race and score-screen layouts."""

from dataclasses import dataclass
import logging
import xml.etree.ElementTree as ET

from apps.platform_ui.presentation import DECLARATION, SCORE_PREVIEW_PAGE, style_xml
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase
from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from . import allbutton, karma, race_preview, toplists
from .challenge_widget import _build_next_challenge_xml
from .config import _state
from .handlers.events import _apply_custom_ui
from .widgets import bar_widgets, score_widgets


_RECORD_LISTS = (
    ('local_records', score_widgets.ML_LOCAL_SCORE),
    ('dedimania_records', score_widgets.ML_DEDI_SCORE),
    ('top_average_times', score_widgets.ML_AVG_TIMES),
)
_OTHER_LISTS = (
    ('top_rankings', toplists.ML_TOP_RANKINGS),
    ('top_winners', toplists.ML_TOP_WINNERS),
    ('most_records', toplists.ML_MOST_RECORDS),
    ('most_finished', toplists.ML_MOST_FINISHED),
    ('top_playtime', toplists.ML_TOP_PLAYTIME),
    ('top_donators', toplists.ML_TOP_DONATORS),
    ('top_nations', toplists.ML_TOP_NATIONS),
    ('top_tracks', toplists.ML_TOP_TRACKS),
    ('top_voters', toplists.ML_TOP_VOTERS),
    ('top_visitors', toplists.ML_TOP_VISITORS),
    ('top_roundscore', toplists.ML_TOP_ROUNDSCORE),
    ('top_winning_payouts', toplists.ML_TOP_WINNING_PAYOUTS),
    ('top_active_players', toplists.ML_TOP_ACTIVE_PLAYERS),
)
_NAMES = ('Xymph', 'Slig', 'Flo', 'AssemblerManiac', 'Undef', 'FuFi', 'Nila', 'ZiZa')
_TRACK = {'name': 'Sample Stadium Track', 'author': 'Slig', 'env': 'Stadium',
          'mood': 'Day', 'authortime': '0:58.82'}
_EMPTY = f'<manialink id="{SCORE_PREVIEW_PAGE}"></manialink>'
_PAINT_TAGS = {'frame', 'quad', 'label', 'format'}
_INTERACTIVE_ATTRS = {'action', 'actionkey', 'url', 'manialink', 'addplayerid', 'scriptevents'}
logger = logging.getLogger(__name__)

PREVIEW_MODES = {
    'time_attack': (Gameinfo.TA, 'Time Attack'), 'rounds': (Gameinfo.RNDS, 'Rounds'),
    'team': (Gameinfo.TEAM, 'Team'), 'laps': (Gameinfo.LAPS, 'Laps'),
    'stunts': (Gameinfo.STNT, 'Stunts'), 'cup': (Gameinfo.CUP, 'Cup'),
}
_MODE_KEYS = {value: key for key, (value, _) in PREVIEW_MODES.items()}
PREVIEW_PHASES = {'race': 'Race HUD', 'score': 'Score Screen', 'table': 'Alternate Scoretable'}


@dataclass(frozen=True)
class PreviewSelection:
    phase: str = 'score'
    mode_key: str = 'current'

    def resolved_mode_key(self, aseco):
        if self.mode_key != 'current':
            return self.mode_key
        if aseco is None:
            return 'time_attack'
        mode = getattr(aseco.server.gameinfo, 'mode', -1)
        return _MODE_KEYS.get(mode, _MODE_KEYS.get(_state.last_real_mode, 'time_attack'))

    def config_scope(self, aseco):
        return self.resolved_mode_key(aseco), 'race' if self.phase == 'race' else 'score'


def _sample_list(key, identifier, *, records, mode):
    cfg = getattr(_state, f'stl_{key}', {})
    if not cfg:
        return ''
    if not cfg.get('enabled', True):
        cfg = {**cfg, 'title': '[Off] ' + (cfg.get('title') or key.replace('_', ' ').title())}
    count = max(0, min(20, int(cfg.get('entries', 0))))
    step = cfg.get('row_height', _state.line_height)
    width = cfg.get('width', 15.5)
    color = getattr(_state.style, 'score_col_scores', 'DDDF')
    if records:
        height = cfg.get('height') or step * count + 3.3
        return (score_widgets._scoretable_header(identifier, cfg, height)
                + ''.join(score_widgets._scoretable_row(
                    i, i + 1, str(980 - i * 25) if mode == Gameinfo.STNT else format_time(58820 + i * 1370),
                    _NAMES[i % len(_NAMES)],
                    color, '', step, max(2, width - 5.3)) for i in range(count))
                + score_widgets._scoretable_footer())
    return (toplists._stl_header(identifier, cfg, count)
            + ''.join(toplists._stl_row_score_nick(
                i, str(100 - i * 4), _NAMES[i % len(_NAMES)], step, '', color, width)
                for i in range(count))
            + toplists._stl_footer())


def _fast_values(aseco, player):
    styles = aseco.get_service('ui/uistyle')
    fast = aseco.get_service('ui/fast_menu')
    return fast.values if fast and fast.enabled and styles and styles.resolve(player).renderer == 'ui_fast' else {}


def _sample_widgets(aseco, player, mode, track, fast):
    if not fast.get('map/enabled'):
        yield _build_next_challenge_xml(track), _state.challenge.enabled

    score_karma = karma._cfg
    karma_enabled = score_karma.enabled and score_karma.gm_cfg(7).enabled
    yield karma._build_widget_skeleton(7), karma_enabled
    yield karma._build_widget_cups(7, sample=True), True  # Same widget; mark only the skeleton.
    show_reminder = (score_karma.remind_to_vote in ('SCORE', 'ALWAYS')
                     and score_karma.reminder_window_display in ('SCORE', 'ALWAYS'))
    if show_reminder or not score_karma.score_mx_window:
        yield karma._build_reminder_xml(aseco, at_score=True), karma_enabled and show_reminder
    else:
        yield karma._build_mx_window_xml(aseco, 3, track['name']), karma_enabled

    yield bar_widgets._build_next_env_xml(_state.next_env, track['env']), _state.next_env.enabled
    yield (bar_widgets._build_next_gamemode_xml(_state.next_gamemode_widget, mode),
           _state.next_gamemode_widget.enabled)
    yield (bar_widgets._build_eyepiece_score_xml(_state.eyepiece_widget),
           _state.eyepiece_widget.score_enabled)
    yield bar_widgets._build_favorite_xml(_state.favorite, True), _state.favorite.enabled
    tz = _state.player_timezone.get(player.login) or _state.clock.default_timezone or 'local'
    yield bar_widgets._build_clock_xml(_state.clock, tz, at_score=True), _state.clock.enabled
    yield allbutton._main_xml(), allbutton.feature_allbutton

    donation_cfg = _state.donation_cfg
    yield (score_widgets.build_donation_widget(aseco, cfg={**donation_cfg, 'enabled': True}),
           donation_cfg.get('enabled', False))
    if mode != Gameinfo.TEAM:
        payout_cfg = _state.winning_payout_cfg
        ranking = [{'NickName': name, 'BestTime': 58820 + index * 1370}
                   for index, name in enumerate(_NAMES[:3])]
        yield (score_widgets.build_winning_payout_widget(
            aseco, cfg={**payout_cfg, 'enabled': True}, ranking=ranking), payout_cfg.get('enabled', False))


def _display_only(node):
    for attr in tuple(node.attrib):
        if attr.lower() in _INTERACTIVE_ATTRS:
            node.attrib.pop(attr)
    for child in list(node):
        if child.tag not in _PAINT_TAGS:
            node.remove(child)
        else:
            _display_only(child)


def _append_sample(page, markup, palette, enabled=True):
    if not markup:
        return
    # Style the native IDs before combining the panels into one private page.
    try:
        styled = style_xml(markup, palette) if palette else markup
        rendered = ET.fromstring('<preview>' + DECLARATION.sub('', styled) + '</preview>')
    except ET.ParseError:
        logger.debug('[Score preview] Skipped invalid widget markup')
        return
    marked = enabled
    for widget in rendered.iter('manialink'):
        frames = widget.findall('frame')
        for frame in frames:
            pos = frame.get('posn', '0 0').split()
            x, y = pos[:2] if len(pos) >= 2 else ('0', '0')
            try:
                depth = float(pos[2]) if len(pos) >= 3 else 0
            except ValueError:
                depth = 0
            frame.set('posn', f'{x} {y} {depth + 10:g}')
            _display_only(frame)
            if not marked:
                ET.SubElement(frame, 'label', posn='.35 .8 4', sizen='4 1.4',
                              textsize='1', scale='.65', textcolor='FFAF', text='[Off]')
                marked = True
            page.append(frame)


def build_preview(palette=None, *, aseco=None, player=None, table=False, selection=None):
    selection = selection or PreviewSelection('table' if table else 'score')
    phase = selection.phase
    mode, mode_title = PREVIEW_MODES[selection.resolved_mode_key(aseco)]
    track = {**_TRACK, 'authortime': '900 pts.'} if mode == Gameinfo.STNT else _TRACK
    page = ET.Element('manialink', id=SCORE_PREVIEW_PAGE)
    if phase == 'score':
        for records, lists in ((True, _RECORD_LISTS), (False, _OTHER_LISTS)):
            for key, identifier in lists:
                if identifier == score_widgets.ML_DEDI_SCORE and mode == Gameinfo.STNT:
                    continue
                _append_sample(page, _sample_list(key, identifier, records=records, mode=mode), palette)
    if aseco is not None and player is not None:
        fast = _fast_values(aseco, player)
        if phase == 'score':
            samples = _sample_widgets(aseco, player, mode, track, fast)
        elif phase == 'race':
            samples = race_preview.sample_widgets(aseco, player, mode, track, _NAMES, fast)
        else:
            samples = ()
        for markup, enabled in samples:
            _append_sample(page, markup, palette, enabled)
        apps = ('alternate_scoretable',) if phase == 'table' else aseco.active_apps
        for app in apps:
            provider = aseco.get_service(f'ui/score_preview/{app}')
            if provider is not None and (phase == 'table' or app != 'alternate_scoretable'):
                for markup, enabled in provider(aseco, player, track, _NAMES, mode=mode, phase=phase):
                    _append_sample(page, markup, palette, enabled)
    has_panels = len(page) > 0
    notice = ET.SubElement(page, 'frame', posn='0 46 32')
    ET.SubElement(notice, 'quad', sizen='48 2.6', halign='center', bgcolor='122E')
    ET.SubElement(notice, 'label', posn='0 -0.35 0.1', sizen='46 2', halign='center',
                  textsize='1', textcolor='FFFF',
                  text=(f'{PREVIEW_PHASES[phase]} | {mode_title} - ' +
                        ('sample data' if has_panels else 'no panels configured')))
    return ET.tostring(page, encoding='unicode')


class ScoretablePreview:
    def __init__(self):
        self.logins = {}

    def selection(self, player):
        return self.logins.get(player.login)

    def visible(self, player, *, table=None):
        selected = self.selection(player)
        return selected is not None and (table is None or (selected.phase == 'table') == table)

    async def set_visible(self, aseco, player, visible, *, table=False, selection=None):
        if visible and is_score_phase(aseco):
            return False
        styles = aseco.get_service('ui/uistyle')
        presentation = styles.presentation if styles else None
        if visible:
            starting = not self.visible(player)
            self.logins[player.login] = selection or self.selection(player) or PreviewSelection('table' if table else 'score')
            if starting and presentation is not None:
                await presentation.hide_race_for_preview(player)
                await _apply_custom_ui(aseco, player.login)
            await self.refresh(aseco, player)
        elif self.visible(player):
            self.logins.pop(player.login)
            if presentation is not None:
                await presentation.restore_race_after_preview(player)
                await _apply_custom_ui(aseco, player.login)
            await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, _EMPTY, 0, False)
        return True

    async def refresh(self, aseco, player):
        if not self.visible(player) or is_score_phase(aseco):
            return
        styles = aseco.get_service('ui/uistyle')
        preset = styles.resolve(player) if styles else None
        palette = preset.palette if preset is not None and preset.base == 1 else None
        markup = build_preview(palette, aseco=aseco, player=player, selection=self.selection(player))
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, markup, 0, False)

    async def clear(self, aseco, _data=None):
        for login in tuple(self.logins):
            player = aseco.server.players.get_player(login)
            if player is None:
                self.logins.pop(login, None)
            else:
                await self.set_visible(aseco, player, False)

    async def disconnect(self, _aseco, player):
        self.logins.pop(player.login, None)

    async def style_changed(self, aseco, data):
        if (login := data.get('login')) in self.logins:
            player = aseco.server.players.get_player(login)
            if player is not None:
                await self.refresh(aseco, player)


def register(aseco):
    preview = ScoretablePreview()
    aseco.register_service('ui/score_preview', preview, owner='ui')
    aseco.register_event('onEndRace', preview.clear)
    aseco.register_event('onNewChallenge', preview.clear)
    aseco.register_event('onPlayerDisconnect', preview.disconnect)
    aseco.register_event('onUiStyleChanged', preview.style_changed)
