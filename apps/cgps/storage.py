"""GPS rows are keyed by map UID; local numeric IDs stay stable across restarts."""

import aiomysql

from pyxaseco.management.config_store import ManagementError


async def ensure_schema(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('''SELECT 1 FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s LIMIT 1''', ('curated_gps',))
            if await cur.fetchone():
                return
            try:
                await cur.execute('''CREATE TABLE `curated_gps` (
                `Id` int unsigned NOT NULL AUTO_INCREMENT,
                `Uid` varchar(27) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                `Name` varchar(255) NOT NULL DEFAULT '',
                `Link` varchar(2048) DEFAULT NULL,
                PRIMARY KEY (`Id`), UNIQUE KEY `Uid` (`Uid`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
            except aiomysql.Error as error:
                # Another connection may have created it after the existence check.
                if not error.args or error.args[0] != 1050:
                    raise


async def sync_tracks(pool, tracks):
    rows = {}
    for track in tracks:
        uid = str(track.get('UId') or track.get('Uid') or '')
        if uid:
            rows[uid] = (uid, str(track.get('Name') or '')[:255])
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Import all known local maps, including those not in today's playlist.
            await cur.execute('''INSERT INTO curated_gps (Uid, Name)
                SELECT Uid, Name FROM challenges WHERE Uid <> ''
                ON DUPLICATE KEY UPDATE Name=VALUES(Name)''')
            values = list(rows.values())
            for start in range(0, len(values), 256):
                await cur.executemany('''INSERT INTO curated_gps (Uid, Name) VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE Name=VALUES(Name)''', values[start:start + 256])


async def list_tracks(pool):
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT Id, Uid, Name, Link FROM curated_gps ORDER BY Id')
            return await cur.fetchall()


async def current_link(pool, uid):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT Link FROM curated_gps WHERE Uid=%s', (uid,))
            row = await cur.fetchone()
            return row[0] if row else None


async def save_link(pool, action, map_id, link=None, *, track_name=None):
    async with pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if track_name is not None:
                    # Current-track commands always use UID, even if it is all digits.
                    await cur.execute('''INSERT INTO curated_gps (Uid, Name) VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE Name=VALUES(Name)''', (map_id, track_name[:255]))
                column = ('Id' if track_name is None and map_id.isascii() and map_id.isdecimal()
                          else 'Uid')
                await cur.execute(f'SELECT Id, Link FROM curated_gps WHERE {column}=%s FOR UPDATE', (map_id,))
                row = await cur.fetchone()
                if not row:
                    raise ManagementError('Unknown map ID; use /cgps list')
                existing = row['Link']
                if action == 'add' and existing:
                    raise ManagementError('This map already has a GPS; use /cgps mod')
                if action in ('mod', 'rem') and not existing:
                    raise ManagementError('No GPS stored for that map; use /cgps add')
                if (action == 'rem' and link is not None
                        and link.split('://', 1)[-1] != existing.split('://', 1)[-1]):
                    raise ManagementError('That link does not match the stored GPS; nothing changed')
                await cur.execute('UPDATE curated_gps SET Link=%s WHERE Id=%s',
                                  (None if action == 'rem' else link, row['Id']))
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise
    return row['Id']
