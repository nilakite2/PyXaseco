from __future__ import annotations

from pyxaseco.core.base import Component

from .widgets import bar_widgets as _bars
from .widgets import checkpoint as _checkpoint
from .widgets import clock_tz as _clock
from .widgets import live as _live


def draw_all_race_bars(*args, **kwargs):
    return _bars.draw_all_race_bars(*args, **kwargs)


def draw_all_score_bars(*args, **kwargs):
    return _bars.draw_all_score_bars(*args, **kwargs)


def hide_all_race_bars(*args, **kwargs):
    return _bars.hide_all_race_bars(*args, **kwargs)


def hide_all_score_bars(*args, **kwargs):
    return _bars.hide_all_score_bars(*args, **kwargs)


def _draw_clock_player(*args, **kwargs):
    return _bars._draw_clock_player(*args, **kwargs)


def _draw_playerspectator_all(*args, **kwargs):
    return _bars._draw_playerspectator_all(*args, **kwargs)


def _draw_clock_all(*args, **kwargs):
    return _bars._draw_clock_all(*args, **kwargs)


def _draw_currentranking_all(*args, **kwargs):
    return _bars._draw_currentranking_all(*args, **kwargs)


def _draw_visitors_all(*args, **kwargs):
    return _bars._draw_visitors_all(*args, **kwargs)


def _draw_trackcount_all(*args, **kwargs):
    return _bars._draw_trackcount_all(*args, **kwargs)


def _hide_trackcount(*args, **kwargs):
    return _bars._hide_trackcount(*args, **kwargs)


def _refresh_server_limits(*args, **kwargs):
    return _bars._refresh_server_limits(*args, **kwargs)


def _refresh_visitor_count(*args, **kwargs):
    return _bars._refresh_visitor_count(*args, **kwargs)


def _fetch_live(*args, **kwargs):
    return _live._fetch_live(*args, **kwargs)


def _draw_live_player(*args, **kwargs):
    return _live._draw_live_player(*args, **kwargs)


def _build_live_rankings_window(*args, **kwargs):
    return _live._build_live_rankings_window(*args, **kwargs)


def _refresh_cp_targets_all(*args, **kwargs):
    return _checkpoint._refresh_cp_targets_all(*args, **kwargs)


def _refresh_cp_target_for_player(*args, **kwargs):
    return _checkpoint._refresh_cp_target_for_player(*args, **kwargs)


def _is_player_currently_spectating(*args, **kwargs):
    return _checkpoint._is_player_currently_spectating(*args, **kwargs)


def _resolve_display_login(*args, **kwargs):
    return _checkpoint._resolve_display_login(*args, **kwargs)


def _format_cp_delta(*args, **kwargs):
    return _checkpoint._format_cp_delta(*args, **kwargs)


def _draw_cp_player(*args, **kwargs):
    return _checkpoint._draw_cp_player(*args, **kwargs)


def _draw_cpdelta_player(*args, **kwargs):
    return _checkpoint._draw_cpdelta_player(*args, **kwargs)


def init_clock_tz(*args, **kwargs):
    return _clock.init_clock_tz(*args, **kwargs)


def load_player_tz(*args, **kwargs):
    return _clock.load_player_tz(*args, **kwargs)


def open_clock_window(*args, **kwargs):
    return _clock.open_clock_window(*args, **kwargs)


def open_clock_group(*args, **kwargs):
    return _clock.open_clock_group(*args, **kwargs)


def select_timezone(*args, **kwargs):
    return _clock.select_timezone(*args, **kwargs)


class RecordsEyepieceHudViewsSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.hud_views',
            description='Grouped HUD/widget-facing view surface for Records Eyepiece.',
        )


HUD_VIEWS_SURFACE = RecordsEyepieceHudViewsSurface()


def get_component() -> RecordsEyepieceHudViewsSurface:
    return HUD_VIEWS_SURFACE


__all__ = [
    'draw_all_race_bars',
    'draw_all_score_bars',
    'hide_all_race_bars',
    'hide_all_score_bars',
    '_draw_clock_player',
    '_draw_playerspectator_all',
    '_draw_clock_all',
    '_draw_currentranking_all',
    '_draw_visitors_all',
    '_draw_trackcount_all',
    '_hide_trackcount',
    '_refresh_server_limits',
    '_refresh_visitor_count',
    '_fetch_live',
    '_draw_live_player',
    '_build_live_rankings_window',
    '_refresh_cp_targets_all',
    '_refresh_cp_target_for_player',
    '_is_player_currently_spectating',
    '_resolve_display_login',
    '_format_cp_delta',
    '_draw_cp_player',
    '_draw_cpdelta_player',
    'init_clock_tz',
    'load_player_tz',
    'open_clock_window',
    'open_clock_group',
    'select_timezone',
    'RecordsEyepieceHudViewsSurface',
    'HUD_VIEWS_SURFACE',
    'get_component',
]
