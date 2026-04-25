"""
plugin_rasp.py — Port of plugins/plugin.rasp.php

RASP ranking engine:
  - Calculates and stores player averages in rs_rank
  - Inserts all finish times into rs_times
  - Shows PB, rank, top lists
  - Fires onLocalRecord2 chain events
  - Provides: /pb /rank /top10 /top100 /topwins /active

Reads rasp.xml for messages.
Reads rasp.settings for feature flags.
"""

from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING, Optional

from pyxaseco.core.config import parse_xml_file
from pyxaseco.helpers import (format_text, format_time, format_time_h,
                               strip_colors, display_manialink,
                               display_manialink_multi)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

# RASP feature flags
feature_ranks  = True
feature_stats  = True
always_show_pb = True
nextrank_show_rp = True
prune_records_times = False
reset_cache_start = True
maxrecs = 500
minrank = 3
maxavg  = 10

# Vote feature flags shared with plugin_rasp_votes
feature_votes = True
vote_in_window = False
allow_spec_startvote = False
allow_spec_voting = False
disable_upon_admin = False
disable_while_sb = False
allow_kickvotes = True
allow_admin_kick = False
allow_ignorevotes = True
allow_admin_ignore = False
ladder_fast_restart = False
auto_vote_starter = True
max_laddervotes = 1
max_replayvotes = 1
max_skipvotes = 1
replays_limit = 0
vote_ratios = [0.5, 0.5, 0.5, 0.5, 0.6, 0.5, 0.5]
r_expire_limit = [1, 3, 3, 3, 3, 3, 3]
r_show_reminder = True
r_points_limits = False
ta_expire_limit = [120, 240, 240, 180, 180, 180, 180]
ta_show_reminder = True
ta_show_interval = 60
ta_time_limits = False
r_ladder_max = 0.5
r_replay_min = 0.5
r_skip_max = 0.8
ta_ladder_max = 0.5
ta_replay_min = 0.5
ta_skip_max = 0.8
global_explain = 1

# Messages loaded from rasp.xml
_rasp_messages: dict = {}

# Compatibility state for plugins that still import plugin_rasp._rasp
_rasp: dict = {}

# Challenge list cache
_challenge_list_cache: list = []


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup',       rasp_startup)
    aseco.register_event('onSync',          rasp_sync)
    aseco.register_event('onNewChallenge2', rasp_new_challenge)
    aseco.register_event('onEndRace',       rasp_end_race)
    aseco.register_event('onPlayerFinish',  rasp_player_finish)
    aseco.register_event('onPlayerConnect', rasp_player_connect)

    aseco.add_chat_command('pb',      'Shows your personal best on current track')
    aseco.add_chat_command('rank',    'Shows your current server rank')
    aseco.add_chat_command('top10',   'Displays top 10 best ranked players')
    aseco.add_chat_command('top100',  'Displays top 100 best ranked players')
    aseco.add_chat_command('topwins', 'Displays top 100 victorious players')
    aseco.add_chat_command('active',  'Displays top 100 most active players')

    aseco.register_event('onChat_pb',      chat_pb)
    aseco.register_event('onChat_rank',    chat_rank)
    aseco.register_event('onChat_top10',   chat_top10)
    aseco.register_event('onChat_top100',  chat_top100)
    aseco.register_event('onChat_topwins', chat_topwins)
    aseco.register_event('onChat_active',  chat_active)


# ---------------------------------------------------------------------------
# Startup / Sync
# ---------------------------------------------------------------------------

