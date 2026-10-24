"""Persistent per-track assignments; UID identity and stable local /fmods IDs."""

import aiomysql

from pyxaseco.management.config_store import ManagementError


async def ensure_schema(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('''SELECT 1 FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s LIMIT 1''', ('forcemods_tracks',))
            if await cur.fetchone():
                return
            try:
                await cur.execute('''CREATE TABLE `forcemods_tracks` (
                `Id` int unsigned NOT NULL AUTO_INCREMENT,
                `Uid` varchar(27) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                `Name` varchar(255) NOT NULL DEFAULT '',
                `Environment` varchar(16) NOT NULL DEFAULT '',
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
            rows[uid] = (uid, str(track.get('Name') or '')[:255],
                         str(track.get('Environnement') or '')[:16])
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            values = list(rows.values())
            for start in range(0, len(values), 256):
                await cur.executemany('''INSERT INTO forcemods_tracks (Uid, Name, Environment) VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE Name=VALUES(Name),
                    Environment=IF(VALUES(Environment)='', Environment, VALUES(Environment))''', values[start:start + 256])


async def list_tracks(pool, uids):
    uids = list(dict.fromkeys(uids))
    rows = []
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            for start in range(0, len(uids), 256):
                batch = uids[start:start + 256]
                await cur.execute('SELECT Id, Uid, Name, Environment, Link FROM forcemods_tracks '
                                  'WHERE Uid IN (' + ','.join(['%s'] * len(batch)) + ')', tuple(batch))
                rows.extend(await cur.fetchall())
    return sorted(rows, key=lambda row: row['Id'])


async def current_link(pool, uid):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT Link FROM forcemods_tracks WHERE Uid=%s', (uid,))
            row = await cur.fetchone()
            return row[0] if row else None


async def save_link(pool, action, map_id, link=None, *, track=None):
    async with pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if track is not None:
                    await cur.execute('''INSERT INTO forcemods_tracks (Uid, Name, Environment) VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE Name=VALUES(Name),
                        Environment=IF(VALUES(Environment)='', Environment, VALUES(Environment))''',
                        (map_id, str(track.get('Name') or '')[:255], str(track.get('Environnement') or '')[:16]))
                column = 'Id' if track is None and map_id.isascii() and map_id.isdecimal() else 'Uid'
                await cur.execute(f'SELECT Id, Uid, Link FROM forcemods_tracks WHERE {column}=%s FOR UPDATE', (map_id,))
                row = await cur.fetchone()
                if not row:
                    raise ManagementError('Unknown mod map ID; use /fmods list.')
                existing = row['Link']
                if action == 'add' and existing:
                    raise ManagementError('This track already has a mod; use /fmods mod.')
                if action in ('mod', 'rem') and not existing:
                    raise ManagementError('No mod assigned to that track; use /fmods add.')
                if action == 'rem' and link is not None and link != existing:
                    raise ManagementError('That URL does not match the stored mod; nothing changed.')
                await cur.execute('UPDATE forcemods_tracks SET Link=%s WHERE Id=%s',
                                  (None if action == 'rem' else link, row['Id']))
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise
    return row['Id']
