"""
plugin_bestsecs.py — Python port of plugin_bestsecs.php (v1.5)
            by DarkKnight, amgreborn

Tracks best sector times (time between consecutive checkpoints) for every
player on each challenge.  Two tables are maintained:

  secrecs_all  — one row per sector: the overall best time for that sector
  secrecs_own  — one row per (player, sector): each player's personal best

Chat commands
-------------
  /secrecs            — show overall best sector times for this map
  /mysecrecs          — show own sector times vs the overall best
  /delsecs            — admin: delete all secrecs for this map
  /delsec N or N-M    — admin: delete sector N, or range N-M
  /secrecs_cleanupdb  — masteradmin: remove orphaned / duplicate DB entries
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ML_BUTTON_ID = '0815470000122'   # ManiaLink ID for the Secrecs/My Secrecs button
ACTION_SECRECS    = 27008505
ACTION_MYSECRECS  = 27008504


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SecRec:
    time: int
    login: str
    cp: int          # sector index (0-based)


# ---------------------------------------------------------------------------
# Plugin state (module-level, reset on new challenge)
# ---------------------------------------------------------------------------

# Overall best per sector:  {sector_index: SecRec}
_tab_sec_recs: dict[int, SecRec] = {}

# Per-player personal bests: {login: {sector_index: SecRec}}
_tab_own_recs: dict[str, dict[int, SecRec]] = {}

# Last checkpoint info per player: {login: {'cpIndex': int, 'cpTime': int}}
_last_cp: dict[str, dict] = {}

# UID of the current challenge
_challenge_now: str = ''

# Number of checkpoints on the current map (finish counts as one)
_checkpoint_amount: int = 0

# Whether the button widget is visible (gamemode-dependent)
_show_secrecs: bool = False

# Config flags read from bestsecs.xml
_cfg_announce_sec: bool = True    # announce overall new record in chat
_cfg_announce_own: bool = True    # announce personal improvement in chat
_cfg_remove_on_delete: bool = True
_cfg_pos_x: float = 50.9
_cfg_pos_y: float = -30.0
_cfg_window_enabled: dict[int, bool] = {}   # gamemode int → bool


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(aseco: 'Aseco'):
    aseco.register_event('onSync',                      bestsecs_sync)
    aseco.register_event('onNewChallenge',              bestsecs_new_challenge)
    aseco.register_event('onCheckpoint',                bestsecs_checkpoint)
    aseco.register_event('onPlayerFinish1',             bestsecs_player_finish)
    aseco.register_event('onPlayerConnect',             bestsecs_player_connect)
    aseco.register_event('onPlayerManialinkPageAnswer', bestsecs_button_click)
    aseco.register_event('onTracklistChanged',          bestsecs_tracklist_changed)

    aseco.add_chat_command('secrecs',
        'Shows Sector Records')
    aseco.add_chat_command('mysecrecs',
        'Shows own Sector Records')
    aseco.add_chat_command('delsecs',
        'Deletes all secrecs on this challenge', True)
    aseco.add_chat_command('delsec',
        'Deletes sector N or range N-M on this challenge (e.g. /delsec 3 or /delsec 2-5)', True)
    aseco.add_chat_command('secrecs_cleanupdb',
        'Removes orphaned/duplicate secrecs from database', True)

    aseco.register_event('onChat_secrecs',          chat_secrecs)
    aseco.register_event('onChat_mysecrecs',        chat_mysecrecs)
    aseco.register_event('onChat_delsecs',          chat_delsecs)
    aseco.register_event('onChat_delsec',           chat_delsec)
    aseco.register_event('onChat_secrecs_cleanupdb', chat_secrecs_cleanupdb)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sec_to_time(ms: int, prefix: bool = False) -> str:
    """Format milliseconds as [+/-]M:SS.cs  (centiseconds, 2 digits)."""
    pre = ''
    if prefix:
        pre = '-' if ms < 0 else '+'
    ms = abs(ms)
    m  = ms // 60000
    s  = (ms % 60000) // 1000
    cs = (ms % 1000) // 10
    return f'{pre}{m}:{s:02d}.{cs:02d}'


async def _get_pool():
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        return await get_pool()
    except Exception:
        return None


async def _get_nickname(pool, login: str) -> str:
    """Fetch NickName from the players table."""
    if not pool:
        return login
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName FROM players WHERE Login=%s LIMIT 1', (login,))
                row = await cur.fetchone()
                return row[0] if row else login
    except Exception:
        return login


def _load_config(aseco: 'Aseco') -> None:
    global _cfg_announce_sec, _cfg_announce_own, _cfg_remove_on_delete
    global _cfg_pos_x, _cfg_pos_y, _cfg_window_enabled

    candidates = [
        Path(getattr(aseco, '_base_dir', '.')).resolve() / 'bestsecs.xml',
        Path('.').resolve() / 'bestsecs.xml',
    ]
    path = None
    for c in candidates:
        if c.exists():
            path = c
            break

    if path is None:
        logger.warning('[BestSecs] bestsecs.xml not found — using defaults')
        return

    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(str(path)).getroot()

        def _text(node, tag, default=''):
            el = node.find(tag)
            return el.text.strip() if el is not None and el.text else default

        def _bool_val(s: str) -> bool:
            return s.strip() in ('1', 'true', 'True', 'TRUE')

        pos = root.find('position')
        if pos is not None:
            try:
                _cfg_pos_x = float(_text(pos, 'xPos', '50.9'))
                _cfg_pos_y = float(_text(pos, 'yPos', '-30'))
            except ValueError:
                pass

        dr = root.find('display_recs')
        if dr is not None:
            _cfg_announce_sec = _bool_val(_text(dr, 'sec_recs', '1'))
            _cfg_announce_own = _bool_val(_text(dr, 'own_recs', '1'))

        _cfg_remove_on_delete = _bool_val(
            _text(root, 'remove_sec_from_db', '1'))

        from pyxaseco.models import Gameinfo
        we = root.find('window_enabled')
        if we is not None:
            _cfg_window_enabled = {
                Gameinfo.RNDS: _bool_val(_text(we, 'Rounds', '1')),
                Gameinfo.TA:   _bool_val(_text(we, 'TA',     '1')),
                Gameinfo.TEAM: _bool_val(_text(we, 'Team',   '1')),
                Gameinfo.LAPS: _bool_val(_text(we, 'Lap',    '1')),
                Gameinfo.STNT: _bool_val(_text(we, 'Stunts', '1')),
                Gameinfo.CUP:  _bool_val(_text(we, 'Cup',    '1')),
            }

        logger.info('[BestSecs] Config loaded from %s', path)
    except Exception as e:
        logger.warning('[BestSecs] Could not parse bestsecs.xml: %s', e)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _ensure_tables(pool) -> None:
    """Create secrecs_all and secrecs_own tables if they don't exist."""
    ddl_all = (
        'CREATE TABLE IF NOT EXISTS `secrecs_all` ('
        '`ID` INT NOT NULL AUTO_INCREMENT,'
        '`ChallengeID` VARCHAR(1000) NOT NULL,'
        '`Sector` INT NOT NULL,'
        '`PlayerNick` VARCHAR(255) NOT NULL,'
        '`Time` INT NOT NULL,'
        'PRIMARY KEY (`ID`)'
        ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    )
    ddl_own = (
        'CREATE TABLE IF NOT EXISTS `secrecs_own` ('
        '`ID` INT NOT NULL AUTO_INCREMENT,'
        '`ChallengeID` VARCHAR(1000) NOT NULL,'
        '`Sector` INT NOT NULL,'
        '`PlayerNick` VARCHAR(255) NOT NULL,'
        '`Time` INT NOT NULL,'
        'PRIMARY KEY (`ID`)'
        ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    )
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(ddl_all)
                await cur.execute(ddl_own)
    except Exception as e:
        logger.error('[BestSecs] Table creation failed: %s', e)