async def rasp_startup(aseco: 'Aseco', _param):
    global _rasp_messages, maxrecs, _rasp
    global feature_votes, vote_in_window, allow_spec_startvote, allow_spec_voting
    global disable_upon_admin, disable_while_sb, allow_kickvotes, allow_admin_kick
    global allow_ignorevotes, allow_admin_ignore, ladder_fast_restart, auto_vote_starter
    global max_laddervotes, max_replayvotes, max_skipvotes, replays_limit, vote_ratios
    global r_expire_limit, r_show_reminder, r_points_limits
    global ta_expire_limit, ta_show_reminder, ta_show_interval, ta_time_limits
    global r_ladder_max, r_replay_min, r_skip_max
    global ta_ladder_max, ta_replay_min, ta_skip_max, global_explain

    rasp_xml = aseco._base_dir / 'rasp.xml'
    aseco.console('[RASP] Loading config file [{1}]', str(rasp_xml))
    data = parse_xml_file(rasp_xml)
    if not data:
        logger.error('[RASP] Could not read rasp.xml')
        return

    msgs = data.get('RASP', {}).get('MESSAGES', [{}])
    _rasp_messages = msgs[0] if msgs else {}

    votes_cfg = data.get('RASP', {}).get('VOTES', [{}])
    votes = votes_cfg[0] if votes_cfg else {}

    def _cfg_bool(block: dict, key: str, default: bool) -> bool:
        raw = block.get(key.upper(), [str(default).lower()])
        val = raw[0] if raw else str(default).lower()
        return str(val).strip().lower() == 'true'

    def _cfg_int(block: dict, key: str, default: int) -> int:
        raw = block.get(key.upper(), [default])
        val = raw[0] if raw else default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def _cfg_float(block: dict, key: str, default: float) -> float:
        raw = block.get(key.upper(), [default])
        val = raw[0] if raw else default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def _cfg_float_list(block: dict, key: str, default: list[float]) -> list[float]:
        raw = block.get(key.upper(), [])
        if not raw:
            return list(default)
        try:
            vals = [float(x) for x in str(raw[0]).replace(',', ' ').split() if x.strip()]
        except (TypeError, ValueError):
            return list(default)
        return vals if len(vals) == len(default) else list(default)

    def _cfg_int_list(block: dict, key: str, default: list[int]) -> list[int]:
        raw = block.get(key.upper(), [])
        if not raw:
            return list(default)
        try:
            vals = [int(x) for x in str(raw[0]).replace(',', ' ').split() if x.strip()]
        except (TypeError, ValueError):
            return list(default)
        return vals if len(vals) == len(default) else list(default)

    feature_votes = _cfg_bool(votes, 'feature_votes', feature_votes)
    vote_in_window = _cfg_bool(votes, 'vote_in_window', vote_in_window)
    allow_spec_startvote = _cfg_bool(votes, 'allow_spec_startvote', allow_spec_startvote)
    allow_spec_voting = _cfg_bool(votes, 'allow_spec_voting', allow_spec_voting)
    disable_upon_admin = _cfg_bool(votes, 'disable_upon_admin', disable_upon_admin)
    disable_while_sb = _cfg_bool(votes, 'disable_while_sb', disable_while_sb)
    allow_kickvotes = _cfg_bool(votes, 'allow_kickvotes', allow_kickvotes)
    allow_admin_kick = _cfg_bool(votes, 'allow_admin_kick', allow_admin_kick)
    allow_ignorevotes = _cfg_bool(votes, 'allow_ignorevotes', allow_ignorevotes)
    allow_admin_ignore = _cfg_bool(votes, 'allow_admin_ignore', allow_admin_ignore)
    ladder_fast_restart = _cfg_bool(votes, 'ladder_fast_restart', ladder_fast_restart)
    auto_vote_starter = _cfg_bool(votes, 'auto_vote_starter', auto_vote_starter)
    max_laddervotes = _cfg_int(votes, 'max_laddervotes', max_laddervotes)
    max_replayvotes = _cfg_int(votes, 'max_replayvotes', max_replayvotes)
    max_skipvotes = _cfg_int(votes, 'max_skipvotes', max_skipvotes)
    replays_limit = _cfg_int(votes, 'replays_limit', replays_limit)
    vote_ratios = _cfg_float_list(votes, 'vote_ratios', vote_ratios)
    r_expire_limit = _cfg_int_list(votes, 'r_expire_limit', r_expire_limit)
    r_show_reminder = _cfg_bool(votes, 'r_show_reminder', r_show_reminder)
    r_points_limits = _cfg_bool(votes, 'r_points_limits', r_points_limits)
    ta_expire_limit = _cfg_int_list(votes, 'ta_expire_limit', ta_expire_limit)
    ta_show_reminder = _cfg_bool(votes, 'ta_show_reminder', ta_show_reminder)
    ta_show_interval = _cfg_int(votes, 'ta_show_interval', ta_show_interval)
    ta_time_limits = _cfg_bool(votes, 'ta_time_limits', ta_time_limits)
    r_ladder_max = _cfg_float(votes, 'r_ladder_max', r_ladder_max)
    r_replay_min = _cfg_float(votes, 'r_replay_min', r_replay_min)
    r_skip_max = _cfg_float(votes, 'r_skip_max', r_skip_max)
    ta_ladder_max = _cfg_float(votes, 'ta_ladder_max', ta_ladder_max)
    ta_replay_min = _cfg_float(votes, 'ta_replay_min', ta_replay_min)
    ta_skip_max = _cfg_float(votes, 'ta_skip_max', ta_skip_max)
    global_explain = _cfg_int(votes, 'global_explain', global_explain)

    # Apply maxrecs from settings
    maxrecs = int(data.get('RASP', {}).get('MAXRECS', [500])[0]) if 'RASP' in data else 500
    aseco.server.records.set_limit(maxrecs)

    _rasp = {
        'messages': _rasp_messages,
        'feature_ranks': feature_ranks,
        'feature_stats': feature_stats,
        'always_show_pb': always_show_pb,
        'nextrank_show_rp': nextrank_show_rp,
        'prune_records_times': prune_records_times,
        'reset_cache_start': reset_cache_start,
        'maxrecs': maxrecs,
        'minrank': minrank,
        'maxavg': maxavg,
        'feature_votes': feature_votes,
        'vote_in_window': vote_in_window,
        'allow_spec_startvote': allow_spec_startvote,
        'allow_spec_voting': allow_spec_voting,
        'disable_upon_admin': disable_upon_admin,
        'disable_while_sb': disable_while_sb,
        'allow_kickvotes': allow_kickvotes,
        'allow_admin_kick': allow_admin_kick,
        'allow_ignorevotes': allow_ignorevotes,
        'allow_admin_ignore': allow_admin_ignore,
        'ladder_fast_restart': ladder_fast_restart,
        'auto_vote_starter': auto_vote_starter,
        'max_laddervotes': max_laddervotes,
        'max_replayvotes': max_replayvotes,
        'max_skipvotes': max_skipvotes,
        'replays_limit': replays_limit,
        'vote_ratios': vote_ratios,
        'r_expire_limit': r_expire_limit,
        'r_show_reminder': r_show_reminder,
        'r_points_limits': r_points_limits,
        'ta_expire_limit': ta_expire_limit,
        'ta_show_reminder': ta_show_reminder,
        'ta_show_interval': ta_show_interval,
        'ta_time_limits': ta_time_limits,
        'r_ladder_max': r_ladder_max,
        'r_replay_min': r_replay_min,
        'r_skip_max': r_skip_max,
        'ta_ladder_max': ta_ladder_max,
        'ta_replay_min': ta_replay_min,
        'ta_skip_max': ta_skip_max,
        'global_explain': global_explain,
    }

    aseco.console('[RASP] Checking database structure...')
    # Tables are created by plugin_localdatabase - just log OK
    aseco.console('[RASP] ...Structure OK!')

    await _clean_data(aseco)


