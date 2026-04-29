from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pyxaseco.core.config import parse_xml_file
from pyxaseco.models import Gameinfo
from pyxaseco.core.aseco import PYXASECO_VERSION as CORE_PYXASECO_VERSION

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 1 startup identity / compatibility
# ---------------------------------------------------------------------------

PLUGIN_NAME = 'plugin_records_eyepiece.py'
PLUGIN_VERSION = '1.0-Alpha'
PLUGIN_MANIALINK_PREFIX = '918'
PLUGIN_LINE_HEIGHT = 1.8
MIN_PYXASECO_VERSION = CORE_PYXASECO_VERSION
SUPPORTED_GAME_TOKENS = {'TMF', 'TMFOREVER'}


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WidgetCfg:
    enabled: bool = False
    width: float = 15.5
    pos_x: float = 0.0
    pos_y: float = 0.0
    entries: int = 8
    topcount: int = 3
    display_type: str = 'score'
    fmt: str = '{score} ({remaining})'
    title: str = ''
    icon_style: str = 'Icons128x128_1'
    icon_substyle: str = 'Rankings'


@dataclass
class StyleCfg:
    # Widget race background
    bg_style: str = 'Bgs1InRace'
    bg_substyle: str = 'NavButton'
    # Title bar
    title_style: str = 'BgsPlayerCard'
    title_sub: str = 'BgRacePlayerName'
    # Top-N background quad
    top_style: str = 'BgsPlayerCard'
    top_sub: str = 'BgCardSystem'
    # Self highlight (both sides)
    hi_style: str = 'BgsPlayerCard'
    hi_sub: str = 'BgCardSystem'
    # Other-online highlight
    hi_other_style: str = 'BgsPlayerCard'
    hi_other_sub: str = 'BgCardSystem'
    # Formatting codes prepended to text
    fmt_codes: str = ''
    # Entry text colours (RGBA, no $ prefix stored here)
    col_default: str = 'FFFF'
    col_scores: str = 'DDDF'
    col_top: str = 'FF0F'
    col_better: str = 'F00F'
    col_worse: str = 'CCCF'
    col_self: str = '3F5F'
    # Column background colours
    col_bg_rank: str = 'AAA5'
    col_bg_score: str = 'AAA3'
    col_bg_name: str = 'AAA1'
    # CP widget text colour
    cp_text_color: str = 'FFFF'
    # Score-screen widget styles (WIDGET_SCORE)
    score_bg_style: str = 'BgsPlayerCard'
    score_bg_substyle: str = 'BgRacePlayerName'
    score_title_style: str = 'BgsPlayerCard'
    score_title_sub: str = 'ProgressBar'
    score_fmt_codes: str = ''
    score_col_default: str = 'FFFF'
    score_col_scores: str = 'DDDF'


@dataclass
class ChallengePanelCfg:
    title: str = ''
    icon_style: str = 'Icons128x128_1'
    icon_substyle: str = 'Challenge'
    width: float = 0.0   # 0.0 = inherit from challenge_widget <width>
    pos_x: float = 0.0
    pos_y: float = 0.0


@dataclass
class ImagesCfg:
    no_screenshot: str = ''



@dataclass
class BarWidgetCfg:
    """Config for the small 4.6×6.5 bar/column widgets."""
    enabled: bool = False
    pos_x: float = 0.0
    pos_y: float = 0.0
    text_color: str = 'FC0F'
    bg_style: str = 'BgsPlayerCard'
    bg_substyle: str = 'ProgressBar'


@dataclass
class ClockWidgetCfg:
    enabled: bool = False
    timeformat: str = 'H:i'
    default_timezone: str = 'UTC'
    text_color: str = 'FC0F'
    # Race-state position
    race_pos_x: float = 44.3
    race_pos_y: float = 39.3
    race_bg_style: str = 'BgsPlayerCard'
    race_bg_substyle: str = 'ProgressBar'
    # Score-state position
    score_pos_x: float = 41.05
    score_pos_y: float = 33.2
    score_bg_style: str = 'BgsPlayerCard'
    score_bg_substyle: str = 'BgRacePlayerName'


@dataclass
class FavoriteWidgetCfg:
    enabled: bool = False
    text_color: str = 'FC0F'
    race_pos_x: float = 44.3
    race_pos_y: float = 39.3
    race_bg_style: str = 'BgsPlayerCard'
    race_bg_substyle: str = 'ProgressBar'
    score_pos_x: float = -47.9
    score_pos_y: float = 33.2
    score_bg_style: str = 'BgsPlayerCard'
    score_bg_substyle: str = 'BgRacePlayerName'


@dataclass
class NextEnvWidgetCfg:
    enabled: bool = False
    pos_x: float = 49.1
    pos_y: float = -40.9
    text_color: str = 'FC0F'
    bg_style: str = 'BgsPlayerCard'
    bg_substyle: str = 'BgRacePlayerName'


@dataclass
class NextGamemodeWidgetCfg:
    enabled: bool = False
    pos_x: float = 53.9
    pos_y: float = -40.9
    text_color: str = 'FC0F'
    bg_style: str = 'BgsPlayerCard'
    bg_substyle: str = 'BgRacePlayerName'


@dataclass
class EyepieceWidgetCfg:
    text_color: str = 'FC0F'
    race_enabled: bool = False
    race_pos_x: float = -62.0
    race_pos_y: float = 47.0
    score_enabled: bool = True
    score_pos_x: float = 58.7
    score_pos_y: float = -40.9
    score_bg_style: str = 'BgsPlayerCard'
    score_bg_substyle: str = 'BgRacePlayerName'

