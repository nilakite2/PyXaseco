"""
plugin_autotime.py — Port of plugins/plugin.autotime.php

Automatically adjusts the TimeAttack timelimit for each track based on
the track's author time multiplied by a configurable factor.

Config: autotime.xml
  <autotime>
    <multiplicator>4</multiplicator>     <!-- author_time × N -->
    <mintime>3</mintime>                 <!-- minimum minutes -->
    <maxtime>12</maxtime>                <!-- maximum minutes -->
    <defaulttime>5</defaulttime>         <!-- fallback minutes if no author time -->
    <display>1</display>                 <!-- 0=off 1=chat 2=window -->
    <message>{#server}>> Set {1} timelimit for {2}: {3} (author: {4})</message>
  </autotime>

Must be placed AFTER plugin.rasp_jukebox in plugins.xml so the jukebox
is available for next-track lookup.
"""

from __future__ import annotations
import logging
import pathlib
from typing import TYPE_CHECKING

from pyxaseco.helpers import format_text, format_time, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# Config loaded from autotime.xml
_atl_config: dict   = {}
_atl_active: bool   = False
_atl_restart: bool  = False   # set True by ladder/restart votes so we skip


def register(aseco: 'Aseco'):
    aseco.register_event('onSync',    _load_config)
    aseco.register_event('onEndRace', _autotimelimit)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

async def _load_config(aseco: 'Aseco', _data):
    global _atl_config, _atl_active, _atl_restart
    _atl_active  = False
    _atl_restart = False

    base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
    cfg  = base / 'autotime.xml'
    if not cfg.exists():
        logger.warning('[AutoTime] autotime.xml not found — plugin disabled.')
        return

    try:
        from pyxaseco.core.config import parse_xml_file
        raw = parse_xml_file(cfg)
        if not raw:
            logger.warning('[AutoTime] Could not parse autotime.xml.')
            return

        atl = raw.get('AUTOTIME', {})
        def gi(key, default):
            v = atl.get(key.upper(), [str(default)])
            try: return int(v[0])
            except Exception: return default
        def gs(key, default):
            v = atl.get(key.upper(), [default])
            return v[0] if v else default

        _atl_config = {
            'MULTIPLICATOR': gi('MULTIPLICATOR', 4),
            'MINTIME':       gi('MINTIME',       3),
            'MAXTIME':       gi('MAXTIME',       12),
            'DEFAULTTIME':   gi('DEFAULTTIME',   5),
            'DISPLAY':       gi('DISPLAY',       1),
            'MESSAGE':       gs('MESSAGE',
                                '{#server}>> Set {1} timelimit for {2}: {3} (author: {4})'),
        }
        _atl_active = True
        aseco.console('[AutoTime] Loaded autotime.xml (×{1}, min={2}m, max={3}m)',
                      _atl_config['MULTIPLICATOR'],
                      _atl_config['MINTIME'],
                      _atl_config['MAXTIME'])
    except Exception as e:
        logger.warning('[AutoTime] Config error: %s', e)


# ---------------------------------------------------------------------------
# onEndRace — set timelimit for the next track
# ---------------------------------------------------------------------------

async def _autotimelimit(aseco: 'Aseco', _data):
    global _atl_restart

    if not _atl_active:
        return
    if _atl_restart:
        _atl_restart = False
        return

    try:
        next_info = await aseco.client.query('GetNextGameInfo') or {}
    except Exception:
        return

    TA = 1
    if next_info.get('GameMode') != TA:
        return
    if _atl_config.get('MULTIPLICATOR', 0) <= 0:
        return

    # Need at least one active player for meaningful next-track info
    has_player = any(not pl.isspectator for pl in aseco.server.players.all())

    # Get next track info
    challenge = await _get_next_track(aseco)
    if challenge is None:
        return

    authortime = getattr(challenge, 'authortime', 0) or 0
    mult = _atl_config['MULTIPLICATOR']
    mintime = _atl_config['MINTIME'] * 60 * 1000
    maxtime = _atl_config['MAXTIME'] * 60 * 1000
    default = _atl_config['DEFAULTTIME'] * 60 * 1000

    if authortime <= 0:
        newtime = default
        tag = 'default'
    else:
        newtime = authortime * mult
        newtime -= newtime % 1000  # round to seconds
        tag = 'new'

    if newtime < mintime:
        newtime = mintime
        tag = 'min'
    elif newtime > maxtime:
        newtime = maxtime
        tag = 'max'

    try:
        await aseco.client.query_ignore_result('SetTimeAttackLimit', newtime)
    except Exception as e:
        logger.debug('[AutoTime] SetTimeAttackLimit failed: %s', e)
        return

    track_name = strip_colors(getattr(challenge, 'name', '?'))
    time_str   = format_time(newtime)[:-3] if format_time(newtime).endswith('.00') else format_time(newtime)
    auth_str   = format_time(authortime) if authortime else '?'

    aseco.console('[AutoTime] Set {1} timelimit for [{2}]: {3} (author: {4})',
                  tag, track_name, time_str, auth_str)

    msg = format_text(_atl_config['MESSAGE'], tag,
                      strip_colors(track_name), time_str, auth_str)

    display = _atl_config.get('DISPLAY', 1)
    if display == 2:
        try:
            from pyxaseco.plugins.plugin_muting import send_window_message
            await send_window_message(aseco, msg, True)
            return
        except ImportError:
            pass
    if display > 0:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage', aseco.format_colors(msg))


async def _get_next_track(aseco: 'Aseco'):
    """Return a Challenge object for the next track (jukebox first, then server list)."""
    # Check jukebox
    try:
        from pyxaseco.plugins.plugin_rasp_jukebox import get_jukebox
        jb = get_jukebox()
        if isinstance(jb, dict) and jb:
            first = next(iter(jb.values()))
            fname = first.get('FileName', '')
            if fname:
                info = await aseco.client.query('GetChallengeInfo', fname) or {}
                if info:
                    from pyxaseco.models import Challenge
                    return Challenge(info)
    except Exception:
        pass

    # Fallback: server's next track index
    try:
        next_idx = await aseco.client.query('GetNextChallengeIndex') or 0
        track_list = await aseco.client.query('GetChallengeList', 1, next_idx) or []
        if track_list:
            info = await aseco.client.query('GetChallengeInfo', track_list[0]['FileName']) or {}
            if info:
                from pyxaseco.models import Challenge
                return Challenge(info)
    except Exception as e:
        logger.debug('[AutoTime] Failed to get next track: %s', e)
    return None


def set_restart():
    """Called by ladder/replay vote to suppress timelimit change on restart."""
    global _atl_restart
    _atl_restart = True