async def _load_all_from_db(challenge: str) -> None:
    global _tab_sec_recs
    _tab_sec_recs = {}
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT Sector, PlayerNick, Time FROM secrecs_all '
                    'WHERE ChallengeID=%s ORDER BY Sector', (challenge,))
                for row in await cur.fetchall():
                    sector, login, t = row
                    _tab_sec_recs[int(sector)] = SecRec(int(t), login, int(sector))
    except Exception as e:
        logger.error('[BestSecs] Load secrecs_all failed: %s', e)


async def _load_own_from_db(challenge: str, login: str) -> None:
    _tab_own_recs[login] = {}
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT Sector, Time FROM secrecs_own '
                    'WHERE ChallengeID=%s AND PlayerNick=%s ORDER BY Sector',
                    (challenge, login))
                for row in await cur.fetchall():
                    sector, t = row
                    _tab_own_recs[login][int(sector)] = SecRec(
                        int(t), login, int(sector))
    except Exception as e:
        logger.error('[BestSecs] Load secrecs_own for %s failed: %s', login, e)


async def _update_all(time_ms: int, sector: int, challenge: str, login: str) -> None:
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT ID FROM secrecs_all '
                    'WHERE ChallengeID=%s AND Sector=%s LIMIT 1',
                    (challenge, sector))
                row = await cur.fetchone()
                if row:
                    await cur.execute(
                        'UPDATE secrecs_all SET PlayerNick=%s, Time=%s '
                        'WHERE ChallengeID=%s AND Sector=%s',
                        (login, time_ms, challenge, sector))
                else:
                    await cur.execute(
                        'INSERT INTO secrecs_all '
                        '(ChallengeID, Sector, PlayerNick, Time) '
                        'VALUES (%s,%s,%s,%s)',
                        (challenge, sector, login, time_ms))
    except Exception as e:
        logger.error('[BestSecs] Update secrecs_all failed: %s', e)