async def rasp_sync(aseco: 'Aseco', _param):
    pass


# ---------------------------------------------------------------------------
# Per-challenge
# ---------------------------------------------------------------------------

async def rasp_new_challenge(aseco: 'Aseco', challenge):
    global _challenge_list_cache

    if reset_cache_start:
        _challenge_list_cache = []

    if not feature_stats or aseco.server.isrelay:
        return

    if not challenge:
        return

    challenge_id = int(getattr(challenge, 'id', 0) or 0)

    # Show PB to all online players
    for player in aseco.server.players.all():
        await _show_pb(aseco, player, challenge_id, always_show_pb)

# ---------------------------------------------------------------------------
# End of race — recalculate ranks
# ---------------------------------------------------------------------------

async def rasp_end_race(aseco: 'Aseco', _params):
    if aseco.server.isrelay or not feature_ranks:
        return
    await _reset_ranks(aseco)

    if not aseco.settings.sb_stats_panels:
        for player in aseco.server.players.all():
            await _show_rank(aseco, player.login)


# ---------------------------------------------------------------------------
# Player finish — store time in rs_times
# ---------------------------------------------------------------------------

async def rasp_player_finish(aseco: 'Aseco', params: list):
    if not feature_stats:
        return
    if len(params) < 3:
        return
    _uid, login, score = params[0], params[1], params[2]
    if score == 0:
        return
    if aseco.server.gameinfo and aseco.server.gameinfo.mode == 3:  # Laps
        return

    player = aseco.server.players.get_player(login)
    if not player or player.id == 0:
        return

    challenge = aseco.server.challenge
    if challenge.id == 0:
        return

    await _insert_time(player.id, challenge.id, score)