@dataclass
class EyepieceState:
    loaded: bool = False
    plugin_name: str = PLUGIN_NAME
    plugin_version: str = PLUGIN_VERSION
    manialink_prefix: str = PLUGIN_MANIALINK_PREFIX
    line_height: float = PLUGIN_LINE_HEIGHT
    refresh_interval: int = 10
    mark_online: bool = True
    style: StyleCfg = field(default_factory=StyleCfg)
    images: ImagesCfg = field(default_factory=ImagesCfg)
    challenge: WidgetCfg = field(default_factory=WidgetCfg)
    challenge_last: WidgetCfg = field(default_factory=WidgetCfg)
    challenge_current: WidgetCfg = field(default_factory=WidgetCfg)
    challenge_next: WidgetCfg = field(default_factory=WidgetCfg)
    local: dict = field(default_factory=dict)
    dedi: dict = field(default_factory=dict)
    live: dict = field(default_factory=dict)
    cp: WidgetCfg = field(default_factory=WidgetCfg)

    # Per-player runtime state
    player_visible: dict = field(default_factory=dict)  # login -> bool
    player_cp_idx: dict = field(default_factory=dict)   # login -> int
    player_cp_lap: dict = field(default_factory=dict)   # login -> int
    player_cp_delta: dict = field(default_factory=dict)  # login -> formatted delta text
    player_cp_target_mode: dict = field(default_factory=dict)   # login -> 'Local'|'Dedi'|''
    player_cp_target_name: dict = field(default_factory=dict)   # login -> label text
    player_cp_target_checks: dict = field(default_factory=dict) # login -> list[int]
    player_best: dict = field(default_factory=dict)  # login -> int (best score this map)

    # Dirty-flag caches — skip ML send if unchanged
    player_local_digest: dict = field(default_factory=dict)
    player_dedi_digest: dict = field(default_factory=dict)
    player_live_digest: dict = field(default_factory=dict)

    # Shared live-rankings cache
    live_cache: list = field(default_factory=list)
    next_refresh: float = 0.0

    # Last confirmed real game mode (0-5). Substituted for mode 7 (Score screen)
    # so widgets keep their correct positions during the between-rounds score phase.
    last_real_mode: int = -1

    # Challenge tracking
    last_challenge: dict = field(default_factory=dict)
    # Cached next-track info dict populated in _on_end_race
    next_challenge: dict = field(default_factory=dict)
    challenge_show_next: bool = False

    # Custom UI flags
    custom_ui_enabled: bool = True
    custom_ui_net_infos: bool = True
    custom_ui_chat: bool = True
    custom_ui_checkpoint_list: bool = True
    custom_ui_round_scores: bool = True
    custom_ui_scoretable: bool = True

    # ── Bar/column widgets (Phase 2) ──────────────────────────────────────
    trackcount: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    gamemode: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    player_spectator: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    ladderlimit: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    current_ranking: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    visitors: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    tmexchange: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    toplist: BarWidgetCfg = field(default_factory=BarWidgetCfg)
    favorite: FavoriteWidgetCfg = field(default_factory=FavoriteWidgetCfg)
    clock: ClockWidgetCfg = field(default_factory=ClockWidgetCfg)

    # ── Score-only bar widgets ────────────────────────────────────────────
    next_env: NextEnvWidgetCfg = field(default_factory=NextEnvWidgetCfg)
    next_gamemode_widget: NextGamemodeWidgetCfg = field(default_factory=NextGamemodeWidgetCfg)
    eyepiece_widget: EyepieceWidgetCfg = field(default_factory=EyepieceWidgetCfg)

    # Per-player timezone preference (login -> tz string)
    player_timezone: dict = field(default_factory=dict)

    # ── Phase 3: RoundScore ──────────────────────────────────────────────
    round_scores: dict = field(default_factory=dict)     # score_ms -> [entry]
    round_score_pb: dict = field(default_factory=dict)   # login -> best_ms
    round_score_cfg: dict = field(default_factory=dict)  # parsed XML config

    # ── Phase 4: Score-screen list widgets ──────────────────────────────
    avg_times: dict = field(default_factory=dict)         # login -> [int]
    stl_local_records: dict = field(default_factory=dict)
    stl_dedimania_records: dict = field(default_factory=dict)
    stl_top_average_times: dict = field(default_factory=dict)
    stl_top_rankings: dict = field(default_factory=dict)
    stl_top_winners: dict = field(default_factory=dict)
    stl_most_records: dict = field(default_factory=dict)
    stl_most_finished: dict = field(default_factory=dict)
    stl_top_playtime: dict = field(default_factory=dict)
    stl_top_donators: dict = field(default_factory=dict)
    stl_top_nations: dict = field(default_factory=dict)
    stl_top_tracks: dict = field(default_factory=dict)
    stl_top_voters: dict = field(default_factory=dict)
    stl_top_visitors: dict = field(default_factory=dict)
    donation_cfg: dict = field(default_factory=dict)
    winning_payout_cfg: dict = field(default_factory=dict)
    _rpoints_cache: list = field(default_factory=list)

    # Server counts (refreshed via onEverySecond)
    server_max_players: int = 0
    server_max_spectators: int = 0

    # Cached visitor count from DB
    visitor_count: int = 0




_state = EyepieceState()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _get_node_value(block, key: str, default=''):
    if not isinstance(block, dict):
        return default
    value = block.get(key.upper(), [default])
    return value[0] if value else default


def _get_bool(block, key: str, default: bool = False) -> bool:
    raw = _get_node_value(block, key, 'true' if default else 'false')
    return str(raw).strip().upper() == 'TRUE'


def _get_int(block, key: str, default: int = 0) -> int:
    try:
        return int(float(_get_node_value(block, key, default)))
    except Exception:
        return default


