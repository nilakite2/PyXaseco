"""
Data models for PyXaseco.

Direct port of includes/types.inc.php — Record, RecordList, Player, PlayerList,
Challenge, Server, Gameinfo, ChatCommand, RPCCall.

TMF-only: TMN-specific branches have been removed.
"""

from __future__ import annotations
import time
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Record / RecordList
# ---------------------------------------------------------------------------

class Record:
    """A single time/score record on a challenge."""

    def __init__(self):
        self.player: Optional['Player'] = None
        self.challenge: Optional['Challenge'] = None
        self.score: int = 0          # milliseconds
        self.date: str = ''          # ISO date string
        self.checks: list = []       # checkpoint times
        self.new: bool = False       # True if just set this round
        self.pos: int = 0            # rank (1-based)

    def __repr__(self):
        login = self.player.login if self.player else '?'
        return f'<Record {login} {self.score}ms rank={self.pos}>'


class RecordList:
    """Ordered list of Records, capped at max entries."""

    def __init__(self, limit: int):
        self._records: list[Record] = []
        self.max: int = limit

    def set_limit(self, limit: int):
        self.max = limit

    def get_record(self, rank: int) -> Optional[Record]:
        """Get record by 0-based index."""
        if 0 <= rank < len(self._records):
            return self._records[rank]
        return None

    def set_record(self, rank: int, record: Record) -> bool:
        if 0 <= rank < len(self._records):
            self._records[rank] = record
            return True
        return False

    def add_record(self, record: Record, rank: int = -1) -> bool:
        """Insert a record at position rank (0-based). -1 = append."""
        if rank == -1:
            rank = len(self._records)
        if rank >= self.max:
            return False
        if record.score <= 0:
            return False
        if len(self._records) >= self.max:
            self._records.pop()
        self._records.insert(rank, record)
        return True

    def del_record(self, rank: int) -> bool:
        if 0 <= rank < len(self._records):
            del self._records[rank]
            return True
        return False

    def move_record(self, from_pos: int, to_pos: int):
        record = self._records.pop(from_pos)
        self._records.insert(to_pos, record)

    def count(self) -> int:
        return len(self._records)

    def clear(self):
        self._records.clear()

    def __iter__(self):
        return iter(self._records)

    def __len__(self):
        return len(self._records)

    def __getitem__(self, index):
        return self._records[index]


# ---------------------------------------------------------------------------
# Player / PlayerList
# ---------------------------------------------------------------------------