async def _update_own(time_ms: int, sector: int, challenge: str, login: str) -> None:
    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT ID FROM secrecs_own '
                    'WHERE ChallengeID=%s AND Sector=%s AND PlayerNick=%s LIMIT 1',
                    (challenge, sector, login))
                row = await cur.fetchone()
                if row:
                    await cur.execute(
                        'UPDATE secrecs_own SET Time=%s '
                        'WHERE ChallengeID=%s AND Sector=%s AND PlayerNick=%s',
                        (time_ms, challenge, sector, login))
                else:
                    await cur.execute(
                        'INSERT INTO secrecs_own '
                        '(ChallengeID, Sector, PlayerNick, Time) '
                        'VALUES (%s,%s,%s,%s)',
                        (challenge, sector, login, time_ms))
    except Exception as e:
        logger.error('[BestSecs] Update secrecs_own for %s failed: %s', login, e)


# ---------------------------------------------------------------------------
# Button widget
# ---------------------------------------------------------------------------

async def _send_button(aseco: 'Aseco', login: str | None = None) -> None:
    """Send the Secrecs / My Secrecs button widget to one player or all."""
    if not _show_secrecs:
        return

    xml = (
        f'<manialink id="{ML_BUTTON_ID}">'
        '<format style="TextCardInfoSmall" textsize="1"/>'
        f'<frame posn="{_cfg_pos_x} {_cfg_pos_y} 1">'
        '<quad posn="4.5 0 0" sizen="18 2.5" halign="center" valign="center"'
        ' style="Bgs1InRace" substyle="BgWindow1"/>'
        f'<label posn="0 0.2 1" sizen="8 2" halign="center" valign="center"'
        f' text="$i$s$fffSecrecs" action="{ACTION_SECRECS}"/>'
        f'<label posn="8 0.2 1" sizen="8 2" halign="center" valign="center"'
        f' text="$i$s$fffMy Secrecs" action="{ACTION_MYSECRECS}"/>'
        '</frame>'
        '</manialink>'
    )
    if login:
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPageToLogin', login, xml, 0, False)
    else:
        await aseco.client.query_ignore_result(
            'SendDisplayManialinkPage', xml, 0, False)


async def _hide_button(aseco: 'Aseco') -> None:
    xml = f'<manialink id="{ML_BUTTON_ID}"></manialink>'
    await aseco.client.query_ignore_result(
        'SendDisplayManialinkPage', xml, 0, False)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def bestsecs_sync(aseco: 'Aseco', _data=None) -> None:
    global _challenge_now
    _load_config(aseco)
    pool = await _get_pool()
    if pool:
        await _ensure_tables(pool)

    ch = getattr(aseco.server, 'challenge', None)
    if ch:
        _challenge_now = getattr(ch, 'uid', '') or ''
        if _challenge_now:
            await _load_all_from_db(_challenge_now)
            for p in aseco.server.players.all():
                await _load_own_from_db(_challenge_now, p.login)

    _update_show_secrecs(aseco)
    await _send_button(aseco)


