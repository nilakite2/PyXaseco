"""UTC population samples and persistent sampled peaks, partitioned by server login."""

from datetime import datetime, timedelta
import math

import aiomysql


TABLES = {
    'serverstats_samples': '''CREATE TABLE `serverstats_samples` (
        `ServerLogin` varchar(100) NOT NULL,
        `SampleTime` datetime NOT NULL,
        `Players` int unsigned NOT NULL,
        `Spectators` int unsigned NOT NULL,
        PRIMARY KEY (`ServerLogin`, `SampleTime`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
    'serverstats_peaks': '''CREATE TABLE `serverstats_peaks` (
        `ServerLogin` varchar(100) NOT NULL,
        `PeakPlayers` int unsigned NOT NULL,
        `PlayersPeakAt` datetime NOT NULL,
        `PeakSpectators` int unsigned NOT NULL,
        `SpectatorsPeakAt` datetime NOT NULL,
        `PeakTotal` int unsigned NOT NULL,
        `TotalPeakAt` datetime NOT NULL,
        PRIMARY KEY (`ServerLogin`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
}


async def ensure_schema(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for name, ddl in TABLES.items():
                await cur.execute('''SELECT 1 FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s LIMIT 1''', (name,))
                if await cur.fetchone():
                    continue
                try:
                    await cur.execute(ddl)
                except aiomysql.Error as error:
                    if not error.args or error.args[0] != 1050:
                        raise


async def sample(pool, data):
    server, at = data['server'], datetime.fromisoformat(data['at'])
    players, spectators = data['players'], data['spectators']
    since = at - timedelta(hours=data['retention_hours'])
    hour = at - timedelta(hours=1)
    bucket = max(data['interval_seconds'], math.ceil(data['retention_hours'] * 3600 / 720))
    async with pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute('''INSERT INTO serverstats_samples (ServerLogin, SampleTime, Players, Spectators)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE Players=VALUES(Players), Spectators=VALUES(Spectators)''',
                    (server, at, players, spectators))
                await cur.execute('''INSERT INTO serverstats_peaks
                    (ServerLogin, PeakPlayers, PlayersPeakAt, PeakSpectators, SpectatorsPeakAt, PeakTotal, TotalPeakAt)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    PlayersPeakAt=IF(VALUES(PeakPlayers)>PeakPlayers, VALUES(PlayersPeakAt), PlayersPeakAt),
                    SpectatorsPeakAt=IF(VALUES(PeakSpectators)>PeakSpectators, VALUES(SpectatorsPeakAt), SpectatorsPeakAt),
                    TotalPeakAt=IF(VALUES(PeakTotal)>PeakTotal, VALUES(TotalPeakAt), TotalPeakAt),
                    PeakPlayers=GREATEST(PeakPlayers, VALUES(PeakPlayers)),
                    PeakSpectators=GREATEST(PeakSpectators, VALUES(PeakSpectators)),
                    PeakTotal=GREATEST(PeakTotal, VALUES(PeakTotal))''',
                    (server, players, at, spectators, at, players + spectators, at))
                # Bound each cleanup batch; displayed statistics still filter by the cutoff.
                await cur.execute('DELETE FROM serverstats_samples WHERE ServerLogin=%s AND SampleTime<%s LIMIT 10000',
                                  (server, since))
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise

        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('''SELECT COUNT(*) AS Samples, AVG(Players) AS AvgPlayers,
                AVG(Spectators) AS AvgSpectators, AVG(Players+Spectators) AS AvgTotal,
                AVG(CASE WHEN SampleTime>=%s THEN Players END) AS HourPlayers,
                AVG(CASE WHEN SampleTime>=%s THEN Spectators END) AS HourSpectators,
                AVG(CASE WHEN SampleTime>=%s THEN Players+Spectators END) AS HourTotal
                FROM serverstats_samples WHERE ServerLogin=%s AND SampleTime>=%s AND SampleTime<=%s''',
                (hour, hour, hour, server, since, at))
            averages = await cur.fetchone() or {}
            await cur.execute('SELECT * FROM serverstats_peaks WHERE ServerLogin=%s', (server,))
            peaks = await cur.fetchone() or {}
            await cur.execute('''SELECT MIN(SampleTime) AS At, AVG(Players) AS Players,
                AVG(Spectators) AS Spectators FROM serverstats_samples
                WHERE ServerLogin=%s AND SampleTime>=%s AND SampleTime<=%s
                GROUP BY TIMESTAMPDIFF(SECOND, %s, SampleTime) DIV %s ORDER BY MIN(SampleTime)''',
                (server, since, at, since, bucket))
            history = list(await cur.fetchall())
    return {'server': server, 'at': data['at'], 'players': players, 'spectators': spectators,
            'averages': averages, 'peaks': peaks, 'history': history, 'bucket_seconds': bucket,
            'since': since.isoformat(sep=' ')}