class Player:
    """
    A connected player.  Constructed from a GetDetailedPlayerInfo RPC response.
    TMF-only fields only.
    """

    def __init__(self, rpc_infos: Optional[dict] = None):
        self.id: int = 0            # DB id (set after DB lookup)
        self.pid: int = 0           # server PlayerId
        self.login: str = ''
        self.nickname: str = ''
        self.teamname: str = ''
        self.ip: str = ''
        self.ipport: str = ''       # IP:port from server
        self.client: str = ''       # ClientVersion
        self.zone: str = ''         # e.g. "Europe|France|Île-de-France"
        self.nation: str = ''       # e.g. "France"
        self.prevstatus: bool = False
        self.isspectator: bool = False
        self.retired: bool = False
        self.isofficial: bool = False
        self.rights: bool = False   # True = United (online rights == 3)
        self.language: str = ''
        self.avatar: str = ''
        self.teamid: int = 0
        self.unlocked: bool = False
        self.ladderrank: int = 0
        self.ladderscore: float = 0.0

        # Set on connect
        self.created: int = 0       # epoch when player connected

        # DB / stats
        self.wins: int = 0
        self.newwins: int = 0
        self.timeplayed: int = 0    # seconds in DB

        # Per-session state
        self.tracklist: list = []
        self.playerlist: list = []
        self.msgs: list = []
        self.pmbuf: list = []
        self.mutelist: list = []
        self.mutebuf: list = []
        self.style: dict = {}
        self.panels: dict = {}
        self.speclogin: str = ''
        self.dedirank: int = 0

        if rpc_infos:
            self._from_rpc(rpc_infos)

    def _from_rpc(self, info: dict):
        self.pid = info.get('PlayerId', 0)
        self.login = info.get('Login', '')
        self.nickname = info.get('NickName', '')
        self.ipport = info.get('IPAddress', '')
        self.ip = re.sub(r':\d+$', '', self.ipport)
        self.prevstatus = False
        self.isspectator = info.get('IsSpectator', False)
        self.retired = False
        self.isofficial = info.get('IsInOfficialMode', False)
        ladder = info.get('LadderStats', {})
        self.teamname = ladder.get('TeamName', '')

        # TMF path: "World|France|..." — strip leading "World|"
        raw_nation = (info.get('Nation', '') or '').strip()
        raw_zone = (info.get('Zone', '') or info.get('Location', '') or '').strip()
        path = (info.get('Path', '') or '').strip()

        def _clean_zone(text: str) -> str:
            return text[6:] if text.startswith('World|') else text

        def _zone_score(text: str) -> int:
            parts = [part.strip() for part in text.split('|') if part.strip()]
            if not parts:
                return -100
            score = 0
            if len(parts) > 1:
                score += 10
            if len(parts[0]) > 3:
                score += 5
            if ' ' in parts[0]:
                score += 3
            if parts[0].isalpha() and len(parts[0]) <= 3:
                score -= 8
            return score

        zone_candidates = [cand for cand in (_clean_zone(raw_zone), _clean_zone(path)) if cand]
        path_zone = max(zone_candidates, key=_zone_score) if zone_candidates else ''
        path_parts = path_zone.split('|') if path_zone else []

        if (
            len(path_parts) >= 2
            and len(path_parts[0]) <= 3
            and path_parts[0].isalpha()
            and ' ' in path_parts[1]
        ):
            path_parts = path_parts[1:]
            path_zone = '|'.join(path_parts)

        path_has_better_nation = bool(
            path_parts and (
                len(path_parts[0]) > 3 or
                ' ' in path_parts[0] or
                len(path_parts) > 1
            )
        )

        if path_has_better_nation:
            self.zone = path_zone
            self.nation = path_parts[0] if path_parts else ''
        elif raw_nation:
            self.zone = raw_nation
            self.nation = raw_nation
        else:
            self.zone = path_zone
            self.nation = path_parts[0] if path_parts else ''

        player_rankings = ladder.get('PlayerRankings', [{}])
        if player_rankings:
            self.ladderrank = player_rankings[0].get('Ranking', 0)
            self.ladderscore = round(player_rankings[0].get('Score', 0.0), 2)

        self.client = info.get('ClientVersion', '')
        self.rights = (info.get('OnlineRights', 0) == 3)  # 3 = United
        self.language = info.get('Language', '')
        avatar_info = info.get('Avatar', {})
        self.avatar = avatar_info.get('FileName', '') if isinstance(avatar_info, dict) else ''
        self.teamid = info.get('TeamId', 0)
        self.created = int(time.time())

    def get_wins(self) -> int:
        return self.wins + self.newwins

    def get_time_online(self) -> int:
        """Seconds since connect."""
        return int(time.time()) - self.created if self.created > 0 else 0

    def get_time_played(self) -> int:
        """Total seconds played (DB + current session)."""
        return self.timeplayed + self.get_time_online()

    def __repr__(self):
        return f'<Player {self.login!r} nick={self.nickname!r}>'


class PlayerList:
    """Dict-backed player list keyed by login."""

    def __init__(self):
        self._players: dict[str, Player] = {}

    def add_player(self, player: Player) -> bool:
        if isinstance(player, Player) and player.login:
            self._players[player.login] = player
            return True
        return False

    def remove_player(self, login: str) -> Optional[Player]:
        return self._players.pop(login, None)

    def get_player(self, login: str) -> Optional[Player]:
        return self._players.get(login)

    def __iter__(self):
        return iter(self._players.values())

    def __len__(self):
        return len(self._players)

    def __contains__(self, login: str):
        return login in self._players

    def all(self) -> list[Player]:
        return list(self._players.values())


# ---------------------------------------------------------------------------
# Challenge
# ---------------------------------------------------------------------------

class Challenge:
    """Current map/challenge info. From GetChallengeInfo RPC response."""

    def __init__(self, rpc_infos: Optional[dict] = None):
        self.id: int = 0            # DB id
        self.name: str = 'undefined'
        self.uid: str = ''
        self.filename: str = ''
        self.author: str = ''
        self.environment: str = ''
        self.mood: str = ''
        self.bronzetime: int = 0
        self.silvertime: int = 0
        self.goldtime: int = 0
        self.authortime: int = 0
        self.copperprice: int = 0
        self.laprace: bool = False
        self.forcedlaps: int = 0
        self.nblaps: int = 0
        self.nbchecks: int = 0
        self.score: int = 0         # winning score this round
        self.starttime: int = 0     # epoch when race started
        self.gbx = None             # GbxDataFetcher object (set by plugin)
        self.tmx = None             # TMX info (set by plugin)

        if rpc_infos:
            self._from_rpc(rpc_infos)

    def _from_rpc(self, info: dict):
        self.name = _strip_newlines(info.get('Name', ''))
        self.uid = info.get('UId', '')
        self.filename = info.get('FileName', '')
        self.author = info.get('Author', '')
        self.environment = info.get('Environnement', '')  # note: Nadeo typo preserved
        self.mood = info.get('Mood', '')
        self.bronzetime = info.get('BronzeTime', 0)
        self.silvertime = info.get('SilverTime', 0)
        self.goldtime = info.get('GoldTime', 0)
        self.authortime = info.get('AuthorTime', 0)
        self.copperprice = info.get('CopperPrice', 0)
        self.laprace = bool(info.get('LapRace', False))
        self.forcedlaps = 0
        self.nblaps = info.get('NbLaps', 0)
        self.nbchecks = info.get('NbCheckpoints', 0)

    def __repr__(self):
        return f'<Challenge {self.uid!r} {self.name!r}>'