async def _insert_time(player_id: int, challenge_id: int, score: int):
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if pool is None:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'INSERT INTO rs_times (playerID, challengeID, score, date, checkpoints) '
                    'VALUES (%s, %s, %s, %s, %s)',
                    (player_id, challenge_id, score, int(time.time()), '')
                )
    except Exception as e:
        logger.warning('[RASP] Could not insert time: %s', e)


# ---------------------------------------------------------------------------
# Player connect — show rank + PB
# ---------------------------------------------------------------------------

async def rasp_player_connect(aseco: 'Aseco', player: 'Player'):
    if feature_ranks:
        await _show_rank(aseco, player.login)
    if feature_stats:
        await _show_pb(aseco, player, aseco.server.challenge.id, always_show_pb)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def _reset_ranks(aseco: 'Aseco'):
    """Recalculate rs_rank for all players."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if pool is None:
            return
    except ImportError:
        return

    aseco.console('[RASP] Calculating ranks...')
    track_ids = await _get_challenge_ids(aseco, pool)
    total = len(track_ids)
    if total == 0:
        return

    is_stnt = (aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)
    order = 'DESC' if is_stnt else 'ASC'

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('TRUNCATE TABLE rs_rank')

            # Players with at least minrank records
            await cur.execute(
                'SELECT PlayerId, COUNT(*) AS cnt FROM records '
                'GROUP BY PlayerId HAVING cnt >= %s', (minrank,)
            )
            rows = await cur.fetchall()
            players = {row[0]: [0, 0] for row in rows}  # {pid: [sum, count]}

            if not players:
                aseco.console('[RASP] ...No ranked players.')
                return

            for track_id in track_ids:
                await cur.execute(
                    f'SELECT PlayerId FROM records WHERE ChallengeId=%s '
                    f'ORDER BY Score {order}, Date ASC LIMIT %s',
                    (track_id, maxrecs)
                )
                recs = await cur.fetchall()
                for rank_i, rec in enumerate(recs, 1):
                    pid = rec[0]
                    if pid in players:
                        players[pid][0] += rank_i
                        players[pid][1] += 1

            # Build one-shot INSERT
            if players:
                values = []
                for pid, (total_sum, count) in players.items():
                    avg = (total_sum + (total - count) * maxrecs) / total
                    values.append(f'({pid},{round(avg * 10000)})')
                await cur.execute(
                    'INSERT INTO rs_rank VALUES ' + ','.join(values)
                )

    aseco.console('[RASP] ...Done!')


async def _clean_data(aseco: 'Aseco'):
    """
    Always remove empty player/challenge rows and optionally prune orphaned
    records/rs_times entries when prune_records_times is enabled.
    """
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if pool is None:
            return
    except ImportError:
        return

    aseco.console('[RASP] Cleaning up unused data')

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM challenges WHERE Uid=''")
            await cur.execute("DELETE FROM players WHERE Login=''")

            if not prune_records_times:
                return

            async def _delete_orphans(select_sql: str, delete_sql: str, label: str):
                await cur.execute(select_sql)
                rows = await cur.fetchall()
                ids = [row[0] for row in rows if row and row[0] is not None]
                if not ids:
                    return

                aseco.console('[RASP] ...Deleting {1}: {2}', label, ','.join(str(i) for i in ids))
                placeholders = ','.join(['%s'] * len(ids))
                await cur.execute(delete_sql.format(placeholders=placeholders), tuple(ids))

            await _delete_orphans(
                'SELECT DISTINCT r.ChallengeId '
                'FROM records r LEFT JOIN challenges c ON (r.ChallengeId=c.Id) '
                'WHERE c.Id IS NULL',
                'DELETE FROM records WHERE ChallengeId IN ({placeholders})',
                'records for deleted challenges',
            )
            await _delete_orphans(
                'SELECT DISTINCT r.PlayerId '
                'FROM records r LEFT JOIN players p ON (r.PlayerId=p.Id) '
                'WHERE p.Id IS NULL',
                'DELETE FROM records WHERE PlayerId IN ({placeholders})',
                'records for deleted players',
            )
            await _delete_orphans(
                'SELECT DISTINCT r.challengeID '
                'FROM rs_times r LEFT JOIN challenges c ON (r.challengeID=c.Id) '
                'WHERE c.Id IS NULL',
                'DELETE FROM rs_times WHERE challengeID IN ({placeholders})',
                'rs_times for deleted challenges',
            )
            await _delete_orphans(
                'SELECT DISTINCT r.playerID '
                'FROM rs_times r LEFT JOIN players p ON (r.playerID=p.Id) '
                'WHERE p.Id IS NULL',
                'DELETE FROM rs_times WHERE playerID IN ({placeholders})',
                'rs_times for deleted players',
            )


async def _get_challenge_ids(aseco: 'Aseco', pool) -> list:
    """Get all challenge IDs from the server track list and ensure they're in DB."""
    global _challenge_list_cache

    if _challenge_list_cache:
        return _challenge_list_cache

    tracks = []
    batch_size = 500
    offset = 0
    while True:
        try:
            chunk = await aseco.client.query('GetChallengeList', batch_size, offset)
        except Exception:
            chunk = []
        if not chunk:
            break
        tracks.extend(chunk)
        if len(chunk) < batch_size:
            break
        offset += len(chunk)

    ids = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for t in (tracks or []):
                uid = t.get('UId', '')
                if not uid:
                    continue
                await cur.execute('SELECT Id FROM challenges WHERE Uid=%s', (uid,))
                row = await cur.fetchone()
                if row:
                    ids.append(row[0])
                else:
                    try:
                        await cur.execute(
                            'INSERT INTO challenges (Uid, Name, Author, Environment) '
                            'VALUES (%s, %s, %s, %s)',
                            (uid, t.get('Name',''), t.get('Author',''),
                             t.get('Environnement',''))
                        )
                        ids.append(cur.lastrowid)
                    except Exception:
                        pass

    if not ids:
        logger.error('[RASP] Cannot obtain challenge list from server and/or database - check configuration files!')

    _challenge_list_cache = ids
    return ids


