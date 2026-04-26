from __future__ import annotations

import asyncio
import logging
import importlib
from datetime import datetime
import pathlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

_backfill_task: asyncio.Task | None = None


def _plugin_module(name: str):
    for mod_name in (f'pyxaseco_plugins.{name}', f'pyxaseco.plugins.{name}'):
        try:
            return importlib.import_module(mod_name)
        except ImportError:
            continue
    raise ImportError(name)


def _track_uid(track: dict | None) -> str:
    if not track:
        return ''
    return str(track.get('UId', '') or track.get('Uid', '') or '').strip()


def _track_filename(track: dict | None) -> str:
    if not track:
        return ''
    return str(track.get('FileName', '') or '').strip()


def _track_author_time(track: dict | None) -> int:
    if not track:
        return 0
    return int(track.get('AuthorTime', 0) or track.get('AuthorScore', 0) or 0)


def _track_gold_time(track: dict | None) -> int:
    if not track:
        return 0
    return int(track.get('GoldTime', 0) or track.get('GoldScore', 0) or 0)


def _tracks_root(aseco: 'Aseco') -> pathlib.Path:
    return pathlib.Path(
        getattr(
            aseco.settings,
            'tracks_root',
            aseco._base_dir.parent / 'GameData' / 'Tracks'
        )
    ).resolve()


def _track_roots(aseco: 'Aseco') -> list[pathlib.Path]:
    roots: list[pathlib.Path] = []
    configured = _tracks_root(aseco)
    roots.append(configured)

    default_root = (aseco._base_dir.parent / 'GameData' / 'Tracks').resolve()
    if default_root not in roots:
        roots.append(default_root)

    if configured.name.lower() == 'challenges':
        parent = configured.parent.resolve()
        if parent not in roots:
            roots.append(parent)

    return roots


def _resolve_track_path(aseco: 'Aseco', filename: str) -> pathlib.Path | None:
    rel = str(filename or '').replace('/', '\\').lstrip('\\')
    if not rel:
        return None

    variants = [rel]
    if rel.lower().startswith('challenges\\'):
        stripped = rel[len('challenges\\'):]
        if stripped:
            variants.append(stripped)

    for root in _track_roots(aseco):
        for variant in variants:
            try:
                candidate = (root / variant).resolve()
            except Exception:
                continue
            if candidate.exists():
                return candidate

    for root in _track_roots(aseco):
        for variant in variants:
            try:
                return (root / variant).resolve()
            except Exception:
                continue

    return None


def _file_modified_at(aseco: 'Aseco', filename: str) -> str | None:
    path = _resolve_track_path(aseco, filename)
    if not path or not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def _normalise_tmx_upload_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')

    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%d',
    ):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