def _get_float(block, key: str, default: float = 0.0) -> float:
    try:
        return float(_get_node_value(block, key, default))
    except Exception:
        return default


def _parse_gm_widgets(root, key: str, default_title: str, *, live: bool = False) -> dict:
    mapping = {
        'ROUNDS': Gameinfo.RNDS,
        'TIME_ATTACK': Gameinfo.TA,
        'TEAM': Gameinfo.TEAM,
        'LAPS': Gameinfo.LAPS,
        'STUNTS': Gameinfo.STNT,
        'CUP': Gameinfo.CUP,
        'SCORE': Gameinfo.SCOR,  # Score screen (mode 7) — optional XML block
    }

    block = _get_node_value(root, key, {})
    gm_block = _get_node_value(block, 'GAMEMODE', {})
    result = {}

    for name, mode in mapping.items():
        sub = _get_node_value(gm_block, name, {})
        width = max(15.5, _get_float(block, 'WIDTH', 15.5))
        entries = max(1, _get_int(sub, 'ENTRIES', 8))
        topcount = max(1, _get_int(sub, 'TOPCOUNT', 3))
        if live and mode == Gameinfo.TEAM:
            entries = 2
            topcount = 2
        elif topcount >= entries:
            topcount = max(1, entries - 1)

        cfg = WidgetCfg(
            enabled=_get_bool(sub, 'ENABLED', False),
            width=width,
            pos_x=_get_float(sub, 'POS_X', 49.2),
            pos_y=_get_float(sub, 'POS_Y', 0.0),
            entries=entries,
            topcount=topcount,
            title=str(_get_node_value(block, 'TITLE', default_title)),
            icon_style=str(_get_node_value(block, 'ICON_STYLE', 'Icons128x128_1')),
            icon_substyle=str(_get_node_value(block, 'ICON_SUBSTYLE', 'Rankings')),
        )
        if live:
            cfg.display_type = str(_get_node_value(sub, 'DISPLAY_TYPE', 'scores')).strip().lower()
            cfg.fmt = str(_get_node_value(sub, 'FORMAT', '{score} ({remaining})'))
        result[mode] = cfg

    return result



def _effective_mode(aseco: 'Aseco') -> int:
    """
    Return the game mode to use for widget config lookup and rendering.

    During the score-screen phase between rounds the dedicated server reports
    GameMode=7 (Gameinfo.SCOR).  No widget config exists for that value, so
    we fall back to the last known real playable mode (0-5) stored in
    _state.last_real_mode.  This keeps all widgets visible and correctly
    positioned on the OnScore / score-screen phase in Rounds and Cup modes.

    Call sites that deal with actual gameplay physics (OnPlayerFinish, etc.)
    should use gameinfo.mode directly; this helper is for display/layout only.
    """
    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    if mode == Gameinfo.SCOR:
        real = _state.last_real_mode
        return real if real >= 0 else mode
    if 0 <= mode <= 5:
        _state.last_real_mode = mode
    return mode


