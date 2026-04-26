"""
plugin_localdatabase.py — Port of plugins/plugin.localdatabase.php

Manages the MySQL local database:
  - players, challenges, records, players_extra tables
  - Loads records on new challenge
  - Saves records on player finish
  - Updates player stats on connect/disconnect
  - Fires onLocalRecord event

Exposes helper functions used by other plugins:
  ldb_get_style, ldb_set_style, ldb_get_panels, ldb_set_panel,
  ldb_get_cps, ldb_set_cps, ldb_get_donations, ldb_update_donations
"""

from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING, Optional

import aiomysql

from pyxaseco.core.config import parse_xml_file
from pyxaseco.core.challenges_cache import ensure_schema as ensure_challenges_extra_schema
from pyxaseco.core.challenges_cache import schedule_backfill as schedule_challenges_extra_backfill
from pyxaseco.helpers import strip_colors, format_text
from pyxaseco.models import Record, Player, Challenge

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

# Module-level DB pool (shared across all callers)
_pool: Optional[aiomysql.Pool] = None
_settings: dict = {}
_display: bool = True
_limit: int = 50
_messages: dict = {}

# Country code map (TMF nation → 3-letter ISO)
_COUNTRY_MAP = {
    'Afghanistan': 'AFG', 'Albania': 'ALB', 'Algeria': 'ALG', 'Andorra': 'AND',
    'Angola': 'ANG', 'Argentina': 'ARG', 'Armenia': 'ARM', 'Australia': 'AUS',
    'Austria': 'AUT', 'Azerbaijan': 'AZE', 'Bahrain': 'BRN', 'Bangladesh': 'BAN',
    'Belarus': 'BLR', 'Belgium': 'BEL', 'Bolivia': 'BOL', 'Bosnia and Herzegovina': 'BIH',
    'Brazil': 'BRA', 'Bulgaria': 'BUL', 'Cameroon': 'CMR', 'Canada': 'CAN',
    'Chile': 'CHI', 'China': 'CHN', 'Colombia': 'COL', 'Costa Rica': 'CRC',
    'Croatia': 'CRO', 'Cuba': 'CUB', 'Cyprus': 'CYP', 'Czech Republic': 'CZE',
    'Denmark': 'DEN', 'Dominican Republic': 'DOM', 'Ecuador': 'ECU', 'Egypt': 'EGY',
    'El Salvador': 'ESA', 'Estonia': 'EST', 'Ethiopia': 'ETH', 'Finland': 'FIN',
    'France': 'FRA', 'Georgia': 'GEO', 'Germany': 'GER', 'Ghana': 'GHA',
    'Greece': 'GRE', 'Guatemala': 'GUA', 'Honduras': 'HON', 'Hungary': 'HUN',
    'Iceland': 'ISL', 'India': 'IND', 'Indonesia': 'INA', 'Iran': 'IRI',
    'Iraq': 'IRQ', 'Ireland': 'IRL', 'Israel': 'ISR', 'Italy': 'ITA',
    'Jamaica': 'JAM', 'Japan': 'JPN', 'Jordan': 'JOR', 'Kazakhstan': 'KAZ',
    'Kenya': 'KEN', 'Kuwait': 'KUW', 'Latvia': 'LAT', 'Lebanon': 'LIB',
    'Libya': 'LBA', 'Liechtenstein': 'LIE', 'Lithuania': 'LTU', 'Luxembourg': 'LUX',
    'Macedonia': 'MKD', 'Malaysia': 'MAS', 'Malta': 'MLT', 'Mexico': 'MEX',
    'Moldova': 'MDA', 'Monaco': 'MON', 'Montenegro': 'MNE', 'Morocco': 'MAR',
    'Netherlands': 'NED', 'New Zealand': 'NZL', 'Nigeria': 'NGR', 'North Korea': 'PRK',
    'Norway': 'NOR', 'Oman': 'OMA', 'Pakistan': 'PAK', 'Panama': 'PAN',
    'Paraguay': 'PAR', 'Peru': 'PER', 'Philippines': 'PHI', 'Poland': 'POL',
    'Portugal': 'POR', 'Puerto Rico': 'PUR', 'Qatar': 'QAT', 'Romania': 'ROU',
    'Russia': 'RUS', 'Saudi Arabia': 'KSA', 'Senegal': 'SEN', 'Serbia': 'SCG',
    'Slovakia': 'SVK', 'Slovenia': 'SLO', 'South Africa': 'RSA', 'South Korea': 'KOR',
    'Spain': 'ESP', 'Sweden': 'SWE', 'Switzerland': 'SUI', 'Syria': 'SYR',
    'Taiwan': 'TPE', 'Thailand': 'THA', 'Trinidad and Tobago': 'TRI', 'Tunisia': 'TUN',
    'Turkey': 'TUR', 'Ukraine': 'UKR', 'United Arab Emirates': 'UAE',
    'United Kingdom': 'GBR', 'United States': 'USA', 'Uruguay': 'URU',
    'Venezuela': 'VEN', 'Vietnam': 'VIE',
}


