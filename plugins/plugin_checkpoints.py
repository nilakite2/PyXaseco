"""
plugin_checkpoints.py — Port of plugins/plugin.checkpoints.php

Tracks checkpoint times per player for comparison against local records.
Provides CP-panel display and /cptms /sectms commands.
Also validates finish integrity for anti-cheat purposes.

Public: checkpoints dict {login: CheckpointData}
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

from pyxaseco.helpers import format_text, strip_colors, format_time

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public state (accessed by plugin_dedimania and plugin_localdatabase)
# ---------------------------------------------------------------------------

@dataclass
class CheckpointData:
    loclrec: int = -1          # -1=off, 0=own/last, 1..N=specific record
    dedirec: int = -1          # -1=off, 0=own/last, 1..30=specific dedi
    best_time: float = 0.0
    best_fin: int = 2**31 - 1  # PHP_INT_MAX
    best_cps: list = field(default_factory=list)
    curr_fin: int = 2**31 - 1
    curr_cps: list = field(default_factory=list)
    speccers: list = field(default_factory=list)


checkpoints: dict = {}        # {login: CheckpointData}
checkpoint_tests: bool = False
laps_cpcount: int = 0


def register(aseco: 'Aseco'):
    aseco.register_event('onPlayerConnect',    _addplayer_cp)
    aseco.register_event('onPlayerDisconnect', _removeplayer_cp)
    aseco.register_event('onNewChallenge',     _reset_checkp)
    aseco.register_event('onBeginRound',       _clear_curr_cp)
    aseco.register_event('onEndRace',          _disable_checkp)
    aseco.register_event('onRestartChallenge', _restart_checkp)
    aseco.register_event('onCheckpoint',       _store_checkp)
    aseco.register_event('onPlayerFinish1',    _store_finish)
    aseco.register_event('onPlayerInfoChanged',_spec_togglecp)

    aseco.add_chat_command('cpsspec','Shows checkpoints of spectated player')
    aseco.add_chat_command('cptms',  "Displays all local records' checkpoint times")
    aseco.add_chat_command('sectms', "Displays all local records' sector times")

    aseco.register_event('onChat_cpsspec', chat_cpsspec)
    aseco.register_event('onChat_cptms',   chat_cptms)
    aseco.register_event('onChat_sectms',  chat_sectms)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def _addplayer_cp(aseco: 'Aseco', player):
    login = player.login
    checkpoints[login] = CheckpointData()
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    LAPS = 3
    if mode == LAPS:
        checkpoints[login].curr_fin = 0

    if aseco.settings.display_checkpoints:
        try:
            from pyxaseco.plugins.plugin_localdatabase import ldb_get_cps
            cps = await ldb_get_cps(aseco, login)
            if cps:
                checkpoints[login].loclrec = cps.get('cps', -1)
                checkpoints[login].dedirec = cps.get('dedicps', -1)
                return
        except Exception:
            pass
        if aseco.settings.auto_enable_cps:
            checkpoints[login].loclrec = 0
        if aseco.settings.auto_enable_dedicps:
            checkpoints[login].dedirec = 0


async def _removeplayer_cp(aseco: 'Aseco', player):
    login = player.login
    if login not in checkpoints:
        return
    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_set_cps
        await ldb_set_cps(aseco, login,
                          checkpoints[login].loclrec,
                          checkpoints[login].dedirec)
    except Exception:
        pass
    checkpoints.pop(login, None)


async def _reset_checkp(aseco: 'Aseco', challenge):
    global laps_cpcount
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    LAPS = 3

    for login, cp in checkpoints.items():
        cp.best_cps = []
        cp.curr_cps = []
        cp.best_fin = 2**31 - 1
        cp.curr_fin = 0 if mode == LAPS else 2**31 - 1

    if aseco.settings.display_checkpoints:
        for login, cp in checkpoints.items():
            lrec = cp.loclrec - 1
            records = aseco.server.records
            if lrec + 1 > 0:
                if lrec > records.count() - 1:
                    lrec = records.count() - 1
                if lrec >= 0:
                    curr = records.get_record(lrec)
                    if curr and curr.checks and curr.score == (curr.checks[-1] if curr.checks else -1):
                        cp.best_fin = curr.score
                        cp.best_cps = list(curr.checks)
            elif lrec + 1 == 0:
                for i in range(records.count()):
                    curr = records.get_record(i)
                    if curr and curr.player and curr.player.login == login:
                        if curr.checks and curr.score == (curr.checks[-1] if curr.checks else -1):
                            cp.best_fin = curr.score
                            cp.best_cps = list(curr.checks)
                        break

    laps_cpcount = getattr(challenge, 'nbchecks', 0)


async def _clear_curr_cp(aseco: 'Aseco', _param=None):
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    STNT, LAPS = 4, 3
    if mode == STNT or getattr(aseco, 'warmup_phase', False):
        return
    for login, cp in checkpoints.items():
        cp.curr_cps = []
        cp.curr_fin = 0 if mode == LAPS else 2**31 - 1


async def _disable_checkp(aseco: 'Aseco', _data):
    global checkpoint_tests
    checkpoint_tests = True


async def _restart_checkp(aseco: 'Aseco', _data):
    global checkpoint_tests
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    LAPS = 3
    for cp in checkpoints.values():
        cp.curr_cps = []
        cp.curr_fin = 0 if mode == LAPS else 2**31 - 1
    checkpoint_tests = True


async def _store_checkp(aseco: 'Aseco', checkpt: list):
    """Store checkpoint data for a player and optionally show CP panel diff."""
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    STNT, LAPS, TA = 4, 3, 1
    if mode == STNT:
        return
    if len(checkpt) < 5:
        return

    login = checkpt[1]
    if login not in checkpoints:
        return

    cp = checkpoints[login]

    if mode != LAPS:
        # TA reset on first CP
        if mode == TA and checkpt[4] == 0:
            cp.curr_cps = []
        # Anti-cheat
        if checkpt[2] <= 0 or checkpt[4] != len(cp.curr_cps):
            return
        cp.curr_cps.append(checkpt[2])

        if cp.loclrec != -1 and checkpt[4] < len(cp.best_cps):
            diff = cp.curr_cps[checkpt[4]] - cp.best_cps[checkpt[4]]
            _show_cp_diff(aseco, login, cp, checkpt[4] + 1, diff)
    else:
        # Laps mode
        global laps_cpcount
        if checkpt[2] <= 0 or checkpt[4] < 0:
            return
        if laps_cpcount == 0 and checkpt[3] == 1:
            laps_cpcount = checkpt[4] + 1
        relcheck = (checkpt[4] % laps_cpcount) if laps_cpcount > 0 else checkpt[4]
        cp.curr_cps.append(checkpt[2] - cp.curr_fin)

        if checkpt[3] * laps_cpcount != checkpt[4] + 1:
            if cp.loclrec != -1 and relcheck < len(cp.best_cps):
                diff = cp.curr_cps[relcheck] - cp.best_cps[relcheck]
                _show_cp_diff(aseco, login, cp, relcheck + 1, diff)
        else:
            # Completed lap
            cp.curr_fin = checkpt[2]
            lap_time = cp.curr_cps[relcheck] if cp.curr_cps else 0
            if lap_time < cp.best_fin:
                cp.best_fin = lap_time
                cp.best_cps = list(cp.curr_cps)
                import time as _t
                cp.best_time = _t.monotonic()
            cp.curr_cps = []


def _show_cp_diff(aseco: 'Aseco', login: str, cp: CheckpointData, check, diff: int):
    import asyncio

    if diff < 0:
        sign = '$00f-'
        diff = abs(diff)
    elif diff == 0:
        sign = '$00f'
    else:
        sign = '$f00+'

    sec = diff // 1000
    hun = (diff - sec * 1000) / 10
    msg = f'{sign}{sec}.{hun:02.0f}'

    async def _do():
        try:
            await aseco.release_event('onEyepieceSetCpDelta', {
                'login': login,
                'text': msg,
            })

            await asyncio.sleep(1.2)

            await aseco.release_event('onEyepieceClearCpDelta', {
                'login': login,
            })
        except Exception as e:
            logger.exception('CP delta widget failed: %s', e)

    asyncio.ensure_future(_do())


async def _store_finish(aseco: 'Aseco', finish_item):
    mode = getattr(aseco.server.gameinfo, 'mode', 0)
    LAPS, STNT = 3, 4
    if mode in (LAPS, STNT):
        return

    # Support both:
    #   [uid, login, score]
    # and object payloads with .player / .score
    if isinstance(finish_item, list):
        if len(finish_item) < 3:
            return
        _uid, login, score = finish_item[0], finish_item[1], finish_item[2]
    else:
        if not getattr(finish_item, 'player', None):
            return
        login = finish_item.player.login
        score = finish_item.score

    if login not in checkpoints:
        return

    cp = checkpoints[login]
    cp.curr_cps.sort()

    if score > 0:
        if cp.curr_cps and score == cp.curr_cps[-1]:
            cp.curr_fin = score
            if cp.best_fin <= 0 or cp.curr_fin < cp.best_fin:
                cp.best_fin = cp.curr_fin
                cp.best_cps = list(cp.curr_cps)
                import time as _t
                cp.best_time = _t.monotonic()


async def _spec_togglecp(aseco: 'Aseco', playerinfo: dict):
    pass


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

async def chat_cpsspec(aseco: 'Aseco', command: dict):
    login = command['author'].login
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors('{#server}> {#error}CPS spectator mode requires TMF panels plugin.'),
        login)


async def chat_cptms(aseco: 'Aseco', command: dict):
    await chat_sectms(aseco, command, diff=False)


async def chat_sectms(aseco: 'Aseco', command: dict, diff: bool = True):
    player = command['author']
    login = player.login
    total = aseco.server.records.count()
    if not total:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No records found!'), login)
        return

    label = 'Sector' if diff else 'CP'
    header = f'Current TOP {aseco.server.records.max} Local {label} Times:'
    rows = [['#', 'Time']]
    cpsmax = 12
    for i in range(total):
        rec = aseco.server.records.get_record(i)
        if not rec:
            continue
        row = [f'{i+1:02d}.', format_time(rec.score)]
        if rec.checks:
            pr = 0
            for j, cp in enumerate(rec.checks[:cpsmax]):
                row.append(f'$n{format_time(cp - pr)}')
                if diff:
                    pr = cp
            if len(rec.checks) > cpsmax:
                row.append('+')
        rows.append(row)

    pages = [rows[k:k+14] for k in range(0, len(rows), 14)]
    widths = [1.0, 0.1, 0.18] + [0.1] * min(cpsmax, 12)
    player.msgs = [[1, header, widths, ['BgRaceScore2', 'Podium']]]
    player.msgs.extend(pages)
    from pyxaseco.helpers import display_manialink_multi
    display_manialink_multi(aseco, player)