async def bestsecs_new_challenge(aseco: 'Aseco', challenge) -> None:
    global _challenge_now, _last_cp, _checkpoint_amount

    _challenge_now = getattr(challenge, 'uid', '') or ''
    _last_cp = {}

    await _load_all_from_db(_challenge_now)
    for p in aseco.server.players.all():
        await _load_own_from_db(_challenge_now, p.login)

    try:
        info = await aseco.client.query('GetCurrentChallengeInfo')
        _checkpoint_amount = int((info or {}).get('NbCheckpoints', 0) or 0)
    except Exception:
        _checkpoint_amount = 0

    _update_show_secrecs(aseco)
    if _show_secrecs:
        await _send_button(aseco)
    else:
        await _hide_button(aseco)


async def bestsecs_checkpoint(aseco: 'Aseco', params: list) -> None:
    """
    params: [uid, login, time_ms, lap, cp_index_zero_based, ...]

    Sector time = time at this CP minus time at the previous CP.
    CP 0 (first checkpoint) has sector time = absolute time at that CP.
    """
    global _tab_sec_recs, _tab_own_recs, _last_cp, _checkpoint_amount

    if len(params) < 5:
        return

    login  = params[1]
    timez  = int(params[2])
    cpz    = int(params[4])   # 0-based cp index
    do_update = True
    time2  = 0

    last = _last_cp.get(login)

    if last is None and cpz == 0:
        # First CP on a fresh run
        time2 = timez
    elif last is None and cpz != 0:
        # Server restart mid-race: we can't calculate this sector
        do_update = False
        # Exception: map has only 1 checkpoint (finish)
        if _checkpoint_amount == 1:
            time2 = timez
            do_update = True
    elif last is not None and cpz == 0:
        # Player restarted — first CP again
        time2 = timez
    else:
        # Normal inter-checkpoint sector
        time2 = timez - last['cpTime']

    if do_update and time2 > 0:
        pool = await _get_pool()

        # ── Overall best (secrecs_all) ─────────────────────────────────────
        existing = _tab_sec_recs.get(cpz)
        if existing is None or time2 < existing.time:
            _tab_sec_recs[cpz] = SecRec(time2, login, cpz)
            if _cfg_announce_sec:
                nick = await _get_nickname(pool, login)
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessage',
                    aseco.format_colors(
                        f'{{#highlite}}{nick}$z$29f'
                        f' claimed the record in sector {cpz}.'
                        f' Time: {_sec_to_time(time2)}'))
            await _update_all(time2, cpz, _challenge_now, login)

        # ── Personal best (secrecs_own) ────────────────────────────────────
        own = _tab_own_recs.setdefault(login, {})
        own_existing = own.get(cpz)
        if own_existing is None or time2 < own_existing.time:
            own[cpz] = SecRec(time2, login, cpz)
            if _cfg_announce_own:
                await aseco.client.query_ignore_result(
                    'ChatSendServerMessageToLogin',
                    aseco.format_colors(
                        f'> You improved your record in sector {cpz}.'
                        f' Time: {_sec_to_time(time2)}'),
                    login)
            await _update_own(time2, cpz, _challenge_now, login)

    _last_cp[login] = {'cpIndex': cpz, 'cpTime': timez}


async def bestsecs_player_finish(aseco: 'Aseco', finish) -> None:
    """Clear last-CP on finish so next run starts clean."""
    login = finish.player.login if finish and finish.player else ''
    if login:
        _last_cp.pop(login, None)


async def bestsecs_player_connect(aseco: 'Aseco', player: 'Player') -> None:
    await _load_own_from_db(_challenge_now, player.login)
    await _send_button(aseco, player.login)
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors(
            '{#server}>> {#message}This server runs BestSecs.'
            ' Type {#highlite}/secrecs {#message}or {#highlite}/mysecrecs'
            ' {#message}to view sector records.'),
        player.login)


async def bestsecs_button_click(aseco: 'Aseco', answer: list) -> None:
    if len(answer) < 3:
        return
    login  = answer[1]
    action = int(answer[2]) if answer[2] is not None else 0

    player = aseco.server.players.get_player(login)
    if not player:
        return

    if action == ACTION_SECRECS:
        await aseco.release_event('onChat_secrecs',
                                  {'author': player, 'params': ''})
    elif action == ACTION_MYSECRECS:
        await aseco.release_event('onChat_mysecrecs',
                                  {'author': player, 'params': ''})