def map_country(nation: str) -> str:
    """Map a TMF nation name to a 3-letter code."""
    return _COUNTRY_MAP.get(nation, nation[:3].upper() if nation else '')


async def get_pool() -> aiomysql.Pool:
    return _pool


def register(aseco: 'Aseco'):
    aseco.register_event('onStartup',          ldb_load_settings)
    aseco.register_event('onStartup',          ldb_connect)
    aseco.register_event('onEverySecond',      ldb_reconnect)
    aseco.register_event('onSync',             ldb_sync)
    aseco.register_event('onNewChallenge',     ldb_new_challenge)
    aseco.register_event('onPlayerConnect',    ldb_player_connect)
    aseco.register_event('onPlayerDisconnect', ldb_player_disconnect)
    aseco.register_event('onPlayerFinish',     ldb_player_finish)
    aseco.register_event('onPlayerWins',       ldb_player_wins)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def ldb_load_settings(aseco: 'Aseco', _param):
    global _settings, _display, _limit, _messages

    config_path = aseco._base_dir / 'localdatabase.xml'
    aseco.console('[LocalDB] Load config file [{1}]', str(config_path))

    data = parse_xml_file(config_path)
    if not data:
        raise RuntimeError(f'[LocalDB] Could not read/parse {config_path}')

    s = data.get('SETTINGS', {})

    def g(key, default=''):
        items = s.get(key.upper(), [default])
        return items[0] if items else default

    _settings = {
        'host':     g('MYSQL_SERVER', '127.0.0.1'),
        'user':     g('MYSQL_LOGIN', 'root'),
        'password': g('MYSQL_PASSWORD', ''),
        'db':       g('MYSQL_DATABASE', 'aseco'),
    }
    _display = g('DISPLAY', 'true').upper() == 'TRUE'
    _limit   = int(g('LIMIT', '50'))
    msgs_block = s.get('MESSAGES', [{}])
    _messages = msgs_block[0] if msgs_block else {}


async def ldb_connect(aseco: 'Aseco', _param):
    global _pool

    aseco.console("[LocalDB] Connecting to MySQL '{1}' db='{2}'",
                  _settings['host'], _settings['db'])
    try:
        _pool = await aiomysql.create_pool(
            host=_settings['host'],
            user=_settings['user'],
            password=_settings['password'],
            db=_settings['db'],
            charset='utf8mb4',
            autocommit=True,
            minsize=1,
            maxsize=5,
        )
    except Exception as e:
        raise RuntimeError(f'[LocalDB] Could not connect to MySQL: {e}')

    aseco.console('[LocalDB] Checking database structure...')
    await _ensure_tables(aseco)
    await ensure_challenges_extra_schema(_pool)
    aseco.console('[LocalDB] ...Structure OK!')
    await schedule_challenges_extra_backfill(aseco, _pool)


async def _open_pool() -> aiomysql.Pool:
    return await aiomysql.create_pool(
        host=_settings['host'],
        user=_settings['user'],
        password=_settings['password'],
        db=_settings['db'],
        charset='utf8mb4',
        autocommit=True,
        minsize=1,
        maxsize=5,
    )


async def ldb_reconnect(aseco: 'Aseco', _param=None):
    """Run the idle reconnect check when no players are online."""
    global _pool

    if aseco.server.players.all():
        return
    if _pool is None:
        _pool = await _open_pool()
        aseco.console('[LocalDB] Reconnected to MySQL Server')
        return

    try:
        async with _pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('SELECT 1')
                await cur.fetchone()
    except Exception:
        try:
            _pool.close()
            await _pool.wait_closed()
        except Exception:
            pass
        _pool = await _open_pool()
        aseco.console('[LocalDB] Reconnected to MySQL Server')


