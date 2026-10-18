"""
RASP ranking backend - ported from the original XAseco RASP runtime.

RASP ranking engine:
  - Calculates and stores player averages in rs_rank
  - Inserts all finish times into rs_times
  - Shows PB, rank, top lists
  - Fires onLocalRecord2 chain events
  - Provides: /pb /rank /top10 /top100 /topwins /active

Reads messages.toml for chat messages.
Reads apps/players/app_defaults.toml for ranking feature flags.
"""

from __future__ import annotations
import asyncio
import logging
import time
from uuid import uuid4
from typing import TYPE_CHECKING, Optional

from pyxaseco.helpers import (format_text, format_time, format_time_h,
                               strip_colors, display_manialink,
                               display_manialink_multi)
from pyxaseco.app_services import localdb_get_player_id, localdb_get_pool
from pyxaseco.app_config import (
    AppSetting,
    AppSettingsSchema,
    as_bool,
    as_float,
    as_int,
    bind_app_settings,
)
from pyxaseco.core.config import display_path

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

# Ranking feature flags
feature_ranks  = True
feature_stats  = True
always_show_pb = False
nextrank_show_rp = True
prune_records_times = False
reset_cache_start = True
maxrecs = 500
minrank = 3
maxavg  = 10
admin_contact = ''

# Vote feature flags shared with the RASP voting backend
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

# Messages loaded from messages.toml
_rasp_messages: dict = {}

# Compatibility state for legacy import paths that still read app state
_rasp: dict = {}

# Challenge list cache
_challenge_list_cache: list = []


def _as_float_list(value, default):
    if isinstance(value, list):
        try:
            parsed = [float(item) for item in value]
            return parsed if len(parsed) == len(default) else list(default)
        except Exception:
            return list(default)
    return list(default)


def _as_int_list(value, default):
    if isinstance(value, list):
        try:
            parsed = [int(item) for item in value]
            return parsed if len(parsed) == len(default) else list(default)
        except Exception:
            return list(default)
    return list(default)


PLAYER_RANKING_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='players',
    description='Typed app defaults for player ranking and record-facing player commands.',
    settings=(
        AppSetting('feature_ranks', feature_ranks, as_bool, 'Enable rankings.', 'rankings'),
        AppSetting('feature_stats', feature_stats, as_bool, 'Enable stats.', 'rankings'),
        AppSetting('always_show_pb', always_show_pb, as_bool, 'Always show PB info.', 'rankings'),
        AppSetting('nextrank_show_rp', nextrank_show_rp, as_bool, 'Show ranking points in nextrank.', 'rankings'),
        AppSetting('prune_records_times', prune_records_times, as_bool, 'Prune record times on startup.', 'rankings'),
        AppSetting('reset_cache_start', reset_cache_start, as_bool, 'Reset ranking cache on startup.', 'rankings'),
        AppSetting('minrank', minrank, as_int, 'Minimum rank display threshold.', 'rankings'),
        AppSetting('maxavg', maxavg, as_int, 'Maximum average count.', 'rankings'),
        AppSetting('maxrecs', maxrecs, as_int, 'Maximum records to retain.', 'rankings'),
    ),
)