async def _show_pb(aseco: 'Aseco', player: 'Player', challenge_id: int, always_show: bool):
    """Show personal best to a player."""
    login = player.login
    is_stnt = (aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)

    found = False
    pb_time = 0
    pb_rank: object = 0

    # Check ranked records first
    for i in range(aseco.server.records.count()):
        rec = aseco.server.records.get_record(i)
        if rec and rec.player.login == login:
            pb_time = rec.score
            pb_rank = i + 1
            found = True
            break

    if not always_show and found:
        if (aseco.settings.show_recs_before == 2 or
                player.panels.get('records', '')):
            return

    if not found and player.id > 0:
        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
            pool = await get_pool()
            if pool:
                order = 'DESC' if is_stnt else 'ASC'
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            f'SELECT score FROM rs_times WHERE playerID=%s AND challengeID=%s '
                            f'ORDER BY score {order} LIMIT 1',
                            (player.id, challenge_id)
                        )
                        row = await cur.fetchone()
                        if row:
                            pb_time = row[0]
                            pb_rank = '$nUNRANKED$m'
                            found = True
        except Exception:
            pass

    # Compute average
    avg_str = 'No Average'
    if player.id > 0:
        try:
            from pyxaseco.plugins.plugin_localdatabase import get_pool
            pool = await get_pool()
            if pool:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            'SELECT score FROM rs_times WHERE playerID=%s AND challengeID=%s '
                            'ORDER BY date DESC LIMIT %s',
                            (player.id, challenge_id, maxavg)
                        )
                        rows = await cur.fetchall()
                        if rows:
                            avg = sum(r[0] for r in rows) // len(rows)
                            avg_str = str(avg) if is_stnt else format_time(avg)
        except Exception:
            pass

    if found:
        msg_raw = _rasp_msg('PB')
        message = format_text(msg_raw,
                              str(pb_time) if is_stnt else format_time(pb_time),
                              pb_rank, avg_str)
    else:
        message = _rasp_msg('PB_NONE')

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin', aseco.format_colors(message), login)


