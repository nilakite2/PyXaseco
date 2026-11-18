"""Build race HUD samples independently of live widget and game state."""

from pyxaseco.helpers import format_time
from pyxaseco.models import Gameinfo

from . import allbutton, banner, karma, menu
from .challenge_widget import _build_current_challenge_xml
from .config import _state
from .widgets import bar_widgets as bars, score_widgets
from .widgets.checkpoint import _build_cp_count_xml
from .widgets.records_common import _build_record_widget


_LIMITS = {Gameinfo.RNDS: '50 pts.', Gameinfo.TA: '5:00', Gameinfo.TEAM: '7 pts.',
           Gameinfo.LAPS: '3 laps', Gameinfo.STNT: '3:00', Gameinfo.CUP: '100 pts.'}


def _records(aseco, login, mode, names, *, fast_records):
    for identifier, configs in ((91812, _state.local), (91811, _state.dedi), (91813, _state.live)):
        if (identifier == 91811 and mode == Gameinfo.STNT) or (fast_records and identifier != 91813):
            continue
        cfg = configs.get(mode)
        if cfg is None:
            continue
        live = identifier == 91813
        if live and mode == Gameinfo.TEAM:
            entries = [{'rank': False, 'nickname': name, 'score': points, 'self': -1}
                       for name, points in (('Blue Team', '7 pts.'), ('Red Team', '5 pts.'))]
        else:
            entries = []
            for i in range(min(20, cfg.entries)):
                score = 58820 + i * 1370
                if mode == Gameinfo.STNT:
                    score = 980 - i * 25
                elif live:
                    if mode in (Gameinfo.RNDS, Gameinfo.CUP) and cfg.display_type != 'time':
                        limit = 100 if mode == Gameinfo.CUP else 50
                        score = (cfg.fmt.replace('{score}', str(40 - i)).replace('{remaining}', str(limit - 40 + i))
                                 .replace('{pointlimit}', str(limit)))
                    elif mode == Gameinfo.LAPS and cfg.display_type != 'time':
                        score = f'{13 - i}/30'
                    else:
                        score = format_time(score)
                entries.append({'rank': i + 1, 'nickname': names[i % len(names)], 'score': score,
                                'login': login if i == 2 else f'preview{i}', 'self': 0 if i == 2 else -1})
        yield _build_record_widget(aseco=aseco, ml_id=identifier, cfg=cfg, login=login,
                                   entries=entries, online=set(), mode=mode, is_live=live), cfg.enabled


def sample_widgets(aseco, player, mode, track, names, fast):
    if not fast.get('map/enabled'):
        yield _build_current_challenge_xml(track), _state.challenge.enabled
    if not fast.get('menu/enabled'):
        yield menu.preview_menu_button(aseco)
    yield from _records(aseco, player.login, mode, names, fast_records=fast.get('records/enabled'))

    laps = mode == Gameinfo.LAPS
    yield _build_cp_count_xml(13 if laps else 4, 30 if laps else 10), _state.cp.enabled
    if mode in (Gameinfo.RNDS, Gameinfo.TEAM, Gameinfo.LAPS, Gameinfo.CUP):
        points = _state.round_score_cfg.get('gamemodes', {}).get(score_widgets._GM_TAG[mode], {})
        sample = {58820 + i * 1370: [
            {'nickname': name, 'score': format_time(58820 + i * 1370),
             'score_plain': 58820 + i * 1370, 'team': i % 2, 'checkpointid': 1 if i < 3 else 0}
        ] for i, name in enumerate(names)}
        yield score_widgets.build_round_score_widget(aseco, mode=mode, sample=sample), points.get('enabled', False)

    yield karma._build_widget_skeleton(mode), karma._cfg.enabled and karma._cfg.gm_cfg(mode).enabled
    yield karma._build_widget_cups(mode, sample=True), True
    yield allbutton._main_xml(), allbutton.feature_allbutton
    yield banner._build_xml('Sample Server'), banner._enabled
    tz = _state.player_timezone.get(player.login) or _state.clock.default_timezone or 'local'
    for cfg, render, args in (
        (_state.trackcount, bars._build_trackcount_xml, (128,)),
        (_state.gamemode, bars._build_gamemode_xml, (mode, _LIMITS[mode])),
        (_state.visitors, bars._build_visitors_xml, (456,)),
        (_state.player_spectator, bars._build_playerspectator_xml, (8, 2, 40, 16)),
        (_state.ladderlimit, bars._build_ladderlimit_xml, (0, 60000)),
        (_state.current_ranking, bars._build_currentranking_xml,
         ('---', 'FIRST') if mode == Gameinfo.TEAM else ('3/8', 'RANKING')),
        (_state.tmexchange, bars._build_tmexchange_xml, (True, '980' if mode == Gameinfo.STNT else '0:58.82')),
        (_state.toplist, bars._build_toplist_xml, ()),
        (_state.favorite, bars._build_favorite_xml, (False,)),
        (_state.clock, bars._build_clock_xml, (tz, False)),
        (_state.discord_widget, bars._build_discord_xml, ()),
        (_state.force_play_widget, bars._build_force_play_xml, ()),
    ):
        yield render(cfg, *args), cfg.enabled