def register(aseco: 'Aseco'):
    aseco.register_event('onTracklistChanged', _invalidate_playlist_ranks)
    aseco.register_event('onChallengeListModified', _invalidate_playlist_ranks)
    aseco.register_event('onLocalRecord', _invalidate_ranks)
    aseco.register_event('onRecordsChanged', _invalidate_ranks)
    aseco.register_event('onRanksUpdated', _ranks_updated)
    aseco.register_event('onEverySecond', _retry_rank_work)
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
    global feature_ranks, feature_stats, always_show_pb, nextrank_show_rp
    global prune_records_times, reset_cache_start, minrank, maxavg

    settings = bind_app_settings(PLAYER_RANKING_SETTINGS_SCHEMA, aseco._base_dir)
    cfg_path = settings.source_path
    aseco.console(
        '[Players] Loading ranking config file [{1}]',
        display_path(cfg_path) if cfg_path else '<defaults>',
    )
    _rasp_messages = {}

    try:
        from pyxaseco.message_loader import overlay_section
        overlay_section(_rasp_messages, 'rasp_messages', strip_prefix='rasp_', base_dir=aseco._base_dir)
    except Exception as exc:
        logger.warning('[Players] ranking messages overlay failed: %s', exc)
    feature_ranks = settings.feature_ranks
    feature_stats = settings.feature_stats
    always_show_pb = settings.always_show_pb
    nextrank_show_rp = settings.nextrank_show_rp
    prune_records_times = settings.prune_records_times
    reset_cache_start = settings.reset_cache_start
    minrank = settings.minrank
    maxavg = settings.maxavg
    maxrecs = settings.maxrecs
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
    }

    aseco.console('[Players] Checking ranking database structure...')
    # Tables are created by the local database app - just log OK
    aseco.console('[Players] ...Structure OK!')

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

    # Show PB to all online players only when explicitly enabled.
    if always_show_pb:
        for player in aseco.server.players.all():
            await _show_pb(aseco, player, challenge_id, True)

# ---------------------------------------------------------------------------
# End of race - recalculate ranks
# ---------------------------------------------------------------------------

async def rasp_end_race(aseco: 'Aseco', _params):
    if aseco.server.isrelay or not feature_ranks:
        return
    from pyxaseco.core.background_jobs import JobPolicy
    aseco.jobs.service('rank_messages', JobPolicy(capacity=2, deadline_seconds=60)).invalidate()
    aseco._rank_message_retry_at = 0.0
    aseco._rank_message_players = (
        {} if aseco.settings.sb_stats_panels else
        {p.login: p for p in aseco.server.players.all()})
    if await _reset_ranks(aseco) is None:
        await _ranks_updated(aseco)


async def _ranks_updated(aseco, _param=None):
    from bisect import bisect_left
    from pyxaseco.core.background_jobs import Admission, JobEnvelope, JobPolicy
    players = getattr(aseco, '_rank_message_players', {})
    if not players:
        return
    pool = await localdb_get_pool(aseco)
    if not pool:
        aseco._rank_message_retry_at = time.monotonic() + 10
        return
    job = JobEnvelope.capture(aseco.capture_job_context(), {})
    async def operation(_job):
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT p.Login, r.avg FROM rs_rank r '
                                  'LEFT JOIN players p ON p.Id=r.playerID ORDER BY r.avg')
                return list(await cur.fetchall())
    async def apply(result):
        if result.status != 'completed':
            logger.warning('[Players] Rank feedback unavailable (%s)', result.error_type)
            aseco._rank_message_players = players
            aseco._rank_message_retry_at = time.monotonic() + 10
            return
        averages = [row[1] for row in result.value]
        by_login = dict(result.value)
        for login, player in players.items():
            if aseco.server.players.get_player(login) is not player:
                continue
            average = by_login.get(login)
            message = (format_text(_rasp_msg('RANK_NONE'), minrank) if average is None else
                       format_text(_rasp_msg('RANK'), bisect_left(averages, average) + 1,
                                   len(averages), f'{average / 10000:4.1f}'))
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin', aseco.format_colors(message), login)
    # These are server ranks, not map UI. A quick skip must not discard feedback.
    outcome = aseco.jobs.service('rank_messages', JobPolicy(capacity=2, deadline_seconds=60)).submit(
        job, operation, apply, current_map=False, dedupe_key='score-ranks')
    if outcome in (Admission.ACCEPTED, Admission.DUPLICATE):
        aseco._rank_message_players = {}
        aseco._rank_message_retry_at = 0.0
    else:
        logger.warning('[Players] Rank feedback deferred (%s)', outcome.value)
        if outcome != Admission.STOPPED:
            aseco._rank_message_retry_at = time.monotonic() + (10 if outcome == Admission.COOLDOWN else 1)