async def bestsecs_tracklist_changed(aseco: 'Aseco', data=None) -> None:
    """Delete DB entries for a map removed from the server."""
    if not _cfg_remove_on_delete:
        return
    if not isinstance(data, (list, tuple)) or not data:
        return
    if data[0] != 'remove':
        return

    filename = data[1] if len(data) > 1 else ''
    if not filename:
        return

    try:
        info = await aseco.client.query('GetChallengeInfo', filename)
        uid = (info or {}).get('UId', '')
    except Exception:
        uid = ''

    if not uid:
        return

    pool = await _get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'DELETE FROM secrecs_all WHERE ChallengeID=%s', (uid,))
                await cur.execute(
                    'DELETE FROM secrecs_own WHERE ChallengeID=%s', (uid,))
        logger.info('[BestSecs] Removed secrecs for deleted map UID=%s', uid)
    except Exception as e:
        logger.error('[BestSecs] Delete secrecs for %s failed: %s', uid, e)


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

async def chat_secrecs(aseco: 'Aseco', command: dict) -> None:
    """Show overall best sector times for the current map."""
    from pyxaseco.helpers import display_manialink_multi

    player: Player = command['author']
    await _load_all_from_db(_challenge_now)

    pool = await _get_pool()
    header = 'Sector Records on this Map:'
    player.msgs = [[1, header, [1.25], ['Icons64x64_1', 'TrackInfo']]]

    recs = sorted(_tab_sec_recs.items())   # [(sector, SecRec), ...]

    if not recs:
        player.msgs.append([''])
        display_manialink_multi(aseco, player)
        return

    pages: dict[int, list] = {}
    overall_time = 0
    for idx, (sector, rec) in enumerate(recs):
        page = (idx // 15) + 1
        overall_time += rec.time
        sec_str = f'{sector:02d}'
        nick = await _get_nickname(pool, rec.login)
        line = aseco.format_colors(
            f'{{#highlite}}Sec{sec_str}: '
            f'{_sec_to_time(rec.time)} by {nick}')
        pages.setdefault(page, []).append([line])

    for pg in sorted(pages):
        rows = pages[pg]
        rows.append([''])
        rows.append([aseco.format_colors(
            f'{{#highlite}}Total Time: {_sec_to_time(overall_time)}')])
        player.msgs.append(rows)

    display_manialink_multi(aseco, player)


async def chat_mysecrecs(aseco: 'Aseco', command: dict) -> None:
    """Show the calling player's personal sector times vs the overall best."""
    from pyxaseco.helpers import display_manialink_multi

    player: Player = command['author']
    await _load_all_from_db(_challenge_now)
    await _load_own_from_db(_challenge_now, player.login)

    pool = await _get_pool()
    header = 'Your own Sector Records on this Map:'
    player.msgs = [[1, header, [1.25], ['Icons64x64_1', 'TrackInfo']]]

    own = _tab_own_recs.get(player.login, {})
    recs = sorted(own.items())   # [(sector, SecRec), ...]

    if not recs:
        player.msgs.append([''])
        display_manialink_multi(aseco, player)
        return

    pages: dict[int, list] = {}
    overall_time = 0
    for idx, (sector, rec) in enumerate(recs):
        page = (idx // 15) + 1
        overall_time += rec.time
        sec_str = f'{sector:02d}'

        best = _tab_sec_recs.get(sector)
        diff_str = ''
        best_nick = ''
        if best:
            diff_str = _sec_to_time(rec.time - best.time, prefix=True)
            best_nick = await _get_nickname(pool, best.login)

        line = aseco.format_colors(
            f'{{#highlite}}Sec{sec_str}: {_sec_to_time(rec.time)}'
            + (f' ( {diff_str} to TOP1 {best_nick}$z$o{{#highlite}} )' if best else ''))
        pages.setdefault(page, []).append([line])

    for pg in sorted(pages):
        rows = pages[pg]
        rows.append([''])
        rows.append([aseco.format_colors(
            f'{{#highlite}}Total Time: {_sec_to_time(overall_time)}')])
        player.msgs.append(rows)

    display_manialink_multi(aseco, player)


async def chat_delsecs(aseco: 'Aseco', command: dict) -> None:
    """Admin: delete all secrecs for the current map."""
    admin: Player = command['author']
    login = admin.login

    if not (aseco.is_admin(admin) or aseco.is_master_admin(admin)):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            '> You must be an Admin to use this command', login)
        return

    pool = await _get_pool()
    if pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'DELETE FROM secrecs_all WHERE ChallengeID=%s',
                    (_challenge_now,))
                await cur.execute(
                    'DELETE FROM secrecs_own WHERE ChallengeID=%s',
                    (_challenge_now,))

    _tab_sec_recs.clear()
    _tab_own_recs.clear()

    await _load_all_from_db(_challenge_now)
    for p in aseco.server.players.all():
        await _load_own_from_db(_challenge_now, p.login)

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        aseco.format_colors('> All SecRecs deleted!'), login)