def _load_config(aseco: 'Aseco') -> None:
    global _state

    # Try multiple locations for records_eyepiece.xml so it is found
    # regardless of where the user runs main.py from:
    #   1. Alongside config.xml (_base_dir) — the documented location
    #   2. Current working directory — if running from a different folder
    #   3. Alongside this config.py file (inside the plugin package)
    _candidates = [
        Path(getattr(aseco, '_base_dir', '.')).resolve() / 'records_eyepiece.xml',
        Path('.').resolve() / 'records_eyepiece.xml',
        Path(__file__).resolve().parent.parent.parent / 'records_eyepiece.xml',
    ]
    path = None
    raw = {}
    for _candidate in _candidates:
        if _candidate.exists():
            path = _candidate
            raw = parse_xml_file(path)
            if raw:
                logger.info('[Records-Eyepiece] Loaded config from %s', path)
                break
    if not raw:
        logger.error(
            '[Records-Eyepiece] Could not find or parse records_eyepiece.xml!\n'
            '  Searched:\n%s\n'
            '  Place records_eyepiece.xml next to config.xml and plugins.xml.',
            '\n'.join(f'    {c}' for c in _candidates)
        )
        _state.loaded = True
        return

    root = raw.get('RECORDS_EYEPIECE', {})

    images_block = _get_node_value(root, 'IMAGES', {})
    _state.images = ImagesCfg(
        no_screenshot=str(_get_node_value(images_block, 'NO_SCREENSHOT', ''))
    )

    # Style -> WIDGET_RACE colours/styles
    style_block = _get_node_value(root, 'STYLE', {})
    widget_race = _get_node_value(style_block, 'WIDGET_RACE', {})
    colors = _get_node_value(widget_race, 'COLORS', {})

    _state.style = StyleCfg(
        bg_style=str(_get_node_value(widget_race, 'BACKGROUND_STYLE', 'Bgs1InRace')),
        bg_substyle=str(_get_node_value(widget_race, 'BACKGROUND_SUBSTYLE', 'NavButton')),
        title_style=str(_get_node_value(widget_race, 'TITLE_STYLE', 'BgsPlayerCard')),
        title_sub=str(_get_node_value(widget_race, 'TITLE_SUBSTYLE', 'BgRacePlayerName')),
        top_style=str(_get_node_value(widget_race, 'TOP_STYLE', 'BgsPlayerCard')),
        top_sub=str(_get_node_value(widget_race, 'TOP_SUBSTYLE', 'BgCardSystem')),
        hi_style=str(_get_node_value(widget_race, 'HIGHLITE_SELF_STYLE', 'BgsPlayerCard')),
        hi_sub=str(_get_node_value(widget_race, 'HIGHLITE_SELF_SUBSTYLE', 'BgCardSystem')),
        hi_other_style=str(_get_node_value(widget_race, 'HIGHLITE_OTHER_STYLE', 'BgsPlayerCard')),
        hi_other_sub=str(_get_node_value(widget_race, 'HIGHLITE_OTHER_SUBSTYLE', 'BgCardSystem')),
        fmt_codes=str(_get_node_value(widget_race, 'FORMATTING_CODES', '')),
        col_default=str(_get_node_value(colors, 'DEFAULT', 'FFFF')),
        col_scores=str(_get_node_value(colors, 'SCORES', 'DDDF')),
        col_top=str(_get_node_value(colors, 'TOP', 'FF0F')),
        col_better=str(_get_node_value(colors, 'BETTER', 'F00F')),
        col_worse=str(_get_node_value(colors, 'WORSE', 'CCCF')),
        col_self=str(_get_node_value(colors, 'SELF', '3F5F')),
        col_bg_rank=str(_get_node_value(colors, 'BACKGROUND_RANK', 'AAA5')),
        col_bg_score=str(_get_node_value(colors, 'BACKGROUND_SCORE', 'AAA3')),
        col_bg_name=str(_get_node_value(colors, 'BACKGROUND_NAME', 'AAA1')),
        cp_text_color=str(
            _get_node_value(
                _get_node_value(root, 'CHECKPOINTCOUNT_WIDGET', {}),
                'TEXT_COLOR',
                'FFFF',
            )
        ),
    )

    # Style -> WIDGET_SCORE (score-screen variants)
    widget_score = _get_node_value(style_block, 'WIDGET_SCORE', {})
    score_colors = _get_node_value(widget_score, 'COLORS', {})
    _state.style.score_bg_style    = str(_get_node_value(widget_score, 'BACKGROUND_STYLE', 'BgsPlayerCard'))
    _state.style.score_bg_substyle = str(_get_node_value(widget_score, 'BACKGROUND_SUBSTYLE', 'BgRacePlayerName'))
    _state.style.score_title_style = str(_get_node_value(widget_score, 'TITLE_STYLE', 'BgsPlayerCard'))
    _state.style.score_title_sub   = str(_get_node_value(widget_score, 'TITLE_SUBSTYLE', 'ProgressBar'))
    _state.style.score_fmt_codes   = str(_get_node_value(widget_score, 'FORMATTING_CODES', ''))
    _state.style.score_col_default = str(_get_node_value(score_colors, 'DEFAULT', 'FFFF'))
    _state.style.score_col_scores  = str(_get_node_value(score_colors, 'SCORES', 'DDDF'))

    # Features
    features = _get_node_value(root, 'FEATURES', {})
    _state.refresh_interval = max(1, _get_int(features, 'REFRESH_INTERVAL', 10))
    _state.mark_online = _get_bool(features, 'MARK_ONLINE_PLAYER_RECORDS', True)

    # Custom UI
    custom_ui = _get_node_value(root, 'CUSTOM_UI', {})
    _state.custom_ui_enabled = _get_bool(custom_ui, 'ENABLED', True)
    _state.custom_ui_net_infos = _get_bool(custom_ui, 'NET_INFOS', True)
    _state.custom_ui_chat = _get_bool(custom_ui, 'CHAT', True)
    _state.custom_ui_checkpoint_list = _get_bool(custom_ui, 'CHECKPOINT_LIST', True)
    _state.custom_ui_round_scores = _get_bool(custom_ui, 'ROUND_SCORES', True)
    _state.custom_ui_scoretable = _get_bool(custom_ui, 'SCORETABLE', True)

    # Challenge widget
    challenge_widget = _get_node_value(root, 'CHALLENGE_WIDGET', {})
    challenge_race = _get_node_value(challenge_widget, 'RACE', {})
    challenge_icons = _get_node_value(challenge_widget, 'ICONS', {})
    challenge_titles = _get_node_value(challenge_widget, 'TITLE', {})

    last_track_icons = _get_node_value(challenge_icons, 'LAST_TRACK', {})
    current_track_icons = _get_node_value(challenge_icons, 'CURRENT_TRACK', {})
    next_track_icons = _get_node_value(challenge_icons, 'NEXT_TRACK', {})

    _state.challenge = WidgetCfg(
        enabled=_get_bool(challenge_widget, 'ENABLED', True),
        width=_get_float(challenge_widget, 'WIDTH', 15.5),
        pos_x=_get_float(challenge_race, 'POS_X', 49.05),
        pos_y=_get_float(challenge_race, 'POS_Y', 48.0),
        title=str(_get_node_value(challenge_titles, 'CURRENT_TRACK', 'Challenge')),
        icon_style=str(_get_node_value(current_track_icons, 'ICON_STYLE', 'Icons128x128_1')),
        icon_substyle=str(_get_node_value(current_track_icons, 'ICON_SUBSTYLE', 'Challenge')),
    )

    _state.challenge_last = ChallengePanelCfg(
        title=str(_get_node_value(challenge_titles, 'LAST_TRACK', 'Last Track')),
        icon_style=str(_get_node_value(last_track_icons, 'ICON_STYLE', 'Icons128x128_1')),
        icon_substyle=str(_get_node_value(last_track_icons, 'ICON_SUBSTYLE', 'Challenge')),
    )

    _state.challenge_current = ChallengePanelCfg(
        title=str(_get_node_value(challenge_titles, 'CURRENT_TRACK', 'Current Track')),
        icon_style=str(_get_node_value(current_track_icons, 'ICON_STYLE', 'Icons128x128_1')),
        icon_substyle=str(_get_node_value(current_track_icons, 'ICON_SUBSTYLE', 'Challenge')),
    )

    challenge_score = _get_node_value(challenge_widget, 'SCORE', {})
    _state.challenge_next = ChallengePanelCfg(
        title=str(_get_node_value(challenge_titles, 'NEXT_TRACK', 'Next Track')),
        icon_style=str(_get_node_value(next_track_icons, 'ICON_STYLE', 'Icons128x128_1')),
        icon_substyle=str(_get_node_value(next_track_icons, 'ICON_SUBSTYLE', 'Challenge')),
        width=_get_float(challenge_score, 'WIDTH', 0.0),
        pos_x=_get_float(challenge_score, 'POS_X', _state.challenge.pos_x),
        pos_y=_get_float(challenge_score, 'POS_Y', _state.challenge.pos_y),
    )

    # CP widget
    cp = _get_node_value(root, 'CHECKPOINTCOUNT_WIDGET', {})
    _state.cp = WidgetCfg(
        enabled=_get_bool(cp, 'ENABLED', True),
        pos_x=_get_float(cp, 'POS_X', -7.9),
        pos_y=_get_float(cp, 'POS_Y', -34.1),
        title='Checkpoints',
    )

    # Per-gamemode record widgets
    _state.local = _parse_gm_widgets(root, 'LOCAL_RECORDS', 'Local Records')
    _state.dedi = _parse_gm_widgets(root, 'DEDIMANIA_RECORDS', 'Dedimania Records')
    _state.live = _parse_gm_widgets(root, 'LIVE_RANKINGS', 'Live Rankings', live=True)

    # Stunts has no Dedimania
    if Gameinfo.STNT in _state.dedi:
        _state.dedi[Gameinfo.STNT].enabled = False

    # ── Bar widgets (Phase 2) ─────────────────────────────────────────────

    def _bar(xml_key, defaults):
        blk = _get_node_value(root, xml_key, {})
        return BarWidgetCfg(
            enabled=_get_bool(blk, 'ENABLED', defaults.get('enabled', False)),
            pos_x=_get_float(blk, 'POS_X', defaults.get('pos_x', 0.0)),
            pos_y=_get_float(blk, 'POS_Y', defaults.get('pos_y', 0.0)),
            text_color=str(_get_node_value(blk, 'TEXT_COLOR', defaults.get('text_color', 'FC0F'))),
            bg_style=str(_get_node_value(blk, 'BACKGROUND_STYLE', defaults.get('bg_style', 'BgsPlayerCard'))),
            bg_substyle=str(_get_node_value(blk, 'BACKGROUND_SUBSTYLE', defaults.get('bg_substyle', 'ProgressBar'))),
        )

    _state.trackcount = _bar('TRACKCOUNT_WIDGET', {
        'enabled': True, 'pos_x': 44.5, 'pos_y': 48.0})
    _state.gamemode = _bar('GAMEMODE_WIDGET', {
        'pos_x': -59.05, 'pos_y': 39.8})
    _state.player_spectator = _bar('PLAYER_SPECTATOR_WIDGET', {
        'pos_x': -54.25, 'pos_y': 39.8})
    _state.ladderlimit = _bar('LADDERLIMIT_WIDGET', {
        'pos_x': -63.85, 'pos_y': 39.8})
    _state.current_ranking = _bar('CURRENT_RANKING_WIDGET', {
        'pos_x': -49.45, 'pos_y': 39.8})
    _state.visitors = _bar('VISITORS_WIDGET', {
        'pos_x': 39.5, 'pos_y': 39.3})
    _state.tmexchange = _bar('TMEXCHANGE_WIDGET', {
        'pos_x': 25.1, 'pos_y': 39.3})
    _state.toplist = _bar('TOPLIST_WIDGET', {
        'pos_x': 29.9, 'pos_y': 39.3})

    # Favorite widget (has race + score positions)
    fav_blk = _get_node_value(root, 'FAVORITE_WIDGET', {})
    fav_race = _get_node_value(fav_blk, 'RACE', {})
    fav_score = _get_node_value(fav_blk, 'SCORE', {})
    _state.favorite = FavoriteWidgetCfg(
        enabled=_get_bool(fav_blk, 'ENABLED', False),
        text_color=str(_get_node_value(fav_blk, 'TEXT_COLOR', 'FC0F')),
        race_pos_x=_get_float(fav_race, 'POS_X', 44.3),
        race_pos_y=_get_float(fav_race, 'POS_Y', 39.3),
        race_bg_style=str(_get_node_value(fav_race, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        race_bg_substyle=str(_get_node_value(fav_race, 'BACKGROUND_SUBSTYLE', 'ProgressBar')),
        score_pos_x=_get_float(fav_score, 'POS_X', -47.9),
        score_pos_y=_get_float(fav_score, 'POS_Y', 33.2),
        score_bg_style=str(_get_node_value(fav_score, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        score_bg_substyle=str(_get_node_value(fav_score, 'BACKGROUND_SUBSTYLE', 'BgRacePlayerName')),
    )

    # Clock widget
    clk_blk = _get_node_value(root, 'CLOCK_WIDGET', {})
    clk_race = _get_node_value(clk_blk, 'RACE', {})
    clk_score = _get_node_value(clk_blk, 'SCORE', {})
    _state.clock = ClockWidgetCfg(
        enabled=_get_bool(clk_blk, 'ENABLED', False),
        timeformat=str(_get_node_value(clk_blk, 'TIMEFORMAT', 'H:i')),
        default_timezone=str(_get_node_value(clk_blk, 'DEFAULT_TIMEZONE', 'UTC')),
        text_color=str(_get_node_value(clk_blk, 'TEXT_COLOR', 'FC0F')),
        race_pos_x=_get_float(clk_race, 'POS_X', 44.3),
        race_pos_y=_get_float(clk_race, 'POS_Y', 39.3),
        race_bg_style=str(_get_node_value(clk_race, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        race_bg_substyle=str(_get_node_value(clk_race, 'BACKGROUND_SUBSTYLE', 'ProgressBar')),
        score_pos_x=_get_float(clk_score, 'POS_X', 41.05),
        score_pos_y=_get_float(clk_score, 'POS_Y', 33.2),
        score_bg_style=str(_get_node_value(clk_score, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        score_bg_substyle=str(_get_node_value(clk_score, 'BACKGROUND_SUBSTYLE', 'BgRacePlayerName')),
    )

    # Score-only bar widgets
    nev_blk = _get_node_value(root, 'NEXT_ENVIRONMENT_WIDGET', {})
    _state.next_env = NextEnvWidgetCfg(
        enabled=_get_bool(nev_blk, 'ENABLED', True),
        pos_x=_get_float(nev_blk, 'POS_X', 49.1),
        pos_y=_get_float(nev_blk, 'POS_Y', -40.9),
        text_color=str(_get_node_value(nev_blk, 'TEXT_COLOR', 'FC0F')),
        bg_style=str(_get_node_value(nev_blk, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        bg_substyle=str(_get_node_value(nev_blk, 'BACKGROUND_SUBSTYLE', 'BgRacePlayerName')),
    )

    ngm_blk = _get_node_value(root, 'NEXT_GAMEMODE_WIDGET', {})
    _state.next_gamemode_widget = NextGamemodeWidgetCfg(
        enabled=_get_bool(ngm_blk, 'ENABLED', True),
        pos_x=_get_float(ngm_blk, 'POS_X', 53.9),
        pos_y=_get_float(ngm_blk, 'POS_Y', -40.9),
        text_color=str(_get_node_value(ngm_blk, 'TEXT_COLOR', 'FC0F')),
        bg_style=str(_get_node_value(ngm_blk, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        bg_substyle=str(_get_node_value(ngm_blk, 'BACKGROUND_SUBSTYLE', 'BgRacePlayerName')),
    )

    ep_blk = _get_node_value(root, 'EYEPIECE_WIDGET', {})
    ep_race = _get_node_value(ep_blk, 'RACE', {})
    ep_score = _get_node_value(ep_blk, 'SCORE', {})
    _state.eyepiece_widget = EyepieceWidgetCfg(
        text_color=str(_get_node_value(ep_blk, 'TEXT_COLOR', 'FC0F')),
        race_enabled=_get_bool(ep_race, 'ENABLED', False),
        race_pos_x=_get_float(ep_race, 'POS_X', -62.0),
        race_pos_y=_get_float(ep_race, 'POS_Y', 47.0),
        score_enabled=_get_bool(ep_score, 'ENABLED', True),
        score_pos_x=_get_float(ep_score, 'POS_X', 58.7),
        score_pos_y=_get_float(ep_score, 'POS_Y', -40.9),
        score_bg_style=str(_get_node_value(ep_score, 'BACKGROUND_STYLE', 'BgsPlayerCard')),
        score_bg_substyle=str(_get_node_value(ep_score, 'BACKGROUND_SUBSTYLE', 'BgRacePlayerName')),
    )

    # ── Phase 3: round_score config ──────────────────────────────────────
    rs_node = _get_node_value(root, 'ROUND_SCORE', {})
    rs_gm   = _get_node_value(rs_node, 'GAMEMODE', {})

    def _rs_gm(tag: str) -> dict:
        gm_node = _get_node_value(rs_gm, tag.upper(), {})
        if not gm_node:
            return {'enabled': False, 'race': {}, 'warmup': {}}
        enabled = _get_bool(gm_node, 'ENABLED', False)
        race_n  = _get_node_value(gm_node, 'RACE', {})
        warm_n  = _get_node_value(gm_node, 'WARMUP', {})
        return {
            'enabled': enabled,
            'race': {'pos_x': _get_float(race_n,'POS_X',49.2),'pos_y': _get_float(race_n,'POS_Y',17.8),'entries': _get_int(race_n,'ENTRIES',14),'topcount': _get_int(race_n,'TOPCOUNT',3)},
            'warmup': {'pos_x': _get_float(warm_n,'POS_X',49.2),'pos_y': _get_float(warm_n,'POS_Y',10.7),'entries': _get_int(warm_n,'ENTRIES',10),'topcount': _get_int(warm_n,'TOPCOUNT',3)},
        }

    race_op = _get_node_value(rs_node, 'RACE', {})
    warm_op = _get_node_value(rs_node, 'WARMUP', {})
    _state.round_score_cfg = {
        'title':  str(_get_node_value(rs_node, 'TITLE', 'Round Score')),
        'width':  max(20.5, _get_float(rs_node, 'WIDTH', 20.5)),
        'race':   {'icon_style': str(_get_node_value(race_op,'ICON_STYLE','Icons64x64_1')), 'icon_substyle': str(_get_node_value(race_op,'ICON_SUBSTYLE','RestartRace'))},
        'warmup': {'icon_style': str(_get_node_value(warm_op,'ICON_STYLE','BgRaceScore2')), 'icon_substyle': str(_get_node_value(warm_op,'ICON_SUBSTYLE','Warmup'))},
        'gamemodes': {'rounds': _rs_gm('rounds'),'time_attack': _rs_gm('time_attack'),'team': _rs_gm('team'),'laps': _rs_gm('laps'),'stunts': _rs_gm('stunts'),'cup': _rs_gm('cup')},
    }

    if any(gm.get('enabled', False) for gm in _state.round_score_cfg['gamemodes'].values()):
        _state.custom_ui_round_scores = False

    # ── Phase 4: scoretable_lists config ─────────────────────────────────
    def _stl(key: str, d: dict) -> dict:
        node = _get_node_value(_get_node_value(root,'SCORETABLE_LISTS',{}), key.upper(), {})
        return {'enabled': _get_bool(node,'ENABLED',d.get('enabled',True)),'title': str(_get_node_value(node,'TITLE',d.get('title',key))),'pos_x': _get_float(node,'POS_X',d.get('pos_x',0.0)),'pos_y': _get_float(node,'POS_Y',d.get('pos_y',0.0)),'entries': _get_int(node,'ENTRIES',d.get('entries',6)),'icon_style': str(_get_node_value(node,'ICON_STYLE',d.get('icon_style','Icons128x128_1'))),'icon_substyle': str(_get_node_value(node,'ICON_SUBSTYLE',d.get('icon_substyle','Rankings')))}

    _state.stl_local_records     = _stl('local_records',    {'pos_x':-63.5,'pos_y':9.85,'entries':8,'title':'Local Records'})
    _state.stl_dedimania_records = _stl('dedimania_records',{'pos_x':-63.5,'pos_y':-8.0,'entries':8,'title':'Dedimania Records','icon_substyle':'Rankings'})
    _state.stl_top_average_times = _stl('top_average_times',{'pos_x':-63.5,'pos_y':29.5,'entries':9,'title':'Average Last Round','icon_style':'BgRaceScore2','icon_substyle':'ScoreLink'})
    _state.stl_top_rankings      = _stl('top_rankings',     {'pos_x':-63.5,'pos_y':47.5,'entries':6,'title':'Top Ranks','icon_style':'BgRaceScore2','icon_substyle':'Podium'})
    _state.stl_top_winners       = _stl('top_winners',      {'pos_x':-47.9,'pos_y':47.5,'entries':6,'title':'Top Winners','icon_style':'Icons128x32_1','icon_substyle':'RT_Cup'})
    _state.stl_most_records      = _stl('most_records',     {'pos_x':-32.3,'pos_y':47.5,'entries':6,'title':'Most Records','icon_style':'Icons64x64_1','icon_substyle':'RestartRace'})
    _state.stl_most_finished     = _stl('most_finished',    {'pos_x':-16.7,'pos_y':47.5,'entries':6,'title':'Most Finished','icon_style':'Icons128x128_1','icon_substyle':'Race'})
    _state.stl_top_playtime      = _stl('top_playtime',     {'pos_x':-1.1,'pos_y':47.5,'entries':6,'title':'Hours Played','icon_style':'Icons128x32_1','icon_substyle':'RT_TimeAttack'})
    _state.stl_top_donators      = _stl('top_donators',     {'pos_x':14.5,'pos_y':47.5,'entries':6,'title':'Top Donators','icon_style':'Icons128x128_1','icon_substyle':'Coppers'})
    _state.stl_top_nations       = _stl('top_nations',      {'pos_x':30.1,'pos_y':47.5,'entries':6,'title':'Top Nations','icon_style':'Icons64x64_1','icon_substyle':'ToolLeague1'})
    _state.stl_top_tracks        = _stl('top_tracks',       {'pos_x':47.8,'pos_y':17.6,'entries':7,'title':'Top Tracks','icon_style':'Icons128x128_1','icon_substyle':'NewTrack'})
    _state.stl_top_voters        = _stl('top_voters',       {'pos_x':47.8,'pos_y':1.5,'entries':7,'title':'Top Voters','icon_style':'Icons128x128_1','icon_substyle':'Invite'})
    _state.stl_top_visitors      = _stl('top_visitors',     {'pos_x':47.8,'pos_y':-14.6,'entries':7,'title':'Top Visitors','icon_style':'Icons128x128_1','icon_substyle':'Rankings'})

    # Donation widget config
    don_node = _get_node_value(root, 'DONATION_WIDGET', {})
    don_wid  = _get_node_value(don_node, 'WIDGET', {})
    _don_raw = str(_get_node_value(don_node, 'AMOUNTS', '20,50,100,200,500,1000'))
    try:
        _don_amounts = [int(x) for x in _don_raw.split(',') if x.strip().isdigit()]
    except Exception:
        _don_amounts = [20, 50, 100, 200, 500, 1000]
    _state.donation_cfg = {
        'enabled': _get_bool(don_node,'ENABLED',False),'text_color': str(_get_node_value(don_node,'TEXT_COLOR','FC0F')),
        'amounts': _don_amounts,'pos_x': _get_float(don_wid,'POS_X',-47.9),'pos_y': _get_float(don_wid,'POS_Y',18.2),
        'bg_style': str(_get_node_value(don_wid,'BACKGROUND_STYLE','BgsPlayerCard')),'bg_substyle': str(_get_node_value(don_wid,'BACKGROUND_SUBSTYLE','BgRacePlayerName')),
        'icon_style': str(_get_node_value(don_wid,'ICON_STYLE','Icons128x128_1')),'icon_substyle': str(_get_node_value(don_wid,'ICON_SUBSTYLE','Coppers')),
        'button_style': str(_get_node_value(don_wid,'BUTTON_STYLE','Bgs1InRace')),'button_substyle': str(_get_node_value(don_wid,'BUTTON_SUBSTYLE','BgIconBorder')),
        'button_color': str(_get_node_value(don_wid,'BUTTON_COLOR','000F')),
    }

    # Winning payout config
    wp_node = _get_node_value(root,'WINNING_PAYOUT',{})
    wp_wid  = _get_node_value(wp_node,'WIDGET',{})
    wp_pay  = _get_node_value(wp_node,'PAY_COPPERS',{})
    wp_col  = _get_node_value(wp_node,'COLORS',{})
    _state.winning_payout_cfg = {
        'enabled': _get_bool(wp_node,'ENABLED',False),'min_coppers': _get_int(wp_node,'MINIMUM_SERVER_COPPERS',250),
        'pos_x': _get_float(wp_wid,'POS_X',37.8),'pos_y': _get_float(wp_wid,'POS_Y',-30.7),
        'title': str(_get_node_value(wp_wid,'TITLE','Finish Winners')),
        'bg_style': str(_get_node_value(wp_wid,'BACKGROUND_STYLE','BgsPlayerCard')),'bg_substyle': str(_get_node_value(wp_wid,'BACKGROUND_SUBSTYLE','BgRacePlayerName')),
        'title_style': str(_get_node_value(wp_wid,'TITLE_STYLE','BgsPlayerCard')),'title_substyle': str(_get_node_value(wp_wid,'TITLE_SUBSTYLE','ProgressBar')),
        'icon_style': str(_get_node_value(wp_wid,'ICON_STYLE','BgRaceScore2')),'icon_substyle': str(_get_node_value(wp_wid,'ICON_SUBSTYLE','Fame')),
        'pay_first': _get_int(wp_pay,'FIRST',20),'pay_second': _get_int(wp_pay,'SECOND',15),'pay_third': _get_int(wp_pay,'THIRD',10),
        'col_won': str(_get_node_value(wp_col,'WON','5F0F')),'col_coppers': str(_get_node_value(wp_col,'COPPERS','FF9F')),'col_disconnected': str(_get_node_value(wp_col,'DISCONNECTED','F00F')),
    }

    _state.loaded = True

# ---------------------------------------------------------------------------
# Phase 1 startup helpers
# ---------------------------------------------------------------------------

def _version_tuple(version: str) -> tuple[int, ...]:
    parts = re.findall(r'\d+', str(version or ''))
    return tuple(int(p) for p in parts) if parts else (0,)


def _runtime_game_token(aseco: 'Aseco') -> str:
    server = aseco.server
    game = ''
    if hasattr(server, 'get_game'):
        try:
            game = server.get_game()
        except Exception:
            game = ''
    elif hasattr(server, 'getGame'):
        try:
            game = server.getGame()
        except Exception:
            game = ''
    if not game:
        game = getattr(server, 'game', '') or ''
    game = str(game).strip()
    if game == 'TmForever':
        return 'TMFOREVER'
    return game.upper()


def validate_phase1_runtime(aseco: 'Aseco') -> None:
    runtime_version = str(getattr(aseco, 'PYXASECO_VERSION', '') or CORE_PYXASECO_VERSION)
    if _version_tuple(runtime_version) < _version_tuple(MIN_PYXASECO_VERSION):
        raise RuntimeError(
            f'[plugin_records_eyepiece.py] Not supported PyXaseco version ({runtime_version})! '
            f'Please update to min. version {MIN_PYXASECO_VERSION}!'
        )

    game_token = _runtime_game_token(aseco)
    if game_token not in SUPPORTED_GAME_TOKENS:
        raise RuntimeError(
            f'[plugin_records_eyepiece.py] This plugin supports only TMF/TmForever, '
            f'can not start with a "{game_token}" Dedicated-Server!'
        )


def _loaded_plugins(aseco: 'Aseco') -> list[str]:
    if getattr(aseco, '_plugin_loader', None):
        return list(getattr(aseco._plugin_loader, 'loaded_plugins', []) or [])
    return list(getattr(aseco, '_plugins', []) or [])


def validate_phase1_dependencies(aseco: 'Aseco') -> None:
    loaded = set(_loaded_plugins(aseco))

    required = {
        'plugin_localdatabase',
        'plugin_tmxinfo',
        'plugin_rasp_jukebox',
    }
    if any(cfg.enabled for cfg in _state.dedi.values()):
        required.add('plugin_dedimania')

    missing = sorted(name for name in required if name not in loaded)
    if missing:
        raise RuntimeError(
            '[plugin_records_eyepiece.py] Unmet requirements! Missing plugin(s): ' + ', '.join(missing)
        )

    forbidden = []
    if 'plugin_elist' in loaded:
        forbidden.append('plugin_elist')
    if _state.cp.enabled and 'plugin_simplcp' in loaded:
        forbidden.append('plugin_simplcp')

    if forbidden:
        raise RuntimeError(
            '[plugin_records_eyepiece.py] This plugin can not run together with: ' + ', '.join(forbidden)
        )


def apply_phase1_defaults(aseco: 'Aseco') -> None:
    _state.plugin_name = PLUGIN_NAME
    _state.plugin_version = PLUGIN_VERSION
    _state.manialink_prefix = PLUGIN_MANIALINK_PREFIX
    _state.line_height = PLUGIN_LINE_HEIGHT

    # No Ultimania or Music, but keep package Python-native.
    if Gameinfo.STNT in _state.dedi:
        _state.dedi[Gameinfo.STNT].enabled = False

    # Default format if placeholders are missing.
    rounds = _state.live.get(Gameinfo.RNDS)
    if rounds:
        fmt = rounds.fmt or ''
        if '{score}' not in fmt and ('{remaining}' not in fmt or '{pointlimit}' not in fmt):
            rounds.fmt = '{score} ({remaining})'

# TMN/TMNF-style accounts do not support payout features in this configuration.
    if not bool(getattr(aseco.server, 'rights', False)):
        setattr(_state, 'winning_payout_enabled', False)