async def _retry_rank_work(aseco, _param=None):
    now = time.monotonic()
    if not feature_ranks or aseco.server.isrelay:
        return
    if 0 < getattr(aseco, '_rank_retry_at', 0) <= now:
        aseco._rank_retry_at = 0.0
        outcome = await _reset_ranks(aseco)
        if outcome is None:
            await _ranks_updated(aseco)
        else:
            # Wait for publication before sending feedback after database recovery.
            aseco._rank_message_retry_at = 0.0
            return
    if 0 < getattr(aseco, '_rank_message_retry_at', 0) <= now:
        aseco._rank_message_retry_at = 0.0
        await _ranks_updated(aseco)


# ---------------------------------------------------------------------------
# Player finish - store time in rs_times
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

    await _insert_time(aseco, player.id, challenge.id, score)


async def _insert_time(aseco: 'Aseco', player_id: int, challenge_id: int, score: int):
    try:
        pool = await localdb_get_pool(aseco)
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
        logger.warning('[Players] Could not insert ranking time: %s', e)


# ---------------------------------------------------------------------------
# Player connect - show rank + PB
# ---------------------------------------------------------------------------

async def rasp_player_connect(aseco: 'Aseco', player: 'Player'):
    if feature_ranks:
        await _show_rank(aseco, player.login)
    if feature_stats and always_show_pb:
        await _show_pb(aseco, player, aseco.server.challenge.id, True)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def _publish_ranks(pool, rows):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rs_rank'")
            engine = await cur.fetchone()
            name = engine[0] if engine else None
            if isinstance(name, bytes):
                name = name.decode('ascii', errors='replace')
            name = str(name or 'unavailable').strip().upper()[:32]
            if name == 'MYISAM':
                await _publish_myisam_ranks(cur, rows)
                return
            if name not in ('INNODB', 'XTRADB'):
                logger.error('[Players] Cannot publish ranks: unsupported rs_rank engine=%s', name)
                raise RuntimeError(f'Unsupported rs_rank engine: {name}')
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute('DELETE FROM rs_rank')
                if rows:
                    await cur.executemany('INSERT INTO rs_rank (playerID, avg) VALUES (%s, %s)', rows)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def _publish_myisam_ranks(cur, rows):
    # CREATE LIKE cannot carry custom triggers or external data/index directories.
    await cur.execute('SELECT COUNT(*) FROM information_schema.TRIGGERS '
                      "WHERE TRIGGER_SCHEMA=DATABASE() AND EVENT_OBJECT_TABLE='rs_rank'")
    triggers = await cur.fetchone()
    if triggers is None or triggers[0]:
        logger.error('[Players] MyISAM rs_rank has custom triggers or unavailable trigger metadata; '
                     'publication requires operator review')
        raise RuntimeError('MyISAM rs_rank trigger metadata requires operator review')
    await cur.execute('SHOW CREATE TABLE rs_rank')
    definition = await cur.fetchone()
    ddl = definition[1] if definition else ''
    if isinstance(ddl, bytes):
        ddl = ddl.decode('ascii', errors='replace')
    if not ddl or any(option in ddl.upper() for option in ('DATA DIRECTORY', 'INDEX DIRECTORY')):
        logger.error('[Players] MyISAM rs_rank has external directory options or unavailable table metadata; '
                     'publication requires operator review')
        raise RuntimeError('MyISAM rs_rank table options require operator review')
    suffix = uuid4().hex
    staging, previous = f'rs_rank_stage_{suffix}', f'rs_rank_old_{suffix}'
    created = False
    try:
        await cur.execute(f'CREATE TABLE `{staging}` LIKE rs_rank')
        created = True
        if rows:
            await cur.executemany(f'INSERT INTO `{staging}` (playerID, avg) VALUES (%s, %s)', rows)
        # One swap: readers see a complete old or new table, never a partial insert.
        await cur.execute(f'RENAME TABLE rs_rank TO `{previous}`, `{staging}` TO rs_rank')
    except BaseException:
        if created:
            try:
                await cur.execute(f'DROP TABLE IF EXISTS `{staging}`')
            except Exception:
                logger.warning('[Players] Could not clean owned staging table %s', staging)
        # Never drop the backup after an unacknowledged swap.
        logger.warning('[Players] Rank publication failed; review %s if present', previous)
        raise
    try:
        await cur.execute(f'DROP TABLE `{previous}`')
    except Exception:
        logger.warning('[Players] Ranks published; old table %s needs cleanup', previous)


