from __future__ import annotations

from pyxaseco.core.base import Component

from apps.dedimania import records_widget as _dedi
from apps.records_local import records_widget as _local
from apps.records_rpg import records_widget as _rpg
from apps.trial_records import records_widget as _trial


ML_LOCAL = _local.ML_LOCAL
ML_DEDI = _dedi.ML_DEDI
ML_SUBWIN = _local.ML_SUBWIN
ML_WINDOW = _local.ML_WINDOW
STAR_MARKER = _rpg.STAR_MARKER


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


def _build_rpg_records_window(*args, **kwargs):
    return _rpg._build_rpg_records_window(*args, **kwargs)


def _draw_rpg_player(*args, **kwargs):
    return _rpg._draw_rpg_player(*args, **kwargs)


def _get_rpg_records(*args, **kwargs):
    return _rpg._get_rpg_records(*args, **kwargs)


def _get_rpg_track(*args, **kwargs):
    return _rpg._get_rpg_track(*args, **kwargs)


def _is_rpg_track_active(*args, **kwargs):
    return _rpg._is_rpg_track_active(*args, **kwargs)


def _rpg_title(*args, **kwargs):
    return _rpg._rpg_title(*args, **kwargs)


def _build_trial_records_window(*args, **kwargs):
    return _trial._build_trial_records_window(*args, **kwargs)


def _draw_trial_player(*args, **kwargs):
    return _trial._draw_trial_player(*args, **kwargs)


def _get_trial_records(*args, **kwargs):
    return _trial._get_trial_records(*args, **kwargs)


def _get_trial_track(*args, **kwargs):
    return _trial._get_trial_track(*args, **kwargs)


def _is_trial_track_active(*args, **kwargs):
    return _trial._is_trial_track_active(*args, **kwargs)


def _trial_title(*args, **kwargs):
    return _trial._trial_title(*args, **kwargs)


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
