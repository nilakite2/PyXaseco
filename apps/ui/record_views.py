from __future__ import annotations

import importlib
import sys

from pyxaseco.core.base import Component

from apps.records_dedimania import records_widget as _dedi
from apps.records_local import records_widget as _local


ML_LOCAL = _local.ML_LOCAL
ML_DEDI = _dedi.ML_DEDI
ML_SUBWIN = _local.ML_SUBWIN
ML_WINDOW = _local.ML_WINDOW
STAR_MARKER = "$o$s$ff0*$z$fff"


def _optional_view(app, name, empty):
    async def invoke(aseco, *args, **kwargs):
        if app not in (getattr(aseco, 'active_apps', ()) or ()):
            return empty()
        module = importlib.import_module(f'apps.{app}.records_widget')
        return await getattr(module, name)(aseco, *args, **kwargs)
    return invoke


def _build_local_records_window(*args, **kwargs):
    return _local._build_local_records_window(*args, **kwargs)


def _draw_local_player(*args, **kwargs):
    return _local._draw_local_player(*args, **kwargs)


def _build_dedi_records_window(*args, **kwargs):
    return _dedi._build_dedi_records_window(*args, **kwargs)


def _draw_dedi_player(*args, **kwargs):
    return _dedi._draw_dedi_player(*args, **kwargs)


def _get_dedi_records(*args, **kwargs):
    return _dedi._get_dedi_records(*args, **kwargs)


_build_rpg_records_window = _optional_view('records_rpg', '_build_rpg_records_window', str)


_draw_rpg_player = _optional_view('records_rpg', '_draw_rpg_player', lambda: None)


_get_rpg_records = _optional_view('records_rpg', '_get_rpg_records', list)


_get_rpg_track = _optional_view('records_rpg', '_get_rpg_track', lambda: None)


_is_rpg_track_active = _optional_view('records_rpg', '_is_rpg_track_active', bool)


def _rpg_title(*args, **kwargs):
    module = sys.modules.get('apps.records_rpg.records_widget')
    return module._rpg_title(*args, **kwargs) if module else 'RPG Records'


_build_trial_records_window = _optional_view('records_trial', '_build_trial_records_window', str)


_draw_trial_player = _optional_view('records_trial', '_draw_trial_player', lambda: None)


_get_trial_records = _optional_view('records_trial', '_get_trial_records', list)


_get_trial_track = _optional_view('records_trial', '_get_trial_track', lambda: None)


_is_trial_track_active = _optional_view('records_trial', '_is_trial_track_active', bool)


def _trial_title(*args, **kwargs):
    module = sys.modules.get('apps.records_trial.records_widget')
    return module._trial_title(*args, **kwargs) if module else 'Trial Records'


class RecordsEyepieceRecordViewsSurface(Component):
    def __init__(self):
        super().__init__(
            component_id='records_eyepiece.record_views',
            description='Grouped record-provider view surface for Records Eyepiece.',
        )


RECORD_VIEWS_SURFACE = RecordsEyepieceRecordViewsSurface()


def get_component() -> RecordsEyepieceRecordViewsSurface:
    return RECORD_VIEWS_SURFACE


__all__ = [
    'ML_LOCAL',
    'ML_DEDI',
    'ML_SUBWIN',
    'ML_WINDOW',
    'STAR_MARKER',
    '_build_local_records_window',
    '_draw_local_player',
    '_build_dedi_records_window',
    '_draw_dedi_player',
    '_get_dedi_records',
    '_build_rpg_records_window',
    '_draw_rpg_player',
    '_get_rpg_records',
    '_get_rpg_track',
    '_is_rpg_track_active',
    '_rpg_title',
    '_build_trial_records_window',
    '_draw_trial_player',
    '_get_trial_records',
    '_get_trial_track',
    '_is_trial_track_active',
    '_trial_title',
    'RecordsEyepieceRecordViewsSurface',
    'RECORD_VIEWS_SURFACE',
    'get_component',
]