async def chat_delsec(aseco: 'Aseco', command: dict) -> None:
    """Admin: delete sector N or range N-M.  Usage: /delsec 3  or  /delsec 2-5"""
    admin: Player = command['author']
    login = admin.login

    if not (aseco.is_admin(admin) or aseco.is_master_admin(admin)):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            '> You must be an Admin to use this command', login)
        return

    params = (command.get('params') or '').strip()

    async def _reply(msg: str) -> None:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(msg), login)

    # Refresh checkpoint count
    global _checkpoint_amount
    try:
        info = await aseco.client.query('GetCurrentChallengeInfo')
        _checkpoint_amount = int((info or {}).get('NbCheckpoints', 0) or 0)
    except Exception:
        pass

    numbers = re.findall(r'\d+', params)
    count = len(numbers)

    if count == 0:
        await _reply('> Usage: /delsec 2  or  /delsec 3-5')
        return

    if count == 1 and params == numbers[0]:
        # Single sector deletion
        sec = int(numbers[0])
        if not (0 <= sec < _checkpoint_amount):
            await _reply('> Please choose a valid sector.')
            return
        await _delete_sectors(sec, sec)
        await aseco.client.query_ignore_result(
            'ChatSendServerMessage',
            aseco.format_colors(f'> Sector {sec} deleted.'))
        return

    if count == 2:
        # Range N-M
        if not re.fullmatch(r'\d+-\d+', params):
            await _reply('> Usage: /delsec 2  or  /delsec 3-5')
            return
        lo, hi = int(numbers[0]), int(numbers[1])
        if lo > hi:
            lo, hi = hi, lo
        if lo == hi:
            if not (0 <= lo < _checkpoint_amount):
                await _reply('> Please choose a valid sector range.')
                return
            await _delete_sectors(lo, hi)
            await aseco.client.query_ignore_result(
                'ChatSendServerMessage',
                aseco.format_colors(f'> Sector {lo} deleted.'))
        else:
            if not (0 <= lo and hi < _checkpoint_amount):
                await _reply('> Please choose a valid sector range.')
                return
            await _delete_sectors(lo, hi)
            await aseco.client.query_ignore_result(
                'ChatSendServerMessage',
                aseco.format_colors(f'> Sectors {lo}-{hi} deleted.'))
        return

    await _reply('> Usage: /delsec 2  or  /delsec 3-5')


async def _delete_sectors(lo: int, hi: int) -> None:
    """Delete sectors lo..hi (inclusive) for the current challenge and reload."""
    pool = await _get_pool()
    if pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for sec in range(lo, hi + 1):
                    await cur.execute(
                        'DELETE FROM secrecs_all '
                        'WHERE ChallengeID=%s AND Sector=%s',
                        (_challenge_now, sec))
                    await cur.execute(
                        'DELETE FROM secrecs_own '
                        'WHERE ChallengeID=%s AND Sector=%s',
                        (_challenge_now, sec))
    await _load_all_from_db(_challenge_now)
    for login in list(_tab_own_recs):
        await _load_own_from_db(_challenge_now, login)


