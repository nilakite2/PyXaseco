"""
checkpoints.py — Port of plugins/plugin.checkpoints.php

Tracks checkpoint times per player for comparison against local records.
Provides CP-panel display and /cptms /sectms commands.
Also validates finish integrity for anti-cheat purposes.

Public: checkpoints dict {login: CheckpointData}
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

from pyxaseco.helpers import _send_multipage, clean_tm_text, format_time
from pyxaseco.app_services import localdb_get_cps, localdb_set_cps

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public state (accessed by Dedimania and localdb)
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

    aseco.add_chat_command('cptms',  'Shows local checkpoint times', usage='/cptms [rank|me|cp N]')
    aseco.add_chat_command('sectms', 'Shows local sector times', usage='/sectms [rank|me|cp N]')

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
            cps = await localdb_get_cps(aseco, login)
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
        await localdb_set_cps(aseco, login,
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
        curr_idx = len(cp.curr_cps) - 1

        if checkpt[3] * laps_cpcount != checkpt[4] + 1:
            if cp.loclrec != -1 and curr_idx >= 0 and relcheck < len(cp.best_cps):
                diff = cp.curr_cps[curr_idx] - cp.best_cps[relcheck]
                _show_cp_diff(aseco, login, cp, relcheck + 1, diff)
        else:
            # Completed lap
            cp.curr_fin = checkpt[2]
            lap_time = cp.curr_cps[curr_idx] if curr_idx >= 0 else 0
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
    if score == 0:
        if mode == 1:
            cp.curr_cps = []
            cp.curr_fin = 2**31 - 1
        return

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

_ROWS_PER_PAGE = 12
_SPLITS_PER_PAGE = 6
_TABLE_WIDTHS = [1.43, .08, .32, .19] + [.135] * _SPLITS_PER_PAGE
_DETAIL_WIDTHS = [1.14, .21, .45, .45]


def _saved_splits(raw, score, minimum, *, laps):
    values = []
    for value in raw or ():
        try:
            split = 0 if isinstance(value, bool) else int(value)
        except (ValueError, TypeError, OverflowError):
            split = 0
        values.append(split if split > 0 else None)
    finish = None
    if not laps and len(values) > minimum and values[-1] == score:
        finish = values.pop()
    return tuple(values), finish


def _split_times(values, index, finish=None):
    current = finish if finish is not None else values[index] if index < len(values) else None
    previous = values[index - 1] if 0 < index <= len(values) else (0 if index == 0 else None)
    sector = current - previous if current is not None and previous is not None and current >= previous else None
    return current, sector


def _split_text(value):
    return '-' if value is None else '$n' + format_time(value)


async def chat_cptms(aseco: 'Aseco', command: dict):
    await chat_sectms(aseco, command, diff=False)


async def chat_sectms(aseco: 'Aseco', command: dict, diff: bool = True):
    player = command['author']
    server = aseco.server
    records = server.records
    command_name = 'sectms' if diff else 'cptms'

    async def error(message):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors('{#server}> {#error}' + message), player.login)

    mode = getattr(server.gameinfo, 'mode', 0)
    if mode == 4:
        await error('Timed checkpoint splits are not available in Stunts.')
        return

    challenge_uid = server.challenge.uid
    params = (command.get('params') or '').strip()
    args = params.lower().split()
    checkpoint = None
    initial_page = 1
    ranked = [(i + 1, rec) for i in range(records.count()) if (rec := records.get_record(i)) is not None]
    if not ranked:
        await error('No records found!')
        return
    if len(args) == 2 and args[0] == 'cp' and args[1].isascii() and args[1].isdecimal() and len(args[1]) <= 9:
        checkpoint = int(args[1])
    elif args == ['me']:
        ranked = [(rank, rec) for rank, rec in ranked if getattr(rec.player, 'login', None) == player.login]
    elif params:
        if not (params.isascii() and params.isdecimal() and len(params) <= 9):
            await error(f'Usage: /{command_name} [rank|me|cp N]')
            return
        requested_rank = int(params)
        ranked = [(rank, rec) for rank, rec in ranked if rank == requested_rank]
    if not ranked:
        await error('No matching record in the local leaderboard.')
        return

    minimum = max(0, (getattr(server.challenge, 'nbchecks', 0) or 0) - 1)
    entries = []
    for rank, rec in ranked:
        login = getattr(rec.player, 'login', '') or '?'
        name = clean_tm_text(getattr(rec.player, 'nickname', ''), keep_colors=False) or login
        name = name[:42].rstrip('$')
        values, finish = _saved_splits(rec.checks, rec.score, minimum, laps=mode == 3)
        entries.append((rank, name, rec.score, values, finish))
    label = 'Sector' if diff else 'CP'
    title = f'Local {label} Times'
    # Keep the record snapshot, but only format the currently visible page.
    if params and checkpoint is None:
        rank, name, score, values, finish = entries[0]
        count = len(values) + (finish is not None)
        page_count = max(1, (count + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE)

        def content(page):
            start = page * _ROWS_PER_PAGE
            rows = [['$zSplit', '$zElapsed', '$zSector']]
            rows.extend([
                'Finish' if i == len(values) else f'CP {i + 1}',
                *map(_split_text, _split_times(values, i, finish if i == len(values) else None)),
            ] for i in range(start, min(start + _ROWS_PER_PAGE, count)))
            if not count:
                rows.append(['No saved splits for this record.'])
            return f'{title} | #{rank} {name} $n{format_time(score)}', _DETAIL_WIDTHS, rows
    else:
        cp_count = max(len(entry[3]) for entry in entries)
        show_finish = any(entry[4] is not None for entry in entries)
        split_count = cp_count + show_finish
        split_pages = max(1, (split_count + _SPLITS_PER_PAGE - 1) // _SPLITS_PER_PAGE)
        player_pages = (len(entries) + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE
        page_count = split_pages * player_pages
        if checkpoint is not None:
            if not 1 <= checkpoint <= cp_count:
                await error(f'Checkpoint not available. Saved checkpoint range: 1-{cp_count}.' if cp_count
                            else 'No local records have saved checkpoints.')
                return
            initial_page += (checkpoint - 1) // _SPLITS_PER_PAGE * player_pages

        def content(page):
            split_page, player_page = divmod(page, player_pages)
            first = split_page * _SPLITS_PER_PAGE
            end = min(first + _SPLITS_PER_PAGE, split_count)
            rows = [['$z#', '$zPlayer', '$zTime'] + [
                '$zFin' if i == cp_count else f'$zCP{i + 1}' for i in range(first, end)]]
            for rank, name, score, values, finish in entries[player_page * _ROWS_PER_PAGE:(player_page + 1) * _ROWS_PER_PAGE]:
                column = 1 if diff else 0
                splits = [_split_text(_split_times(values, i)[column]) for i in range(first, min(end, cp_count))]
                if show_finish and end > cp_count:
                    sector = _split_times(values, len(values), finish)[1] if len(values) == cp_count else None
                    splits.append(_split_text(sector if diff else finish))
                rows.append([f'{rank}.', '$n' + name, _split_text(score), *splits])
            if not split_count:
                rows.append(['No local records have saved splits.'])
            span = f'CP {first + 1}-{min(end, cp_count)}' if first < cp_count else ''
            if show_finish and end > cp_count:
                span = span + ' + Fin' if span else 'Finish'
            caption = ' | '.join(part for part in (title, span, f'Players {player_page + 1}/{player_pages}') if part)
            return caption, _TABLE_WIDTHS, rows

    blank = [[] for _ in range(_ROWS_PER_PAGE + 2)]
    last_page = 0

    def prepare(controller, viewer):
        nonlocal last_page
        if controller.server.challenge.uid != challenge_uid:
            return False
        meta = viewer.msgs[0]
        page = meta[0]
        if not 1 <= page <= page_count:
            return False
        if last_page != page:
            if last_page:
                viewer.msgs[last_page] = blank
            head, widths, rows = content(page - 1)
            meta[1:3] = [head, widths]
            viewer.msgs[page] = rows + [[] for _ in range(len(blank) - len(rows))]
            last_page = page
        return True

    player.msgs = [[initial_page, title, _TABLE_WIDTHS, ['BgRaceScore2', 'Podium'], prepare]] + [blank] * page_count
    await _send_multipage(aseco, player)