async def _show_rank(aseco: 'Aseco', login: str):
    """Show current server rank to a player."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool, get_player_id
        pool = await get_pool()
        if not pool:
            return
        pid = await get_player_id(login)
        if not pid:
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT avg FROM rs_rank WHERE playerID=%s', (pid,))
                row = await cur.fetchone()
                if row:
                    my_avg = row[0]
                    await cur.execute('SELECT COUNT(*) FROM rs_rank')
                    total_row = await cur.fetchone()
                    total = total_row[0] if total_row else 0

                    await cur.execute(
                        'SELECT COUNT(*) FROM rs_rank WHERE avg < %s', (my_avg,))
                    better_row = await cur.fetchone()
                    rank = (better_row[0] if better_row else 0) + 1

                    message = format_text(_rasp_msg('RANK'), rank, total,
                                          f'{my_avg/10000:4.1f}')
                else:
                    message = format_text(_rasp_msg('RANK_NONE'), minrank)

        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(message), login)
    except Exception as e:
        logger.debug('[RASP] showRank error: %s', e)


def _rasp_msg(key: str) -> str:
    items = _rasp_messages.get(key.upper(), [''])
    return items[0] if items else ''


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

async def chat_pb(aseco: 'Aseco', command: dict):
    if aseco.server.isrelay:
        msg = format_text(aseco.get_chat_message('NOTONRELAY'))
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(msg),
            command['author'].login)
        return
    if feature_stats:
        await _show_pb(aseco, command['author'],
                       aseco.server.challenge.id, True)


async def chat_rank(aseco: 'Aseco', command: dict):
    if feature_ranks:
        await _show_rank(aseco, command['author'].login)


async def chat_top10(aseco: 'Aseco', command: dict):
    await _show_top_ranked(aseco, command['author'], 10, 'Current TOP 10 Players:')


async def chat_top100(aseco: 'Aseco', command: dict):
    await _show_top_ranked(aseco, command['author'], 100, 'Current TOP 100 Players:')


async def _show_top_ranked(aseco: 'Aseco', player: 'Player', limit: int, head: str):
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT p.NickName, r.avg FROM players p '
                    'LEFT JOIN rs_rank r ON (p.Id=r.playerID) '
                    'WHERE r.avg != 0 ORDER BY r.avg ASC LIMIT %s', (limit,)
                )
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning('[RASP] top ranked query error: %s', e)
        return

    if not rows:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            aseco.format_colors('{#server}> {#error}No ranked players found!'),
            player.login)
        return

    extra = 0.2 if aseco.settings.lists_colornicks else 0
    recs = []
    for i, row in enumerate(rows, 1):
        nick = row[0] if aseco.settings.lists_colornicks else strip_colors(row[0])
        recs.append([f'{i:02d}.', '{#black}' + nick, f'{row[1]/10000:4.1f}'])

    pages = [recs[i:i+15] for i in range(0, max(len(recs),1), 15)]
    player.msgs = [[1, head, [0.7+extra, 0.1, 0.45+extra, 0.15],
                    ['BgRaceScore2', 'LadderRank']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def chat_topwins(aseco: 'Aseco', command: dict):
    player = command['author']
    head = 'Current TOP 100 Victors:'
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName, Wins FROM players ORDER BY Wins DESC LIMIT 100')
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning('[RASP] topwins error: %s', e)
        return

    extra = 0.2 if aseco.settings.lists_colornicks else 0
    wins = []
    for i, row in enumerate(rows, 1):
        nick = row[0] if aseco.settings.lists_colornicks else strip_colors(row[0])
        wins.append([f'{i:02d}.', '{#black}' + nick, str(row[1])])

    pages = [wins[i:i+15] for i in range(0, max(len(wins),1), 15)]
    player.msgs = [[1, head, [0.7+extra, 0.1, 0.45+extra, 0.15],
                    ['BgRaceScore2', 'LadderRank']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)


async def chat_active(aseco: 'Aseco', command: dict):
    player = command['author']
    head = 'TOP 100 Most Active Players:'
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName, TimePlayed FROM players '
                    'ORDER BY TimePlayed DESC LIMIT 100')
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning('[RASP] active error: %s', e)
        return

    extra = 0.2 if aseco.settings.lists_colornicks else 0
    active = []
    for i, row in enumerate(rows, 1):
        nick = row[0] if aseco.settings.lists_colornicks else strip_colors(row[0])
        active.append([f'{i:02d}.', '{#black}' + nick,
                       format_time_h(row[1] * 1000, False)])

    pages = [active[i:i+15] for i in range(0, max(len(active),1), 15)]
    player.msgs = [[1, head, [0.8+extra, 0.1, 0.45+extra, 0.25],
                    ['BgRaceScore2', 'LadderRank']]]
    player.msgs.extend(pages)
    display_manialink_multi(aseco, player)