async def ensure_schema(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `challenges_extra` (
                  `Id` mediumint(9) NOT NULL AUTO_INCREMENT,
                  `Challenge_Id` mediumint(9) NOT NULL,
                  `AuthorTime` int(11) NOT NULL DEFAULT 0,
                  `GoldTime` int(11) NOT NULL DEFAULT 0,
                  `AddedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  `TMX_Id` int(11) DEFAULT NULL,
                  `TMX_UploadDate` datetime DEFAULT NULL,
                  PRIMARY KEY (`Id`),
                  UNIQUE KEY `Challenge_Id` (`Challenge_Id`),
                  KEY `TMX_Id` (`TMX_Id`),
                  KEY `AddedAt` (`AddedAt`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            await cur.execute("SHOW COLUMNS FROM `challenges_extra`")
            rows = await cur.fetchall()
            existing = {str(row[0] or row.get('Field') or '') for row in (rows or [])}

            wanted_columns = {
                'Challenge_Id': "ALTER TABLE `challenges_extra` ADD COLUMN `Challenge_Id` mediumint(9) NOT NULL AFTER `Id`",
                'AuthorTime': "ALTER TABLE `challenges_extra` ADD COLUMN `AuthorTime` int(11) NOT NULL DEFAULT 0 AFTER `Challenge_Id`",
                'GoldTime': "ALTER TABLE `challenges_extra` ADD COLUMN `GoldTime` int(11) NOT NULL DEFAULT 0 AFTER `AuthorTime`",
                'AddedAt': "ALTER TABLE `challenges_extra` ADD COLUMN `AddedAt` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER `GoldTime`",
                'TMX_Id': "ALTER TABLE `challenges_extra` ADD COLUMN `TMX_Id` int(11) DEFAULT NULL AFTER `AddedAt`",
                'TMX_UploadDate': "ALTER TABLE `challenges_extra` ADD COLUMN `TMX_UploadDate` datetime DEFAULT NULL AFTER `TMX_Id`",
            }
            for column, ddl in wanted_columns.items():
                if column not in existing:
                    await cur.execute(ddl)

            await cur.execute("SHOW INDEX FROM `challenges_extra`")
            index_rows = await cur.fetchall()
            index_names = {str(row[2] or row.get('Key_name') or '') for row in (index_rows or [])}

            wanted_indexes = {
                'Challenge_Id': "ALTER TABLE `challenges_extra` ADD UNIQUE KEY `Challenge_Id` (`Challenge_Id`)",
                'TMX_Id': "ALTER TABLE `challenges_extra` ADD KEY `TMX_Id` (`TMX_Id`)",
                'AddedAt': "ALTER TABLE `challenges_extra` ADD KEY `AddedAt` (`AddedAt`)",
            }
            for index_name, ddl in wanted_indexes.items():
                if index_name not in index_names:
                    await cur.execute(ddl)


async def get_metadata_map(pool) -> dict[str, dict]:
    if not pool:
        return {}

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    c.Uid,
                    c.Id,
                    x.AuthorTime,
                    x.GoldTime,
                    x.AddedAt,
                    x.TMX_Id,
                    x.TMX_UploadDate
                FROM challenges c
                LEFT JOIN challenges_extra x ON (x.Challenge_Id = c.Id)
                WHERE c.Uid IS NOT NULL AND c.Uid <> ''
                """
            )
            rows = await cur.fetchall()

    out: dict[str, dict] = {}
    for row in rows or []:
        uid = str(row[0] or '').strip()
        if not uid:
            continue
        out[uid] = {
            'challenge_id': int(row[1] or 0),
            'author_time': int(row[2] or 0) if row[2] is not None else 0,
            'gold_time': int(row[3] or 0) if row[3] is not None else 0,
            'added_at': _normalise_tmx_upload_date(row[4]),
            'tmx_id': int(row[5] or 0) if row[5] is not None else 0,
            'tmx_upload_date': _normalise_tmx_upload_date(row[6]),
        }
    return out


async def schedule_backfill(aseco: 'Aseco', pool):
    global _backfill_task

    if _backfill_task and not _backfill_task.done():
        return

    _backfill_task = asyncio.create_task(_backfill_missing_rows(aseco, pool))


async def _paged_challenge_list(aseco: 'Aseco', batch_size: int = 500) -> list[dict]:
    tracks: list[dict] = []
    offset = 0
    while True:
        chunk = await aseco.client.query('GetChallengeList', batch_size, offset) or []
        if not chunk:
            break
        tracks.extend(chunk)
        if len(chunk) < batch_size:
            break
        offset += len(chunk)
    return tracks


async def _fetch_challenge_info_times(aseco: 'Aseco', filename: str) -> tuple[int, int]:
    if not filename:
        return 0, 0
    try:
        info = await aseco.client.query('GetChallengeInfo', filename)
    except Exception:
        return 0, 0

    author_time = int(info.get('AuthorTime', 0) or info.get('AuthorScore', 0) or 0)
    gold_time = int(info.get('GoldTime', 0) or info.get('GoldScore', 0) or 0)
    return author_time, gold_time


async def _ensure_challenge_row(cur, *, uid: str, name: str = '', author: str = '', environment: str = '') -> int:
    uid = (uid or '').strip()
    if not uid:
        return 0

    await cur.execute('SELECT Id FROM challenges WHERE Uid=%s LIMIT 1', (uid,))
    row = await cur.fetchone()
    if row:
        return int(row[0] or row.get('Id') or 0)

    await cur.execute(
        'INSERT INTO challenges (Uid, Name, Author, Environment) VALUES (%s, %s, %s, %s)',
        (uid, name, author, environment)
    )
    return int(cur.lastrowid or 0)


async def upsert_for_track(
    aseco: 'Aseco',
    pool,
    track: dict | None = None,
    *,
    uid: str = '',
    name: str = '',
    author: str = '',
    environment: str = '',
    filename: str = '',
    challenge_id: int = 0,
    author_time: int | None = None,
    gold_time: int | None = None,
    added_at: str | None = None,
    repair_added_at: bool = False,
    tmx_id: int | None = None,
    tmx_upload_date=None,
):
    uid = (uid or _track_uid(track)).strip()
    if not uid:
        return

    name = name or (track.get('Name', '') if track else '')
    author = author or (track.get('Author', '') if track else '')
    environment = environment or (
        (track.get('Environnement', '') if track else '') or
        (track.get('Environment', '') if track else '')
    )
    filename = filename or _track_filename(track)

    if author_time is None:
        author_time = _track_author_time(track)
    if gold_time is None:
        gold_time = _track_gold_time(track)
    if (author_time or 0) <= 0 and filename:
        fetched_author, fetched_gold = await _fetch_challenge_info_times(aseco, filename)
        author_time = author_time or fetched_author
        gold_time = gold_time or fetched_gold

    added_at = added_at or _file_modified_at(aseco, filename) or datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not tmx_id or not tmx_upload_date:
        tmx_meta = await _fetch_tmx_meta_for_uid(aseco, uid)
        if tmx_meta:
            tmx_id = tmx_id or int(tmx_meta.get('id', 0) or 0) or None
            tmx_upload_date = tmx_upload_date or tmx_meta.get('uploaded')

    upload_date = _normalise_tmx_upload_date(tmx_upload_date)

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if challenge_id <= 0:
                challenge_id = await _ensure_challenge_row(
                    cur,
                    uid=uid,
                    name=name,
                    author=author,
                    environment=environment,
                )

            if challenge_id <= 0:
                return

            await cur.execute(
                """
                INSERT INTO challenges_extra
                    (Challenge_Id, AuthorTime, GoldTime, AddedAt, TMX_Id, TMX_UploadDate)
                VALUES
                    (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    AuthorTime = VALUES(AuthorTime),
                    GoldTime = VALUES(GoldTime),
                    AddedAt = IF(%s, VALUES(AddedAt), AddedAt),
                    TMX_Id = COALESCE(VALUES(TMX_Id), TMX_Id),
                    TMX_UploadDate = COALESCE(VALUES(TMX_UploadDate), TMX_UploadDate)
                """,
                (
                    challenge_id,
                    int(author_time or 0),
                    int(gold_time or 0),
                    added_at,
                    int(tmx_id) if tmx_id else None,
                    upload_date,
                    1 if repair_added_at else 0,
                ),
            )


async def _fetch_tmx_meta_for_uid(aseco: 'Aseco', uid: str) -> dict:
    uid = (uid or '').strip()
    if not uid:
        return {}
    try:
        mod = _plugin_module('plugin_tmxinfo')
        getter = getattr(mod, 'get_tmx_trackmeta_for_uid', None)
        if callable(getter):
            return await getter(aseco, uid) or {}
    except Exception:
        return {}
    return {}


async def remove_for_uid(pool, uid: str):
    uid = (uid or '').strip()
    if not uid:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT Id FROM challenges WHERE Uid=%s LIMIT 1', (uid,))
            row = await cur.fetchone()
            if not row:
                return
            challenge_id = int(row[0] or row.get('Id') or 0)
            if challenge_id > 0:
                await cur.execute('DELETE FROM challenges_extra WHERE Challenge_Id=%s', (challenge_id,))


async def _backfill_missing_rows(aseco: 'Aseco', pool):
    try:
        await asyncio.sleep(2.0)

        tracks = await _paged_challenge_list(aseco)
        if not tracks:
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT Id, Uid, Name, Author, Environment FROM challenges')
                rows = await cur.fetchall()
                by_uid: dict[str, dict] = {}
                for row in rows or []:
                    challenge_id = int(row[0] or 0)
                    by_uid[str(row[1] or '').strip()] = {
                        'id': challenge_id,
                        'name': str(row[2] or ''),
                        'author': str(row[3] or ''),
                        'environment': str(row[4] or ''),
                    }

                await cur.execute('SELECT Challenge_Id, AddedAt, TMX_Id, TMX_UploadDate FROM challenges_extra')
                extra_rows = await cur.fetchall()
                extra_meta = {
                    int(row[0] or 0): {
                        'added_at': row[1],
                        'tmx_id': int(row[2] or 0) if row[2] is not None else 0,
                        'tmx_upload_date': row[3],
                    }
                    for row in (extra_rows or [])
                }

            inserted = 0
            enriched = 0
            repaired_added_at = 0
            for track in tracks:
                uid = _track_uid(track)
                if not uid:
                    continue

                row = by_uid.get(uid)
                if not row:
                    async with conn.cursor() as cur:
                        challenge_id = await _ensure_challenge_row(
                            cur,
                            uid=uid,
                            name=str(track.get('Name', '') or ''),
                            author=str(track.get('Author', '') or ''),
                            environment=str(track.get('Environnement', '') or track.get('Environment', '') or ''),
                        )
                    row = {
                        'id': challenge_id,
                        'name': str(track.get('Name', '') or ''),
                        'author': str(track.get('Author', '') or ''),
                        'environment': str(track.get('Environnement', '') or track.get('Environment', '') or ''),
                    }
                    by_uid[uid] = row

                row_meta = extra_meta.get(row['id'])
                needs_insert = row_meta is None
                needs_tmx_enrich = bool(
                    row_meta is not None and
                    (not row_meta.get('tmx_id') or not row_meta.get('tmx_upload_date'))
                )
                file_added_at = _file_modified_at(aseco, _track_filename(track))
                existing_added_at = _normalise_tmx_upload_date(row_meta.get('added_at')) if row_meta else None
                needs_added_at_repair = bool(
                    row_meta is not None and
                    file_added_at and
                    existing_added_at != file_added_at
                )
                if not needs_insert and not needs_tmx_enrich and not needs_added_at_repair:
                    continue

                tmx_meta = await _fetch_tmx_meta_for_uid(aseco, uid) if (needs_insert or needs_tmx_enrich) else {}

                await upsert_for_track(
                    aseco,
                    pool,
                    track=track,
                    challenge_id=row['id'],
                    uid=uid,
                    name=row['name'],
                    author=row['author'],
                    environment=row['environment'],
                    added_at=file_added_at,
                    repair_added_at=needs_added_at_repair,
                    tmx_id=int(tmx_meta.get('id', 0) or 0) or None,
                    tmx_upload_date=tmx_meta.get('uploaded'),
                )
                extra_meta[row['id']] = {
                    'added_at': file_added_at or existing_added_at,
                    'tmx_id': int(tmx_meta.get('id', 0) or 0),
                    'tmx_upload_date': tmx_meta.get('uploaded'),
                }
                if needs_insert:
                    inserted += 1
                if needs_tmx_enrich:
                    enriched += 1
                if needs_added_at_repair:
                    repaired_added_at += 1

        if inserted or enriched or repaired_added_at:
            logger.info(
                '[ChallengesCache] Backfilled %s challenges_extra row(s), enriched %s TMX metadata row(s), repaired %s AddedAt row(s)',
                inserted,
                enriched,
                repaired_added_at,
            )
    except Exception as exc:
        logger.warning('[ChallengesCache] Backfill failed: %s', exc)