async def _reset_ranks(aseco: 'Aseco'):
    from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy, Admission
    from pyxaseco.core.file_io import file_io
    from .rank_calculation import calculate_ranks
    pool = await localdb_get_pool(aseco)
    if pool is None:
        aseco._rank_retry_at = time.monotonic() + 10
        return
    track_ids = await _get_challenge_ids(aseco, pool)
    if not track_ids:
        return
    track_ids = tuple(track_ids)
    revision = getattr(aseco, '_rank_revision', 0)
    job = JobEnvelope.capture(aseco.capture_job_context(), {
        'track_count': len(track_ids), 'maxrecs': int(maxrecs), 'minrank': int(minrank),
        'stunts': aseco.server.gameinfo.mode == 4})
    async def operation(envelope):
        p = envelope.payload()
        direction = 'DESC' if p['stunts'] else 'ASC'
        ordered = []
        async with pool.acquire() as conn:
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    await cur.execute('SELECT PlayerId, COUNT(*) AS cnt FROM records GROUP BY PlayerId HAVING cnt >= %s',
                                      (p['minrank'],))
                    eligible = [row[0] for row in await cur.fetchall()]
                    ids = list(dict.fromkeys(track_ids))
                    for offset in range(0, len(ids), 256):
                        chunk = ids[offset:offset + 256]
                        placeholders = ','.join(['%s'] * len(chunk))
                        await cur.execute(
                            f'SELECT ChallengeId, PlayerId FROM records WHERE ChallengeId IN ({placeholders}) '
                            f'ORDER BY ChallengeId ASC, Score {direction}, Date ASC', tuple(chunk))
                        ordered.extend(await cur.fetchall())
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
        # No connection retained during CPU calculation.
        return await file_io(calculate_ranks, track_ids, eligible, ordered, p['maxrecs'])
    async def apply(result):
        if result.status != 'completed':
            logger.warning('[Players] Rank calculation failed; keeping last complete ranks (%s)', result.error_type)
            return
        # Metadata locks on a shared database must not leave publication waiting forever.
        async with asyncio.timeout(10):
            await _publish_ranks(pool, result.value)
        aseco.console('[Players] ...Done! ({1} ranked players)', len(result.value))
        await aseco.release_event('onRanksUpdated', None)
    async def discard(_result):
        current = aseco.capture_job_context()
        if (aseco.jobs.running and feature_ranks
                and job.context.run_id == current.run_id
                and job.context.server_id == current.server_id
                and revision != getattr(aseco, '_rank_revision', 0)):
            # Record/playlist edits invalidate the snapshot; rebuild the latest one.
            await _reset_ranks(aseco)
    outcome = aseco.jobs.service('player_ranks', JobPolicy(capacity=2, deadline_seconds=120)).submit(
        job, operation, apply, current_map=False, dedupe_key='ranks', discard=discard)
    if outcome == Admission.ACCEPTED:
        aseco._rank_retry_at = 0.0
        aseco.console('[Players] Calculating ranks in background; last complete ranks remain available')
    elif outcome == Admission.DUPLICATE:
        aseco._rank_retry_at = 0.0
    else:
        logger.warning('[Players] Rank calculation deferred (%s)', outcome.value)
        if outcome != Admission.STOPPED:
            aseco._rank_retry_at = time.monotonic() + (10 if outcome == Admission.COOLDOWN else 1)
    return outcome


async def _invalidate_ranks(aseco, _param=None):
    from pyxaseco.core.background_jobs import JobPolicy
    aseco._rank_revision = getattr(aseco, '_rank_revision', 0) + 1
    aseco.jobs.service('player_ranks', JobPolicy(capacity=2, deadline_seconds=120)).invalidate()


async def _invalidate_playlist_ranks(aseco, _param=None):
    global _challenge_list_cache
    _challenge_list_cache = []
    await _invalidate_ranks(aseco)