async def chat_secrecs_cleanupdb(aseco: 'Aseco', command: dict) -> None:
    """
    MasterAdmin: remove orphaned and duplicate entries from the DB.
    1. Delete rows with empty ChallengeID
    2. Delete rows whose UID is not in the current tracklist
    3. Remove duplicate rows from secrecs_own (keep lowest ID = oldest)
    """
    author: Player = command['author']
    login = author.login

    if not aseco.is_master_admin(author):
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            '> You must be a MasterAdmin to use this command', login)
        return

    async def _chat(msg: str) -> None:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors(msg), login)

    pool = await _get_pool()
    if not pool:
        await _chat('> Database not available.')
        return

    total_removed = 0

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:

            # 1. Remove rows with empty ChallengeID
            await cur.execute(
                "SELECT COUNT(*) FROM secrecs_all WHERE ChallengeID=''")
            n = (await cur.fetchone())[0]
            await cur.execute(
                "SELECT COUNT(*) FROM secrecs_own WHERE ChallengeID=''")
            n += (await cur.fetchone())[0]
            total_removed += n
            await cur.execute("DELETE FROM secrecs_all WHERE ChallengeID=''")
            await cur.execute("DELETE FROM secrecs_own WHERE ChallengeID=''")
            if n:
                await _chat(f'Removed {n} entries with empty ChallengeID.')

            # 2. Remove rows for maps no longer on the server
            try:
                tracks = await aseco.client.query('GetChallengeList', 5000, 0) or []
                live_uids = {
                    t.get('UId') or t.get('Uid', '') for t in tracks}
                live_uids.discard('')
            except Exception:
                live_uids = set()

            await cur.execute(
                'SELECT DISTINCT ChallengeID FROM secrecs_all')
            db_uids = [row[0] for row in await cur.fetchall()]

            old_removed = 0
            for uid in db_uids:
                if uid and uid not in live_uids:
                    await cur.execute(
                        'SELECT COUNT(*) FROM secrecs_all WHERE ChallengeID=%s',
                        (uid,))
                    n_all = (await cur.fetchone())[0]
                    await cur.execute(
                        'SELECT COUNT(*) FROM secrecs_own WHERE ChallengeID=%s',
                        (uid,))
                    n_own = (await cur.fetchone())[0]
                    await cur.execute(
                        'DELETE FROM secrecs_all WHERE ChallengeID=%s', (uid,))
                    await cur.execute(
                        'DELETE FROM secrecs_own WHERE ChallengeID=%s', (uid,))
                    old_removed += n_all + n_own
                    await _chat(
                        f'Removed {n_all + n_own} entries for old UID {uid}')

            total_removed += old_removed
            if old_removed:
                await _chat(f'Done removing old secrecs ({old_removed} entries).')

            # 3. Remove duplicates in secrecs_own — keep the best (lowest Time)
            #    per (ChallengeID, Sector, PlayerNick)
            dup_removed = 0
            await cur.execute(
                'SELECT DISTINCT ChallengeID FROM secrecs_own')
            challenges = [row[0] for row in await cur.fetchall()]

            for ch_uid in challenges:
                await cur.execute(
                    'SELECT MAX(Sector) FROM secrecs_own WHERE ChallengeID=%s',
                    (ch_uid,))
                row = await cur.fetchone()
                max_sector = int(row[0]) if row and row[0] is not None else -1

                for sector in range(max_sector + 1):
                    # Find all (PlayerNick, ID) pairs where that player has
                    # more than one entry — keep the row with the lowest Time
                    await cur.execute(
                        'SELECT PlayerNick, COUNT(*) as c '
                        'FROM secrecs_own '
                        'WHERE ChallengeID=%s AND Sector=%s '
                        'GROUP BY PlayerNick HAVING c > 1',
                        (ch_uid, sector))
                    duped = [r[0] for r in await cur.fetchall()]

                    for pnick in duped:
                        # Keep the single row with the minimum time; if tied,
                        # keep the one with the lowest ID.
                        await cur.execute(
                            'SELECT ID FROM secrecs_own '
                            'WHERE ChallengeID=%s AND Sector=%s '
                            'AND PlayerNick=%s ORDER BY Time ASC, ID ASC',
                            (ch_uid, sector, pnick))
                        ids = [r[0] for r in await cur.fetchall()]
                        # Delete everything except the first (best) ID
                        for del_id in ids[1:]:
                            await cur.execute(
                                'DELETE FROM secrecs_own WHERE ID=%s',
                                (del_id,))
                            dup_removed += 1

            total_removed += dup_removed
            if dup_removed:
                await _chat(
                    f'Done removing duplicate secrecs_own ({dup_removed} entries).')

    await _chat(
        f'{total_removed} entries were removed from database in total.')
    logger.info('[BestSecs] cleanupdb removed %d entries', total_removed)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_show_secrecs(aseco: 'Aseco') -> None:
    global _show_secrecs
    from pyxaseco.models import Gameinfo
    mode = getattr(aseco.server.gameinfo, 'mode', -1)
    _show_secrecs = bool(_cfg_window_enabled.get(mode, False))