# ---------------------------------------------------------------------------
# Gameinfo
# ---------------------------------------------------------------------------

class Gameinfo:
    """Current game mode and settings. From GetCurrentGameInfo RPC response."""

    RNDS = 0
    TA   = 1
    TEAM = 2
    LAPS = 3
    STNT = 4
    CUP  = 5
    SCOR = 7   # Score screen between rounds — server-reported only, not a playable mode

    _MODE_NAMES = {0: 'Rounds', 1: 'TimeAttack', 2: 'Team',
                   3: 'Laps', 4: 'Stunts', 5: 'Cup', 7: 'Score'}

    def __init__(self, rpc_infos: Optional[dict] = None):
        self.mode: int = -1
        self.numchall: int = 0
        self.rndslimit: int = 0
        self.timelimit: int = 0
        self.teamlimit: int = 0
        self.teamusenewrules: bool = False
        self.lapslimit: int = 0
        self.lapsnblaps: int = 0
        self.cuplimit: int = 0
        self.forcedlaps: int = 0
        self.raw: dict = {}

        if rpc_infos:
            self._from_rpc(rpc_infos)

    def _from_rpc(self, info: dict):
        self.raw = dict(info or {})
        self.mode = info.get('GameMode', -1)
        self.numchall = info.get('NbChallenge', 0)
        if info.get('RoundsUseNewRules'):
            self.rndslimit = info.get('RoundsPointsLimitNewRules', 0)
        else:
            self.rndslimit = info.get('RoundsPointsLimit', 0)
        self.timelimit = info.get('TimeAttackLimit', 0)
        self.teamusenewrules = bool(info.get('TeamUseNewRules'))
        if self.teamusenewrules:
            self.teamlimit = info.get('TeamPointsLimitNewRules', 0)
        else:
            self.teamlimit = info.get('TeamPointsLimit', 0)
        self.lapslimit = info.get('LapsTimeLimit', 0)
        self.lapsnblaps = info.get('LapsNbLaps', info.get('NbLaps', 0))
        self.cuplimit = info.get('CupPointsLimit', 0)
        self.forcedlaps = info.get('RoundsForcedLaps', 0)

    def get_mode(self) -> str:
        return self._MODE_NAMES.get(self.mode, 'Undefined')


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class Server:
    """Stores information about the dedicated server we are connected to."""

    RACE  = 'race'
    SCORE = 'score'

    def __init__(self, ip: str, port: int, login: str, password: str):
        self.ip = ip
        self.port = port
        self.login = login
        self.password = password
        self.starttime = int(time.time())

        # Populated after connect
        self.id: int = 0
        self.name: str = ''
        self.game: str = ''          # 'TmForever' etc. from GetVersion
        self.serverlogin: str = ''
        self.nickname: str = ''
        self.zone: str = ''
        self.rights: bool = False
        self.version: str = ''
        self.build: str = ''
        self.packmask: str = ''
        self.laddermin: float = 0.0
        self.laddermax: float = 0.0
        self.maxplay: int = 0
        self.maxspec: int = 0
        self.timeout: Optional[float] = None

        # State
        self.challenge: Challenge = Challenge()
        self.records: RecordList = RecordList(50)  # overridden by config
        self.players: PlayerList = PlayerList()
        self.mutelist: list = []
        self.gamestate: str = self.RACE
        self.gameinfo: Optional[Gameinfo] = None
        self.gamedir: str = ''
        self.trackdir: str = ''
        self.votetime: int = 0
        self.voterate: int = 0
        self.uptime: int = 0

        self.isrelay: bool = False
        self.relaymaster: str = ''
        self.relayslist: list = []

    def get_game(self) -> str:
        """Return short game identifier."""
        return {
            'TmForever': 'TMF',
            'TmNationsESWC': 'TMN',
            'TmSunrise': 'TMS',
            'TmOriginal': 'TMO',
        }.get(self.game, 'Unknown')

    def __repr__(self):
        return f'<Server {self.serverlogin!r} game={self.game!r}>'


# ---------------------------------------------------------------------------
# ChatCommand
# ---------------------------------------------------------------------------

class ChatCommand:
    """Registered chat command metadata."""

    def __init__(self, name: str, help_text: str, is_admin: bool = False):
        self.name = name
        self.help = help_text
        self.isadmin = is_admin

    def __repr__(self):
        return f'<ChatCommand /{self.name} admin={self.isadmin}>'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_newlines(text: str) -> str:
    """Remove embedded newlines from map names."""
    return text.replace('\n', '').replace('\r', '').replace('\\n', '')