async def _ensure_tables(aseco: 'Aseco'):
    """Create tables and apply the required schema migrations."""
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Suppress "Table already exists" notes from MySQL/MariaDB
            await cur.execute("SET sql_notes = 0")

            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `challenges` (
                  `Id` mediumint(9) NOT NULL AUTO_INCREMENT,
                  `Uid` varchar(27) NOT NULL DEFAULT '',
                  `Name` varchar(100) NOT NULL DEFAULT '',
                  `Author` varchar(30) NOT NULL DEFAULT '',
                  `Environment` varchar(10) NOT NULL DEFAULT '',
                  PRIMARY KEY (`Id`), UNIQUE KEY `Uid` (`Uid`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `players` (
                  `Id` mediumint(9) NOT NULL AUTO_INCREMENT,
                  `Login` varchar(50) NOT NULL DEFAULT '',
                  `Game` varchar(3) NOT NULL DEFAULT '',
                  `NickName` varchar(100) NOT NULL DEFAULT '',
                  `Nation` varchar(3) NOT NULL DEFAULT '',
                  `UpdatedAt` datetime NOT NULL DEFAULT '2000-01-01 00:00:00',
                  `Wins` mediumint(9) NOT NULL DEFAULT 0,
                  `TimePlayed` int(10) unsigned NOT NULL DEFAULT 0,
                  `TeamName` char(60) NOT NULL DEFAULT '',
                  PRIMARY KEY (`Id`), UNIQUE KEY `Login` (`Login`), KEY `Game` (`Game`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `records` (
                  `Id` int(11) NOT NULL AUTO_INCREMENT,
                  `ChallengeId` mediumint(9) NOT NULL DEFAULT 0,
                  `PlayerId` mediumint(9) NOT NULL DEFAULT 0,
                  `Score` int(11) NOT NULL DEFAULT 0,
                  `Date` datetime NOT NULL DEFAULT '2000-01-01 00:00:00',
                  `Checkpoints` text NOT NULL,
                  PRIMARY KEY (`Id`),
                  UNIQUE KEY `PlayerId` (`PlayerId`,`ChallengeId`),
                  KEY `ChallengeId` (`ChallengeId`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `players_extra` (
                  `playerID` mediumint(9) NOT NULL DEFAULT 0,
                  `cps` smallint(3) NOT NULL DEFAULT -1,
                  `dedicps` smallint(3) NOT NULL DEFAULT -1,
                  `donations` mediumint(9) NOT NULL DEFAULT 0,
                  `style` varchar(20) NOT NULL DEFAULT '',
                  `panels` varchar(255) NOT NULL DEFAULT '',
                  PRIMARY KEY (`playerID`), KEY `donations` (`donations`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `rs_karma` (
                  `Id` int(11) NOT NULL AUTO_INCREMENT,
                  `ChallengeId` mediumint(9) NOT NULL DEFAULT 0,
                  `PlayerId` mediumint(9) NOT NULL DEFAULT 0,
                  `Score` tinyint(4) NOT NULL DEFAULT 0,
                  PRIMARY KEY (`Id`),
                  UNIQUE KEY `PlayerId` (`PlayerId`,`ChallengeId`),
                  KEY `ChallengeId` (`ChallengeId`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `rs_rank` (
                  `playerID` mediumint(9) NOT NULL DEFAULT 0,
                  `avg` float NOT NULL DEFAULT 0,
                  KEY `playerID` (`playerID`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS `rs_times` (
                  `ID` int(11) NOT NULL AUTO_INCREMENT,
                  `challengeID` mediumint(9) NOT NULL DEFAULT 0,
                  `playerID` mediumint(9) NOT NULL DEFAULT 0,
                  `score` int(11) NOT NULL DEFAULT 0,
                  `date` int(10) unsigned NOT NULL DEFAULT 0,
                  `checkpoints` text NOT NULL,
                  PRIMARY KEY (`ID`),
                  KEY `playerID` (`playerID`,`challengeID`),
                  KEY `challengeID` (`challengeID`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Re-enable notes
            await cur.execute("SET sql_notes = 1")

            # Clean up empty entries
            await cur.execute("DELETE FROM challenges WHERE uid=''")
            await cur.execute("DELETE FROM players WHERE login=''")


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

async def ldb_sync(aseco: 'Aseco', _param):
    """Reset player iterator after sync (players already loaded via onPlayerConnect)."""
    pass


# ---------------------------------------------------------------------------
# Player connect / disconnect
# ---------------------------------------------------------------------------

async def ldb_player_connect(aseco: 'Aseco', player: 'Player'):
    if not player.login or _pool is None:
        return

    nation = map_country(player.nation)

    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT Id, Wins, TimePlayed, TeamName FROM players WHERE Login=%s',
                (player.login,)
            )
            row = await cur.fetchone()

            if row:
                player.id = row['Id']
                if not player.teamname and row['TeamName']:
                    player.teamname = row['TeamName']
                if player.wins < row['Wins']:
                    player.wins = row['Wins']
                if player.timeplayed < row['TimePlayed']:
                    player.timeplayed = row['TimePlayed']

                await cur.execute(
                    'UPDATE players SET NickName=%s, Nation=%s, TeamName=%s, UpdatedAt=NOW() '
                    'WHERE Login=%s',
                    (player.nickname, nation, player.teamname, player.login)
                )
            else:
                await cur.execute(
                    'INSERT INTO players (Login, Game, NickName, Nation, TeamName, UpdatedAt) '
                    'VALUES (%s, %s, %s, %s, %s, NOW())',
                    (player.login, 'TMF', player.nickname, nation, player.teamname)
                )
                player.id = cur.lastrowid

            # Ensure players_extra row exists
            await cur.execute(
                'SELECT playerID FROM players_extra WHERE playerID=%s', (player.id,)
            )
            if not await cur.fetchone():
                default_panels = '/'.join([
                    aseco.settings.admin_panel,
                    aseco.settings.donate_panel,
                    aseco.settings.records_panel,
                    aseco.settings.vote_panel,
                ])
                cps    = 0 if aseco.settings.auto_enable_cps else -1
                dedicps = 0 if aseco.settings.auto_enable_dedicps else -1
                await cur.execute(
                    'INSERT INTO players_extra (playerID, cps, dedicps, donations, style, panels) '
                    'VALUES (%s, %s, %s, 0, %s, %s)',
                    (player.id, cps, dedicps,
                     aseco.settings.window_style, default_panels)
                )


async def ldb_player_disconnect(aseco: 'Aseco', player: 'Player'):
    if not player.login or _pool is None:
        return
    online_secs = player.get_time_online()
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE players SET UpdatedAt=NOW(), TimePlayed=TimePlayed+%s WHERE Login=%s',
                (online_secs, player.login)
            )


# ---------------------------------------------------------------------------
# Challenge change
# ---------------------------------------------------------------------------

async def ldb_new_challenge(aseco: 'Aseco', challenge: 'Challenge'):
    if _pool is None:
        return

    aseco.server.records.clear()

    if aseco.server.isrelay:
        challenge.id = 0
        return

    is_stnt = (aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)
    order = 'DESC' if is_stnt else 'ASC'
    maxrecs = aseco.server.records.max

    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                f'''SELECT c.Id AS ChallengeId, r.Score, p.NickName, p.Login,
                           r.Date, r.Checkpoints
                    FROM challenges c
                    LEFT JOIN records r ON (r.ChallengeId=c.Id)
                    LEFT JOIN players p ON (r.PlayerId=p.Id)
                    WHERE c.Uid=%s
                    GROUP BY r.Id
                    ORDER BY r.Score {order}, r.Date ASC
                    LIMIT %s''',
                (challenge.uid, maxrecs)
            )
            rows = await cur.fetchall()

            if rows and rows[0]['ChallengeId'] is not None:
                challenge.id = rows[0]['ChallengeId']
                for row in rows:
                    if row['Score'] is None:
                        continue
                    rec = Record()
                    rec.score = row['Score']
                    rec.checks = row['Checkpoints'].split(',') if row['Checkpoints'] else []
                    rec.new = False
                    p = Player()
                    p.nickname = row['NickName'] or ''
                    p.login    = row['Login'] or ''
                    rec.player = p
                    rec.challenge = challenge
                    aseco.server.records.add_record(rec)
            else:
                # Challenge not in DB yet -> insert it
                try:
                    await cur.execute(
                        'INSERT INTO challenges (Uid, Name, Author, Environment) '
                        'VALUES (%s, %s, %s, %s)',
                        (challenge.uid, challenge.name,
                         challenge.author, challenge.environment)
                    )
                    challenge.id = cur.lastrowid
                except Exception as e:
                    logger.warning('[LocalDB] Could not insert challenge: %s', e)

    aseco.server.records  # already updated in-place


# ---------------------------------------------------------------------------
# Player finish — record handling
# ---------------------------------------------------------------------------

async def ldb_player_finish(aseco: 'Aseco', params: list):
    """Called on onPlayerFinish: params = [uid, login, score]"""
    if _pool is None or len(params) < 3:
        return
    _uid, login, score = params[0], params[1], params[2]
    if score == 0:
        return

    player = aseco.server.players.get_player(login)
    if not player:
        return

    challenge = aseco.server.challenge
    is_stnt = (aseco.server.gameinfo and aseco.server.gameinfo.mode == 4)
    records  = aseco.server.records
    maxrecs  = records.max
    nick     = strip_colors(player.nickname)

    from pyxaseco.helpers import format_time

    # Find where this score fits in the record list
    for i in range(maxrecs):
        cur_rec = records.get_record(i)
    
        if cur_rec is None:
            better = True
        else:
            better = (score > cur_rec.score) if is_stnt else (score < cur_rec.score)
    
        if better:
            # Does this player already have a record?
            cur_rank = -1
            cur_score = 0
            for rank in range(records.count()):
                r = records.get_record(rank)
                if r and r.player and r.player.login == login:
                    worse = (score < r.score) if is_stnt else (score > r.score)
                    if worse:
                        return  # new time is worse, ignore
                    cur_rank = rank
                    cur_score = r.score
                    break

            finish_time = str(score) if is_stnt else format_time(score)

            # Build the new record object
            new_rec = Record()
            new_rec.score     = score
            new_rec.player    = player
            new_rec.challenge = challenge
            new_rec.new       = True

            # Try to attach checkpoint data from plugin_checkpoints now,
            # so both in-memory records and DB rows get real CP times.
            try:
                from pyxaseco.plugins.plugin_checkpoints import checkpoints
                cp = checkpoints.get(login)
                if cp and getattr(cp, 'curr_cps', None):
                    new_rec.checks = [int(x) for x in cp.curr_cps]
                else:
                    new_rec.checks = []
            except Exception:
                new_rec.checks = []

            if cur_rank != -1:
                diff = (score - cur_score) if is_stnt else (cur_score - score)
                sec  = diff // 1000
                hun  = (diff % 1000) // 10

                if diff > 0:
                    records.set_record(cur_rank, new_rec)

                if cur_rank > i:
                    records.move_record(cur_rank, i)
                    msg_key = 'RECORD_NEW_RANK'
                    message = _get_msg(msg_key, nick, i+1,
                                       'Score' if is_stnt else 'Time',
                                       finish_time, cur_rank+1,
                                       f'+{diff}' if is_stnt else f'-{sec}.{hun:02d}')
                elif diff == 0:
                    msg_key = 'RECORD_EQUAL'
                    message = _get_msg(msg_key, nick, cur_rank + 1,
                                       'Score' if is_stnt else 'Time', finish_time)
                    new_rec.new = False
                else:
                    msg_key = 'RECORD_NEW'
                    message = _get_msg(msg_key, nick, i+1,
                                       'Score' if is_stnt else 'Time',
                                       finish_time, cur_rank+1,
                                       f'+{diff}' if is_stnt else f'-{sec}.{hun:02d}')
            else:
                records.add_record(new_rec, i)
                message = _get_msg('RECORD_FIRST', nick, i+1,
                                   'Score' if is_stnt else 'Time', finish_time)

            # Broadcast or whisper
            if _display and message:
                msg_colored = aseco.format_colors(message)
                if i < _limit:
                    await aseco.client.query_ignore_result('ChatSendServerMessage', msg_colored)
                else:
                    private = message.replace('{#server}>> ', '{#server}> ')
                    await aseco.client.query_ignore_result(
                        'ChatSendServerMessageToLogin', aseco.format_colors(private), login)

            # Persist to DB and fire event
            if new_rec.new:
                await _insert_record(challenge.id, player.id, score, new_rec.checks)
                aseco.console('[LocalDB] player {1} finished with {2} → rank {3}',
                              login, score, i+1)
                new_rec.pos = i + 1
                await aseco.release_event('onLocalRecord', new_rec)

            aseco.server.records = records
            return


def _get_msg(key: str, *args) -> str:
    """Look up a message from localdatabase.xml messages block and format it."""
    items = _messages.get(key.upper(), [''])
    raw = items[0] if items else ''
    return format_text(raw, *args)


async def _insert_record(challenge_id: int, player_id: int, score: int, checks: list):
    if _pool is None or player_id == 0 or challenge_id == 0:
        return
    cps = ','.join(str(c) for c in checks)
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'INSERT INTO records (ChallengeId, PlayerId, Score, Date, Checkpoints) '
                'VALUES (%s, %s, %s, NOW(), %s) '
                'ON DUPLICATE KEY UPDATE Score=VALUES(Score), Date=VALUES(Date), '
                'Checkpoints=VALUES(Checkpoints)',
                (challenge_id, player_id, score, cps)
            )


# ---------------------------------------------------------------------------
# Player wins
# ---------------------------------------------------------------------------

async def ldb_player_wins(aseco: 'Aseco', player: 'Player'):
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE players SET Wins=%s WHERE Login=%s',
                (player.get_wins(), player.login)
            )


# ---------------------------------------------------------------------------
# Helper API used by other plugins
# ---------------------------------------------------------------------------

async def ldb_get_style(aseco: 'Aseco', login: str) -> str:
    if _pool is None:
        return ''
    pid = await _get_player_id(login)
    if not pid:
        return ''
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT style FROM players_extra WHERE playerID=%s', (pid,))
            row = await cur.fetchone()
            return row[0] if row else ''


async def ldb_set_style(aseco: 'Aseco', login: str, style: str):
    if _pool is None:
        return
    pid = await _get_player_id(login)
    if not pid:
        return
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE players_extra SET style=%s WHERE playerID=%s', (style, pid))


async def ldb_get_panels(aseco: 'Aseco', login: str) -> dict:
    if _pool is None:
        return {}
    pid = await _get_player_id(login)
    if not pid:
        return {}
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT panels FROM players_extra WHERE playerID=%s', (pid,))
            row = await cur.fetchone()
            if row and row[0]:
                parts = row[0].split('/')
                return {
                    'admin':   parts[0] if len(parts) > 0 else '',
                    'donate':  parts[1] if len(parts) > 1 else '',
                    'records': parts[2] if len(parts) > 2 else '',
                    'vote':    parts[3] if len(parts) > 3 else '',
                }
    return {}


async def ldb_set_panel(aseco: 'Aseco', login: str, panel_type: str, value: str):
    panels = await ldb_get_panels(aseco, login)
    panels[panel_type] = value
    pid = await _get_player_id(login)
    if not pid or _pool is None:
        return
    combined = '/'.join([panels.get('admin',''), panels.get('donate',''),
                         panels.get('records',''), panels.get('vote','')])
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE players_extra SET panels=%s WHERE playerID=%s', (combined, pid))


async def ldb_get_cps(aseco: 'Aseco', login: str) -> dict:
    if _pool is None:
        return {'cps': -1, 'dedicps': -1}
    pid = await _get_player_id(login)
    if not pid:
        return {'cps': -1, 'dedicps': -1}
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT cps, dedicps FROM players_extra WHERE playerID=%s', (pid,))
            row = await cur.fetchone()
            return row if row else {'cps': -1, 'dedicps': -1}


async def ldb_set_cps(aseco: 'Aseco', login: str, cps: int, dedicps: int):
    if _pool is None:
        return
    pid = await _get_player_id(login)
    if not pid:
        return
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE players_extra SET cps=%s, dedicps=%s WHERE playerID=%s',
                (cps, dedicps, pid))


async def ldb_get_donations(aseco: 'Aseco', login: str) -> int:
    if _pool is None:
        return 0
    pid = await _get_player_id(login)
    if not pid:
        return 0
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT donations FROM players_extra WHERE playerID=%s', (pid,))
            row = await cur.fetchone()
            return row[0] if row else 0


async def ldb_update_donations(aseco: 'Aseco', login: str, amount: int):
    if _pool is None:
        return
    pid = await _get_player_id(login)
    if not pid:
        return
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE players_extra SET donations=donations+%s WHERE playerID=%s',
                (amount, pid))


async def ldb_remove_record(aseco: 'Aseco', challenge_id: int, player_id: int, recno: int):
    """Remove a record from DB and the in-memory list."""
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'DELETE FROM records WHERE ChallengeId=%s AND PlayerId=%s',
                (challenge_id, player_id)
            )
    aseco.server.records.del_record(recno)


async def _get_player_id(login: str) -> Optional[int]:
    """Look up a player's DB ID by login. Returns 0 if not found."""
    if _pool is None:
        return 0
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT Id FROM players WHERE Login=%s', (login,))
            row = await cur.fetchone()
            return row[0] if row else 0


# Public helper used by other modules
async def get_player_id(login: str) -> int:
    return await _get_player_id(login) or 0