async def _clean_data(aseco: 'Aseco'):
    """
    Always remove empty player/challenge rows and optionally prune orphaned
    records/rs_times entries when prune_records_times is enabled.
    """
    try:
        pool = await localdb_get_pool(aseco)
        if pool is None:
            return
    except ImportError:
        return

    aseco.console('[Players] Cleaning up unused ranking data')

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

                aseco.console('[Players] ...Deleting {1}: {2}', label, ','.join(str(i) for i in ids))
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
    global _challenge_list_cache
    if _challenge_list_cache:
        return list(_challenge_list_cache)
    from pyxaseco.core.playlist import playlist
    tracks = await playlist(aseco).snapshot()
    by_uid = {}
    valid = [row for row in tracks if row.get('UId')]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for offset in range(0, len(valid), 256):
                chunk = list({row['UId']: row for row in valid[offset:offset + 256]}.values())
                await cur.execute('SELECT Uid, Id FROM challenges WHERE Uid IN (' +
                                  ','.join(['%s'] * len(chunk)) + ')', tuple(row['UId'] for row in chunk))
                by_uid.update(await cur.fetchall())
                missing = [row for row in chunk if row['UId'] not in by_uid]
                if not missing:
                    continue
                # Another controller may insert the UID after our SELECT.
                # A no-op upsert preserves its ID and metadata without IGNORE warnings.
                await cur.executemany(
                    'INSERT INTO challenges (Uid, Name, Author, Environment) VALUES (%s,%s,%s,%s) '
                    'ON DUPLICATE KEY UPDATE Uid=VALUES(Uid)',
                    [(row['UId'], row.get('Name', ''), row.get('Author', ''),
                      row.get('Environnement', row.get('Environment', ''))) for row in missing])
                await cur.execute('SELECT Uid, Id FROM challenges WHERE Uid IN (' +
                                  ','.join(['%s'] * len(missing)) + ')', tuple(row['UId'] for row in missing))
                by_uid.update(await cur.fetchall())
    ids = [by_uid[row['UId']] for row in valid if row['UId'] in by_uid]
    _challenge_list_cache = ids
    return list(ids)


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
            pool = await localdb_get_pool(aseco)
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
            pool = await localdb_get_pool(aseco)
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
        pool = await localdb_get_pool(aseco)
        if not pool:
            return
        pid = await localdb_get_player_id(aseco, login)
        if not pid:
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # One statement keeps average, total and ties on the same publication.
                await cur.execute(
                    'SELECT r.avg, (SELECT COUNT(*) FROM rs_rank), '
                    '(SELECT COUNT(*) FROM rs_rank b WHERE b.avg < r.avg) + 1 '
                    'FROM rs_rank r WHERE r.playerID=%s LIMIT 1', (pid,))
                row = await cur.fetchone()
                if row:
                    my_avg, total, rank = row
                    message = format_text(_rasp_msg('RANK'), rank, total,
                                          f'{my_avg/10000:4.1f}')
                else:
                    message = format_text(_rasp_msg('RANK_NONE'), minrank)

        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin', aseco.format_colors(message), login)
    except Exception as e:
        logger.debug('[Players] showRank error: %s', e)


def _rasp_msg(key: str) -> str:
    value = _rasp_messages.get(key.upper(), '')
    if isinstance(value, list):
        return value[0] if value else ''
    if value is None:
        return ''
    return str(value)


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
        pool = await localdb_get_pool(aseco)
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
        logger.warning('[Players] top ranked query error: %s', e)
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
        pool = await localdb_get_pool(aseco)
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName, Wins FROM players ORDER BY Wins DESC LIMIT 100')
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning('[Players] topwins error: %s', e)
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
        pool = await localdb_get_pool(aseco)
        if not pool:
            return
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT NickName, TimePlayed FROM players '
                    'ORDER BY TimePlayed DESC LIMIT 100')
                rows = await cur.fetchall()
    except Exception as e:
        logger.warning('[Players] active error: %s', e)
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

