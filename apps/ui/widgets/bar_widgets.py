"""
widgets/bar_widgets.py

All 4.6x6.5 bar widgets that appear in the corners of the HUD:

Race-state (shown during gameplay):
  ML 91809  TrackcountWidget      - track count, opens tracklist window
  ML 91807  GamemodeWidget        - current gamemode name + limit
  ML 91808  VisitorsWidget        - total visitor count
  ML 91837  PlayerSpectatorWidget - player/spectator counts
  ML 91838  LadderLimitWidget     - ladder range e.g. "40-80k"
  ML 91844  CurrentRankingWidget  - live ladder rank (per player)
  ML 91849  TMExchangeWidget      - TMX world record for this map
  ML 91810  ToplistWidget         - button to open top-list window
  ML 91835  AddToFavoriteWidget   - add-to-favorites button
  ML 91806  ClockWidget           - server/player clock (sent per timezone group)

Score-state (shown on score screen, sent at onEndRace):
  ML 91841  NextEnvironmentWidget - upcoming environment icon
  ML 91836  NextGamemodeWidget    - upcoming gamemode icon
  ML 91833  EyepieceWidget/Score  - Records-Eyepiece logo bar

Each widget is a standalone async function:
  _draw_<name>_all(aseco)       - broadcast to all players
  _draw_<name>_player(aseco, login)  - send to one player (Clock only)
  _hide_<name>(aseco)           - broadcast empty manialink
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from pyxaseco.models import Gameinfo
from pyxaseco.app_services import localdb_get_pool

from ..config import _state, _effective_mode

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Manialink IDs
# ---------------------------------------------------------------------------
ML_TRACKCOUNT       = 91809
ML_GAMEMODE         = 91807
ML_VISITORS         = 91808
ML_PLAYERSPECTATOR  = 91837
ML_LADDERLIMIT      = 91838
ML_CURRENTRANKING   = 91844
ML_TMEXCHANGE       = 91849
ML_TOPLIST          = 91810
ML_FAVORITE         = 91835
ML_CLOCK            = 91806
ML_NEXT_ENV         = 91841
ML_NEXT_GAMEMODE    = 91836
ML_EYEPIECE_SCORE   = 91833
ML_DISCORD          = 5834287
ML_FORCE_PLAY       = 5834288

# Action IDs
ACT_SHOW_TRACKLIST      = 91820    # action 91820 - open TracklistWindow
ACT_SHOW_TOPNATIONS     = 91809    # action 91809 - TopNationsWindow
ACT_SHOW_TOPLIST        = 918153   # action 918153 - ToplistWindow
ACT_SHOW_CURRENTRANKING = 91806    # action 91806 - LiveRankingsWindow
ACT_CLOCK_DETAILS       = 91803    # ManialinkId.'03' = '918'+'03' = 91803
ACT_SHOW_TMXINFO        = 91808    # action 91808 - trigger /tmxinfo
ACT_DISCORD             = 5834287
ACT_FORCE_PLAY          = 5834288

# Image URL for the "open small" chevron arrow
_OPEN_SMALL = 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/edge-open-ld-light.png'

# Gamemode metadata: mode int -> (name, Icons128x32_1 substyle)
_GAMEMODE_META = {
    Gameinfo.RNDS: ('ROUNDS',      'RT_Rounds'),
    Gameinfo.TA:   ('TIME ATTACK', 'RT_TimeAttack'),
    Gameinfo.TEAM: ('TEAM',        'RT_Team'),
    Gameinfo.LAPS: ('LAPS',        'RT_Laps'),
    Gameinfo.STNT: ('STUNTS',      'RT_Stunts'),
    Gameinfo.CUP:  ('CUP',         'RT_Cup'),
}

# Environment name -> (posn, sizen) for the env icon quad
_ENV_ICONS = {
    'Stadium': ('0.7 -1 0.06',   '3.3 2.156'),
    'Bay':     ('1.29 -0.6 0.06','1.76 2.97'),
    'Coast':   ('1.45 -0.6 0.06','1.738 2.97'),
    'Desert':  ('1.33 -0.6 0.06','1.837 2.97'),
    'Speed':   ('1.33 -0.6 0.06','1.837 2.97'),  # alias
    'Island':  ('1.03 -0.6 0.06','2.409 2.97'),
    'Rally':   ('1.33 -0.6 0.06','1.925 2.97'),
    'Alpine':  ('1.23 -0.6 0.06','2.112 2.97'),
    'Snow':    ('1.23 -0.6 0.06','2.112 2.97'),  # alias
}
_ENV_IMAGE_KEYS = {
    'Stadium': 'icon_stadium', 'Bay': 'icon_bay', 'Coast': 'icon_coast',
    'Desert': 'icon_desert', 'Speed': 'icon_desert',
    'Island': 'icon_island', 'Rally': 'icon_rally',
    'Alpine': 'icon_snow', 'Snow': 'icon_snow',
}
_ENV_IMAGES = {
    'icon_stadium': 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-stadium-enabled.png',
    'icon_bay':     'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-bay-enabled.png',
    'icon_coast':   'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-coast-enabled.png',
    'icon_desert':  'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-desert-enabled.png',
    'icon_island':  'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-island-enabled.png',
    'icon_rally':   'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-rally-enabled.png',
    'icon_snow':    'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/env-snow-enabled.png',
}

BAR_BASE_W = 4.6
BAR_BASE_H = 6.5


def _bar_width(cfg) -> float:
    return max(1.0, float(getattr(cfg, 'width', BAR_BASE_W) or BAR_BASE_W))


def _bar_height(cfg) -> float:
    return max(1.0, float(getattr(cfg, 'height', BAR_BASE_H) or BAR_BASE_H))


def _bar_x(cfg, value: float) -> float:
    return _bar_width(cfg) * value / BAR_BASE_W


def _bar_y(cfg, value: float) -> float:
    return _bar_height(cfg) * value / BAR_BASE_H


def _bar_w(cfg, value: float) -> float:
    return _bar_width(cfg) * value / BAR_BASE_W


def _bar_h(cfg, value: float) -> float:
    return _bar_height(cfg) * value / BAR_BASE_H


def _bar_text_scale(cfg, base: float) -> float:
    scale = min(_bar_width(cfg) / BAR_BASE_W, _bar_height(cfg) / BAR_BASE_H)
    return round(base * scale, 3)


def _scale_bar_geom(cfg, posn: str, sizen: str) -> tuple[str, str]:
    px, py, pz = [float(x) for x in posn.split()]
    sx, sy = [float(x) for x in sizen.split()]
    pos = f'{_bar_x(cfg, px):.4f} {_bar_y(cfg, py):.4f} {pz:g}'
    size = f'{_bar_w(cfg, sx):.4f} {_bar_h(cfg, sy):.4f}'
    return pos, size


# ---------------------------------------------------------------------------
# Low-level send helpers
# ---------------------------------------------------------------------------

async def _broadcast(aseco: 'Aseco', xml: str) -> None:
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPage', xml, 0, False)


async def _send_to(aseco: 'Aseco', login: str, xml: str) -> None:
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPageToLogin', login, xml, 0, False)


def _empty(ml_id: int) -> str:
    return f'<manialink id="{ml_id}"></manialink>'


def _bg_attrs(style: str, substyle: str, color: str = '') -> str:
    if color:
        return f'bgcolor="{escape(color)}"'
    return f'style="{escape(style)}" substyle="{escape(substyle)}"'


async def _rehide_hidden_logins(aseco: 'Aseco', *ml_ids: int) -> None:
    hidden = [
        p.login for p in aseco.server.players.all()
        if not _state.player_visible.get(p.login, True)
    ]
    if not hidden:
        return
    for login in hidden:
        for ml_id in ml_ids:
            await _send_to(aseco, login, _empty(ml_id))


# ---------------------------------------------------------------------------
# Helper: format time limit in ms as M:SS or just seconds
# ---------------------------------------------------------------------------

def _fmt_time_limit(ms: int) -> str:
    if ms <= 0:
        return '?'
    s = ms // 1000
    m = s // 60
    s = s % 60
    if m > 0:
        return f'{m}:{s:02d}'
    return str(s)


# ---------------------------------------------------------------------------
# TrackcountWidget  (ML 91809)
# ---------------------------------------------------------------------------

async def _draw_trackcount_all(aseco: 'Aseco') -> None:
    cfg = _state.trackcount
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    try:
        # Query GBX directly for the authoritative server-wide track count.
        all_tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
        count = len(all_tracks)
        aseco.server._re_trackcount = count
    except Exception:
        count = getattr(aseco.server, '_re_trackcount', 0)

    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_TRACKCOUNT}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' action="{ACT_SHOW_TRACKLIST}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
        f'<quad posn="{_bar_x(cfg, 0.4):.4f} 0 0.002" sizen="{_bar_w(cfg, 3.8):.4f} {_bar_h(cfg, 3.8):.4f}"'
        f' style="Icons128x128_1" substyle="LoadTrack"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' text="{count}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="TRACKS"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_TRACKCOUNT)


async def _hide_trackcount(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_TRACKCOUNT))


# ---------------------------------------------------------------------------
# GamemodeWidget  (ML 91807)
# ---------------------------------------------------------------------------

async def _draw_gamemode_all(aseco: 'Aseco') -> None:
    cfg = _state.gamemode
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    mode = _effective_mode(aseco)
    name, icon_sub = _GAMEMODE_META.get(mode, ('?', 'RT_TimeAttack'))

    # Build limits string from current game info
    limits = ''
    gi = aseco.server.gameinfo
    try:
        if mode == Gameinfo.RNDS:
            pts = getattr(gi, 'rounds_points_limit', 0) or 0
            limits = f'{pts} pts.'
        elif mode == Gameinfo.TA:
            ms = getattr(gi, 'time_attack_limit', 0) or 0
            limits = _fmt_time_limit(ms)
        elif mode == Gameinfo.TEAM:
            pts = getattr(gi, 'team_points_limit', 0) or 0
            limits = f'{pts} pts.'
        elif mode == Gameinfo.LAPS:
            tl = getattr(gi, 'laps_time_limit', 0) or 0
            if tl > 0:
                limits = f'{_fmt_time_limit(tl)} min.'
            else:
                nl = getattr(gi, 'laps_nb_laps', 0) or 0
                limits = f'{nl} laps'
        elif mode == Gameinfo.CUP:
            pts = getattr(gi, 'cup_points_limit', 0) or 0
            limits = f'{pts} pts.'
    except Exception:
        pass

    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_GAMEMODE}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.3):.4f} 0.002" sizen="{_bar_w(cfg, 2.9):.4f} {_bar_h(cfg, 2.9):.4f}"'
        f' style="Icons128x32_1" substyle="{icon_sub}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="{name}"/>'
    )
    if limits:
        xml += (
            f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
            f' textsize="1" text="{escape(limits)}"/>'
        )
    xml += f'</frame></manialink>'
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_GAMEMODE)


async def _hide_gamemode(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_GAMEMODE))


# ---------------------------------------------------------------------------
# VisitorsWidget  (ML 91808)
# ---------------------------------------------------------------------------

async def _draw_visitors_all(aseco: 'Aseco') -> None:
    cfg = _state.visitors
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    count = _state.visitor_count
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_VISITORS}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' action="{ACT_SHOW_TOPNATIONS}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.3):.4f} 0.002" sizen="{_bar_w(cfg, 3.2):.4f} {_bar_h(cfg, 3.2):.4f}"'
        f' style="Icons128x128_1" substyle="Buddies"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' text="{count}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="VISITORS"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_VISITORS)


async def _hide_visitors(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_VISITORS))


async def _refresh_visitor_count(aseco: 'Aseco') -> None:
    """Query total visitor count from DB and cache in _state.visitor_count."""
    try:
        pool = await localdb_get_pool(aseco)
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT COUNT(*) FROM players')
                row = await cur.fetchone()
                _state.visitor_count = int(row[0]) if row else 0
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PlayerSpectatorWidget  (ML 91837)
# ---------------------------------------------------------------------------

def _is_spectator(p) -> bool:
    raw = getattr(p, 'spectatorstatus', None)
    if raw is not None:
        try:
            return (int(raw) % 10) != 0
        except Exception:
            pass
    return bool(getattr(p, 'isspectator', False))

async def _draw_playerspectator_all(aseco: 'Aseco') -> None:
    cfg = _state.player_spectator
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    players = aseco.server.players.all()
    n_spec = sum(1 for p in players if _is_spectator(p))
    n_play = len(players) - n_spec

    max_play = _state.server_max_players
    max_spec = _state.server_max_spectators

    col_play = 'F00' if (max_play > 0 and n_play >= max_play) else 'FFF'
    col_spec = 'F00' if (max_spec > 0 and n_spec >= max_spec) else 'FFF'
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_PLAYERSPECTATOR}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -0.6):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{col_play}" text="{n_play}/{max_play}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -2.1):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="PLAYER"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{col_spec}" text="{n_spec}/{max_spec}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="SPECTATOR"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_PLAYERSPECTATOR)


async def _refresh_server_limits(aseco: 'Aseco') -> None:
    """Refresh max player/spectator slots from server."""
    try:
        opts = await aseco.client.query('GetServerOptions')
        if opts:
            _state.server_max_players    = int(opts.get('CurrentMaxPlayers', 0) or 0)
            _state.server_max_spectators = int(opts.get('CurrentMaxSpectators', 0) or 0)
    except Exception:
        pass


async def _hide_playerspectator(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_PLAYERSPECTATOR))


# ---------------------------------------------------------------------------
# LadderLimitWidget  (ML 91838)
# ---------------------------------------------------------------------------

async def _draw_ladderlimit_all(aseco: 'Aseco') -> None:
    cfg = _state.ladderlimit
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    lmin = getattr(aseco.server, 'laddermin', 0) or 0
    lmax = getattr(aseco.server, 'laddermax', 0) or 0

    lo = str(int(lmin) // 1000)[:3]
    hi = str(int(lmax) // 1000)[:3]
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_LADDERLIMIT}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.3):.4f} 0.002" sizen="{_bar_w(cfg, 3.35):.4f} {_bar_h(cfg, 3):.4f}"'
        f' style="Icons128x128_1" substyle="LadderPoints"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' scale="0.9" text="{lo}-{hi}k"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="LADDER"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_LADDERLIMIT)


async def _hide_ladderlimit(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_LADDERLIMIT))


# ---------------------------------------------------------------------------
# CurrentRankingWidget  (ML 91844, per-player)
# ---------------------------------------------------------------------------

async def _draw_currentranking_all(aseco: 'Aseco') -> None:
    cfg = _state.current_ranking
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    mode = _effective_mode(aseco)
    for p in aseco.server.players.all():
        await _draw_currentranking_player(aseco, p.login, mode)


async def _draw_currentranking_player(aseco: 'Aseco', login: str, mode: int | None = None) -> None:
    cfg = _state.current_ranking
    if not cfg.enabled:
        return
    if not _state.player_visible.get(login, True):
        await _send_to(aseco, login, _empty(ML_CURRENTRANKING))
        return

    if mode is None:
        mode = _effective_mode(aseco)

    if mode == Gameinfo.TEAM:
        ranks = '---'
        info  = 'FIRST'
    else:
        # Find this player's current server ranking
        try:
            rankings = await aseco.client.query('GetCurrentRanking', 300, 0)
            rank = 0
            total = len(rankings) if rankings else 0
            for entry in (rankings or []):
                if entry.get('Login') == login:
                    bt = entry.get('BestTime', 0) or 0
                    sc = entry.get('Score', 0) or 0
                    if bt > 0 or sc > 0:
                        rank = entry.get('Rank', 0) or 0
                    break
            ranks = f'{rank}/{total}'
        except Exception:
            ranks = '0/0'
        info = 'RANKING'
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_CURRENTRANKING}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' action="{ACT_SHOW_CURRENTRANKING}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.3):.4f} 0.003" sizen="{_bar_w(cfg, 3.35):.4f} {_bar_h(cfg, 3):.4f}"'
        f' style="Icons128x128_1" substyle="Rankings"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="FFFF" text="{ranks}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="{info}"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _send_to(aseco, login, xml)


async def _hide_currentranking(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_CURRENTRANKING))


# ---------------------------------------------------------------------------
# TMExchangeWidget  (ML 91849)
# ---------------------------------------------------------------------------

async def _draw_tmexchange_all(aseco: 'Aseco') -> None:
    cfg = _state.tmexchange
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    ch = getattr(aseco.server, 'challenge', None)
    tmx_id = getattr(ch, 'tmx_id', None) if ch else None
    tmx_prefix = getattr(ch, 'tmx_prefix', None) if ch else None

    score = ''
    try:
        import sys
        panels = (
            sys.modules.get('apps.platform_ui.panels')
            or sys.modules.get('apps.platform_ui.panels')
        )
        if panels is not None:
            cache = getattr(panels, '_records_cache', {}) or {}
            score = str(cache.get('tmx', '') or '').strip()
    except Exception:
        score = ''

    has_tmx = bool(tmx_id and tmx_prefix)
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    if has_tmx:
        if not score or score in ('---.--', '---', ''):
            score = 'NO'

        xml = (
            f'<manialink id="{ML_TMEXCHANGE}">'
            f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
            f'<format textsize="1"/>'
            f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}" action="{ACT_SHOW_TMXINFO}"'
            f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
            f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
            f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.1):.4f} 0.002" sizen="{_bar_w(cfg, 3.2):.4f} {_bar_h(cfg, 3.2):.4f}"'
            f' image="http://maniacdn.net/undef.de/xaseco1/records-eyepiece/logo-tmx-normal.png"'
            f' imagefocus="http://maniacdn.net/undef.de/xaseco1/records-eyepiece/logo-tmx-focus.png"/>'
            f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
            f' text="{escape(score)}"/>'
            f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
            f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="WORLD-RECORD"/>'
            f'</frame>'
            f'</manialink>'
        )
    else:
        xml = (
            f'<manialink id="{ML_TMEXCHANGE}">'
            f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
            f'<format textsize="1"/>'
            f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
            f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
            f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.1):.4f} 0.002" sizen="{_bar_w(cfg, 3.2):.4f} {_bar_h(cfg, 3.2):.4f}"'
            f' image="http://maniacdn.net/undef.de/xaseco1/records-eyepiece/logo-tmx-normal.png"'
            f' imagefocus="http://maniacdn.net/undef.de/xaseco1/records-eyepiece/logo-tmx-focus.png"/>'
            f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
            f' text="NOT AT"/>'
            f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
            f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="MANIA-EXCHANGE"/>'
            f'</frame>'
            f'</manialink>'
        )

    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_TMEXCHANGE)


async def _hide_tmexchange(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_TMEXCHANGE))


# ---------------------------------------------------------------------------
# ToplistWidget  (ML 91810)
# ---------------------------------------------------------------------------

async def _draw_toplist_all(aseco: 'Aseco') -> None:
    cfg = _state.toplist
    if not cfg.enabled:
        return
    if _state.challenge_show_next:
        return

    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_TOPLIST}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' action="{ACT_SHOW_TOPLIST}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.3):.4f} 0.002" sizen="{_bar_w(cfg, 3.35):.4f} {_bar_h(cfg, 3):.4f}"'
        f' style="Icons128x128_1" substyle="Rankings"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' scale="0.9" text="MORE"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="RANKING"/>'
        f'</frame>'
        f'</manialink>'
    )

    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_TOPLIST)


async def _hide_toplist(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_TOPLIST))


# ---------------------------------------------------------------------------
# AddToFavoriteWidget  (ML 91835)
# ---------------------------------------------------------------------------

async def _draw_favorite_all(aseco: 'Aseco', score: bool = False) -> None:
    cfg = _state.favorite
    if not cfg.enabled:
        return

    if score:
        px, py = cfg.score_pos_x, cfg.score_pos_y
        bg_sty, bg_sub = cfg.score_bg_style, cfg.score_bg_substyle
        bg_col = cfg.score_bg_color
    else:
        px, py = cfg.race_pos_x, cfg.race_pos_y
        bg_sty, bg_sub = cfg.race_bg_style, cfg.race_bg_substyle
        bg_col = cfg.race_bg_color
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    slogin = getattr(aseco.server, 'serverlogin', '') or ''
    sname  = escape(getattr(aseco.server, 'name', '') or '')
    szone  = escape(getattr(aseco.server, 'zone', '') or '')

    import urllib.parse
    fav_ml = (
        f'addfavorite?action=add'
        f'&amp;server={urllib.parse.quote(slogin)}'
        f'&amp;name={urllib.parse.quote(sname)}'
        f'&amp;zone={urllib.parse.quote(szone)}'
    )

    xml = (
        f'<manialink id="{ML_FAVORITE}">'
        f'<frame posn="{px} {py} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' manialink="{fav_ml}" addplayerid="1"'
        f' {_bg_attrs(bg_sty, bg_sub, bg_col)}/>'
        f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.2):.4f} 0.002" sizen="{_bar_w(cfg, 3.2):.4f} {_bar_h(cfg, 3.2):.4f}"'
        f' style="Icons128x128_Blink" substyle="ServersFavorites"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' text="ADD"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="FAVORITE"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_FAVORITE)


async def _hide_favorite(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_FAVORITE))


# ---------------------------------------------------------------------------
# ClockWidget  (ML 91806)
# Sent per timezone group: players with the same TZ get the same manialink.
# Each player's timezone preference is stored in _state.player_timezone[login].
# ---------------------------------------------------------------------------

def _compute_clock(timezone: str, timeformat: str) -> tuple[str, str]:
    # Primary: system local time - always correct on the server regardless of platform
    now_local = datetime.now().astimezone()

    # Try to display time in the requested timezone if different from system tz
    now = now_local
    if timezone:
        try:
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo(timezone)
            now = datetime.now(_tz)
        except Exception:
            pass  # Fall back to system local time

    fmt = (timeformat or 'H:i')
    fmt = fmt.replace('H', '%H').replace('i', '%M').replace('s', '%S').replace('G', '%H')
    try:
        time_str = now.strftime(fmt)
    except Exception:
        time_str = now.strftime('%H:%M')

    # Timezone abbreviation: prefer actual tz name, fall back to UTC offset string
    tz_abbr = now.strftime('%Z') or ''
    if not tz_abbr or len(tz_abbr) > 6:
        off = now.utcoffset()
        if off is not None:
            tot = int(off.total_seconds() // 60)
            sign = '+' if tot >= 0 else '-'
            tot = abs(tot)
            tz_abbr = f'UTC{sign}{tot // 60:02d}:{tot % 60:02d}'
        else:
            tz_abbr = 'UTC'
    return time_str, tz_abbr


async def _draw_clock_all(aseco: 'Aseco') -> None:
    cfg = _state.clock
    if not cfg.enabled:
        return

    at_score = _state.challenge_show_next

    # Group players by timezone preference
    # Default timezone from XML config (e.g. 'Europe/Berlin')
    _fallback_tz = cfg.default_timezone or 'local'

    tz_groups: dict[str, list[str]] = {}
    for p in aseco.server.players.all():
        tz = _state.player_timezone.get(p.login) or _fallback_tz
        tz_groups.setdefault(tz, []).append(p.login)

    for tz, logins in tz_groups.items():
        xml = _build_clock_xml(cfg, tz, at_score)
        for login in logins:
            await _send_to(aseco, login, xml)


async def _draw_clock_player(aseco: 'Aseco', login: str) -> None:
    cfg = _state.clock
    if not cfg.enabled:
        return
    _fallback_tz = cfg.default_timezone or 'local'
    tz = _state.player_timezone.get(login) or _fallback_tz
    at_score = _state.challenge_show_next
    xml = _build_clock_xml(cfg, tz, at_score)
    await _send_to(aseco, login, xml)


def _build_clock_xml(cfg, timezone: str, at_score: bool) -> str:
    time_str, tz_abbr = _compute_clock(timezone, cfg.timeformat)

    now = datetime.utcnow()
    # Swatch Internet Time (beats): (UTC+1 seconds since midnight) / 86.4
    beats = int(((now.hour * 3600 + now.minute * 60 + now.second + 3600) % 86400) / 86.4)

    if at_score:
        px, py = cfg.score_pos_x, cfg.score_pos_y
        bg_sty, bg_sub = cfg.score_bg_style, cfg.score_bg_substyle
        bg_col = cfg.score_bg_color
        action_attr = ''
    else:
        px, py = cfg.race_pos_x, cfg.race_pos_y
        bg_sty, bg_sub = cfg.race_bg_style, cfg.race_bg_substyle
        bg_col = cfg.race_bg_color
        action_attr = f' action="{ACT_CLOCK_DETAILS}"'
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_CLOCK}">'
        f'<frame posn="{px} {py} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"{action_attr}'
        f' {_bg_attrs(bg_sty, bg_sub, bg_col)}/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -0.6):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' text="{escape(time_str)}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -2.1):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="{escape(tz_abbr)}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' text="{beats:03d}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="BEAT"/>'
    )
    if not at_score:
        worldmap = 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/worldmap-pure.png'
        xml += (
            f'<quad posn="0 100 0" sizen="7.2 4.34" image="{worldmap}"/>'  # preload
            f'<quad posn="{_bar_x(cfg, -0.18):.4f} {_bar_y(cfg, -4.6):.4f} 0.002" sizen="{_bar_w(cfg, 2.1):.4f} {_bar_h(cfg, 2.1):.4f}" image="{_OPEN_SMALL}"/>'
        )
    xml += f'</frame></manialink>'
    return xml


async def _hide_clock(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_CLOCK))


# ---------------------------------------------------------------------------
# Score-state: NextEnvironmentWidget  (ML 91841)
# ---------------------------------------------------------------------------

async def _draw_next_env_all(aseco: 'Aseco') -> None:
    cfg = _state.next_env
    if not cfg.enabled:
        return

    nxt = _state.next_challenge
    env = str(nxt.get('env', '') or '')

    icon_quad = ''
    if env in _ENV_ICONS:
        posn, sizen = _ENV_ICONS[env]
        posn, sizen = _scale_bar_geom(cfg, posn, sizen)
        img_key = _ENV_IMAGE_KEYS[env]
        img_url = _ENV_IMAGES.get(img_key, '')
        if img_url:
            icon_quad = (
                f'<quad posn="{posn}" sizen="{sizen}"'
                f' image="{img_url}"/>'
            )
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_NEXT_ENV}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'{icon_quad}'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.2):.4f} 0.002" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="UPCOMING"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -5.2):.4f} 0.002" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="ENVIRONMENT"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_NEXT_ENV)


async def _hide_next_env(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_NEXT_ENV))


# ---------------------------------------------------------------------------
# Score-state: NextGamemodeWidget  (ML 91836)
# ---------------------------------------------------------------------------

async def _draw_next_gamemode_all(aseco: 'Aseco') -> None:
    cfg = _state.next_gamemode_widget
    if not cfg.enabled:
        return

    try:
        nextgame = await aseco.client.query('GetNextGameInfo')
        next_mode = int((nextgame or {}).get('GameMode', 0) or 0)
    except Exception:
        next_mode = 0

    _, icon_sub = _GAMEMODE_META.get(next_mode, ('?', 'RT_TimeAttack'))
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_NEXT_GAMEMODE}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.3):.4f} 0.002" sizen="{_bar_w(cfg, 2.9):.4f} {_bar_h(cfg, 2.9):.4f}"'
        f' style="Icons128x32_1" substyle="{icon_sub}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.2):.4f} 0.002" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="UPCOMING"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -5.2):.4f} 0.002" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="GAMEMODE"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_NEXT_GAMEMODE)


async def _hide_next_gamemode(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_NEXT_GAMEMODE))


# ---------------------------------------------------------------------------
# Score-state: EyepieceWidget/Score  (ML 91833)
# ---------------------------------------------------------------------------

async def _draw_eyepiece_score_all(aseco: 'Aseco') -> None:
    cfg = _state.eyepiece_widget
    if not cfg.score_enabled:
        return
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_EYEPIECE_SCORE}">'
        f'<frame posn="{cfg.score_pos_x} {cfg.score_pos_y} 0">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' {_bg_attrs(cfg.score_bg_style, cfg.score_bg_substyle, getattr(cfg, "score_bg_color", ""))}/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -0.6):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.7)}" text="Records"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -2.0):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center"'
        f' textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.5)}" text="Eyepiece"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_EYEPIECE_SCORE)


async def _hide_eyepiece_score(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_EYEPIECE_SCORE))


# ---------------------------------------------------------------------------
# Discord and Force Play widgets  (ML 5834287 / 5834288)
# ---------------------------------------------------------------------------

async def _draw_discord_widget_all(aseco: 'Aseco') -> None:
    if _state.challenge_show_next:
        return
    cfg = _state.discord_widget
    if not cfg.enabled:
        return

    discord_url = (_state.links.get('discord') or 'discord.gg/CwFNmzKX8G').replace('&', '&amp;')
    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_DISCORD}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0" action="{ACT_DISCORD}">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' action="{ACT_DISCORD}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}'
        f' url="{discord_url}"/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.2):.4f} 0.002" sizen="{_bar_w(cfg, 3.2):.4f} {_bar_h(cfg, 3.2):.4f}"'
        f' action="{ACT_DISCORD}"'
        f' style="Icons128x128_1" substyle="Buddies"'
        f' url="{discord_url}"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center" text="$zJoin"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center" textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="$zDiscord"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_DISCORD)


async def _draw_force_play_widget_all(aseco: 'Aseco') -> None:
    if _state.challenge_show_next:
        return
    cfg = _state.force_play_widget
    if not cfg.enabled:
        return

    w = _bar_width(cfg)
    h = _bar_height(cfg)
    cx = w / 2.0

    xml = (
        f'<manialink id="{ML_FORCE_PLAY}">'
        f'<frame posn="{cfg.pos_x} {cfg.pos_y} 0" action="{ACT_FORCE_PLAY}">'
        f'<format textsize="1"/>'
        f'<quad posn="0 0 0.001" sizen="{w:.4f} {h:.4f}"'
        f' action="{ACT_FORCE_PLAY}"'
        f' {_bg_attrs(cfg.bg_style, cfg.bg_substyle, getattr(cfg, "bg_color", ""))}/>'
        f'<quad posn="{_bar_x(cfg, 0.7):.4f} {_bar_y(cfg, -0.2):.4f} 0.002" sizen="{_bar_w(cfg, 3.2):.4f} {_bar_h(cfg, 3.2):.4f}"'
        f' style="Icons128x128_1" substyle="Vehicles"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -3.4):.4f} 0.1" sizen="{_bar_w(cfg, 3.65):.4f} {_bar_h(cfg, 2):.4f}" halign="center" text="$zForce"/>'
        f'<label posn="{cx:.4f} {_bar_y(cfg, -4.9):.4f} 0.1" sizen="{_bar_w(cfg, 6.35):.4f} {_bar_h(cfg, 2):.4f}" halign="center" textcolor="{cfg.text_color}" scale="{_bar_text_scale(cfg, 0.6)}" text="$zPlay"/>'
        f'</frame>'
        f'</manialink>'
    )
    await _broadcast(aseco, xml)
    await _rehide_hidden_logins(aseco, ML_FORCE_PLAY)


async def _hide_discord_widget(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_DISCORD))


async def _hide_force_play_widget(aseco: 'Aseco') -> None:
    await _broadcast(aseco, _empty(ML_FORCE_PLAY))


# ---------------------------------------------------------------------------
# Convenience: draw all race-state bar widgets at once
# ---------------------------------------------------------------------------

async def draw_all_race_bars(aseco: 'Aseco') -> None:
    """Send all enabled race-state bar widgets to all players."""
    await _draw_trackcount_all(aseco)
    await _draw_gamemode_all(aseco)
    await _draw_visitors_all(aseco)
    await _draw_playerspectator_all(aseco)
    await _draw_ladderlimit_all(aseco)
    await _draw_currentranking_all(aseco)
    await _draw_tmexchange_all(aseco)
    await _draw_toplist_all(aseco)
    await _draw_favorite_all(aseco, score=False)
    await _draw_discord_widget_all(aseco)
    await _draw_force_play_widget_all(aseco)
    await _draw_clock_all(aseco)


async def draw_all_score_bars(aseco: 'Aseco') -> None:
    """Send all enabled score-state bar widgets to all players."""
    await _draw_next_env_all(aseco)
    await _draw_next_gamemode_all(aseco)
    await _draw_eyepiece_score_all(aseco)
    await _draw_favorite_all(aseco, score=True)
    await _draw_clock_all(aseco)


async def hide_all_race_bars(aseco: 'Aseco') -> None:
    """Broadcast empty MLs for all race-state bar widgets (at score)."""
    for ml_id in (ML_TRACKCOUNT, ML_GAMEMODE, ML_VISITORS, ML_PLAYERSPECTATOR,
                  ML_LADDERLIMIT, ML_CURRENTRANKING, ML_TMEXCHANGE, ML_TOPLIST,
                  ML_FAVORITE, ML_CLOCK, ML_DISCORD, ML_FORCE_PLAY):
        await _broadcast(aseco, _empty(ml_id))


async def hide_all_score_bars(aseco: 'Aseco') -> None:
    """Broadcast empty MLs for all score-state bar widgets (at race start)."""
    for ml_id in (ML_NEXT_ENV, ML_NEXT_GAMEMODE, ML_EYEPIECE_SCORE,
                  ML_FAVORITE, ML_CLOCK):
        await _broadcast(aseco, _empty(ml_id))

