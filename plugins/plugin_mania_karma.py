from __future__ import annotations

"""
plugin_mania_karma.py — PyXaseco port of plugins/plugin.mania_karma.php
"""

import asyncio
import base64
import gzip
import logging
import math
import pathlib
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyxaseco.helpers import strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

VERSION = "2.0.1"
MANIALINK_BASE = 911

ML_REMINDER = 91101
ML_WINDOWS = 91102
ML_SKELETON = 91103
ML_MARKER = 91104
ML_CUPS = 91105
ML_CONNECTION = 91106
ML_LOADING = 91107

ACT_CLOSE = 91100
ACT_OPEN_HELP = 91101
ACT_OPEN_DETAIL = 91102
ACT_OPEN_WHO = 91103
ACT_VOTE_P1 = 91110
ACT_VOTE_P2 = 91111
ACT_VOTE_P3 = 91112
ACT_VOTE_UNDECIDED = 91113
ACT_VOTE_N1 = 91114
ACT_VOTE_N2 = 91115
ACT_VOTE_N3 = 91116
ACT_VOTE_LOCKED = 91117
ACT_IGNORE = 91118
ACT_REFRESH = 91119
ACT_PAGE_PREV = 91120
ACT_PAGE_NEXT = 91121

VOTE_KEYS = {
    3: "fantastic",
    2: "beautiful",
    1: "good",
    -1: "bad",
    -2: "poor",
    -3: "waste",
}

VOTE_SCORES = {
    "fantastic": 100,
    "beautiful": 80,
    "good": 60,
    "bad": 40,
    "poor": 20,
    "waste": 0,
}

GM_TAG = {0: "rounds", 1: "time_attack", 2: "team", 3: "laps", 4: "stunts", 5: "cup", 7: "score"}

TMX_HOST_ALIASES = {
    "TMNF": "tmnf.exchange",
    "TMU": "tmuf.exchange",
    "TMN": "nations.tm-exchange.com",
    "TMO": "original.tm-exchange.com",
    "TMS": "sunrise.tm-exchange.com",
}

TMX_PREFIX_HOSTS = {
    "tmnforever": "tmnf.exchange",
    "united": "tmuf.exchange",
    "nations": "nations.tm-exchange.com",
    "original": "original.tm-exchange.com",
    "sunrise": "sunrise.tm-exchange.com",
}

NUMBER_FORMATS = {
    "english": {"decimal_sep": ".", "thousands_sep": ","},
    "german": {"decimal_sep": ",", "thousands_sep": "."},
    "french": {"decimal_sep": ",", "thousands_sep": " "},
}

ISO3166_ALPHA3: dict[str, tuple[str, str]] = {
    "ABW": ("Aruba", "NORTHAMERICA"), "AFG": ("Afghanistan", "ASIA"), "AGO": ("Angola", "AFRICA"),
    "AIA": ("Anguilla", "NORTHAMERICA"), "ALA": ("Åland Islands", "EUROPE"), "ALB": ("Albania", "EUROPE"),
    "AND": ("Andorra", "EUROPE"), "ANT": ("Netherlands Antilles", "NORTHAMERICA"), "ARE": ("United Arab Emirates", "ASIA"),
    "ARG": ("Argentina", "SOUTHAMERICA"), "ARM": ("Armenia", "ASIA"), "ASM": ("American Samoa", "OCEANIA"),
    "ATA": ("Antarctica", "WORLDWIDE"), "ATF": ("French Southern Territories", "WORLDWIDE"),
    "ATG": ("Antigua and Barbuda", "NORTHAMERICA"), "AUS": ("Australia", "OCEANIA"), "AUT": ("Austria", "EUROPE"),
    "AZE": ("Azerbaijan", "ASIA"), "BDI": ("Burundi", "AFRICA"), "BEL": ("Belgium", "EUROPE"),
    "BEN": ("Benin", "AFRICA"), "BFA": ("Burkina Faso", "AFRICA"), "BGD": ("Bangladesh", "ASIA"),
    "BGR": ("Bulgaria", "EUROPE"), "BHR": ("Bahrain", "ASIA"), "BHS": ("Bahamas", "NORTHAMERICA"),
    "BIH": ("Bosnia and Herzegovina", "EUROPE"), "BLR": ("Belarus", "EUROPE"), "BLZ": ("Belize", "NORTHAMERICA"),
    "BMU": ("Bermuda", "NORTHAMERICA"), "BOL": ("Bolivia", "SOUTHAMERICA"), "BRA": ("Brazil", "SOUTHAMERICA"),
    "BRB": ("Barbados", "NORTHAMERICA"), "BRN": ("Brunei Darussalam", "ASIA"), "BTN": ("Bhutan", "ASIA"),
    "BWA": ("Botswana", "AFRICA"), "CAF": ("Central African Republic", "AFRICA"), "CAN": ("Canada", "NORTHAMERICA"),
    "CHE": ("Switzerland", "EUROPE"), "CHL": ("Chile", "SOUTHAMERICA"), "CHN": ("China", "ASIA"),
    "CMR": ("Cameroon", "AFRICA"), "COD": ("Democratic Republic of Congo", "AFRICA"), "COG": ("Republic of Congo", "AFRICA"),
    "COL": ("Colombia", "SOUTHAMERICA"), "CRI": ("Costa Rica", "NORTHAMERICA"), "CUB": ("Cuba", "NORTHAMERICA"),
    "CYP": ("Cyprus", "ASIA"), "CZE": ("Czech Republic", "EUROPE"), "DEU": ("Germany", "EUROPE"),
    "DNK": ("Denmark", "EUROPE"), "DOM": ("Dominican Republic", "NORTHAMERICA"), "DZA": ("Algeria", "AFRICA"),
    "ECU": ("Ecuador", "SOUTHAMERICA"), "EGY": ("Egypt", "AFRICA"), "ESP": ("Spain", "EUROPE"),
    "EST": ("Estonia", "EUROPE"), "ETH": ("Ethiopia", "AFRICA"), "FIN": ("Finland", "EUROPE"),
    "FJI": ("Fiji", "OCEANIA"), "FRA": ("France", "EUROPE"), "GBR": ("United Kingdom", "EUROPE"),
    "GEO": ("Georgia", "ASIA"), "GHA": ("Ghana", "AFRICA"), "GRC": ("Greece", "EUROPE"),
    "GTM": ("Guatemala", "NORTHAMERICA"), "HKG": ("Hong Kong", "ASIA"), "HRV": ("Croatia", "EUROPE"),
    "HTI": ("Haiti", "NORTHAMERICA"), "HUN": ("Hungary", "EUROPE"), "IDN": ("Indonesia", "ASIA"),
    "IND": ("India", "ASIA"), "IRL": ("Ireland", "EUROPE"), "IRN": ("Iran", "ASIA"),
    "IRQ": ("Iraq", "ASIA"), "ISL": ("Iceland", "EUROPE"), "ISR": ("Israel", "ASIA"),
    "ITA": ("Italy", "EUROPE"), "JAM": ("Jamaica", "NORTHAMERICA"), "JOR": ("Jordan", "ASIA"),
    "JPN": ("Japan", "ASIA"), "KAZ": ("Kazakhstan", "ASIA"), "KEN": ("Kenya", "AFRICA"),
    "KGZ": ("Kyrgyzstan", "ASIA"), "KHM": ("Cambodia", "ASIA"), "KOR": ("South Korea", "ASIA"),
    "KWT": ("Kuwait", "ASIA"), "LAO": ("Lao People's Democratic Republic", "ASIA"), "LBN": ("Lebanon", "ASIA"),
    "LBR": ("Liberia", "AFRICA"), "LBY": ("Libyan Arab Jamahiriya", "AFRICA"), "LKA": ("Sri Lanka", "ASIA"),
    "LSO": ("Lesotho", "AFRICA"), "LTU": ("Lithuania", "EUROPE"), "LUX": ("Luxembourg", "EUROPE"),
    "LVA": ("Latvia", "EUROPE"), "MAR": ("Morocco", "AFRICA"), "MCO": ("Monaco", "EUROPE"),
    "MDA": ("Moldova", "EUROPE"), "MDG": ("Madagascar", "AFRICA"), "MEX": ("Mexico", "NORTHAMERICA"),
    "MKD": ("Macedonia", "EUROPE"), "MLI": ("Mali", "AFRICA"), "MLT": ("Malta", "EUROPE"),
    "MMR": ("Myanmar", "ASIA"), "MNE": ("Montenegro", "EUROPE"), "MNG": ("Mongolia", "ASIA"),
    "MOZ": ("Mozambique", "AFRICA"), "MRT": ("Mauritania", "AFRICA"), "MUS": ("Mauritius", "AFRICA"),
    "MWI": ("Malawi", "AFRICA"), "MYS": ("Malaysia", "ASIA"), "NAM": ("Namibia", "AFRICA"),
    "NER": ("Niger", "AFRICA"), "NGA": ("Nigeria", "AFRICA"), "NIC": ("Nicaragua", "NORTHAMERICA"),
    "NLD": ("Netherlands", "EUROPE"), "NOR": ("Norway", "EUROPE"), "NPL": ("Nepal", "ASIA"),
    "NZL": ("New Zealand", "OCEANIA"), "OMN": ("Oman", "ASIA"), "PAK": ("Pakistan", "ASIA"),
    "PAN": ("Panama", "NORTHAMERICA"), "PER": ("Peru", "SOUTHAMERICA"), "PHL": ("Philippines", "ASIA"),
    "PNG": ("Papua New Guinea", "OCEANIA"), "POL": ("Poland", "EUROPE"), "PRT": ("Portugal", "EUROPE"),
    "PRY": ("Paraguay", "SOUTHAMERICA"), "QAT": ("Qatar", "ASIA"), "ROU": ("Romania", "EUROPE"),
    "RUS": ("Russian Federation", "EUROPE"), "SAU": ("Saudi Arabia", "ASIA"), "SDN": ("Sudan", "AFRICA"),
    "SEN": ("Senegal", "AFRICA"), "SGP": ("Singapore", "ASIA"), "SVK": ("Slovakia", "EUROPE"),
    "SVN": ("Slovenia", "EUROPE"), "SWE": ("Sweden", "EUROPE"), "THA": ("Thailand", "ASIA"),
    "TUN": ("Tunisia", "AFRICA"), "TUR": ("Turkey", "ASIA"), "TWN": ("Taiwan", "ASIA"),
    "TZA": ("Tanzania", "AFRICA"), "UGA": ("Uganda", "AFRICA"), "UKR": ("Ukraine", "EUROPE"),
    "URY": ("Uruguay", "SOUTHAMERICA"), "USA": ("United States of America", "NORTHAMERICA"),
    "UZB": ("Uzbekistan", "ASIA"), "VEN": ("Venezuela", "SOUTHAMERICA"), "VNM": ("Viet Nam", "ASIA"),
    "YEM": ("Yemen", "ASIA"), "ZAF": ("South Africa", "AFRICA"), "ZMB": ("Zambia", "AFRICA"), "ZWE": ("Zimbabwe", "AFRICA"),
}


@dataclass
class WidgetGamemodeCfg:
    enabled: bool = True
    pos_x: float = 49.2
    pos_y: float = 32.86


@dataclass
class ReminderStateCfg:
    pos_x: float = -40.9
    pos_y: float = -31.5


@dataclass
class KarmaConfig:
    api_auth_url: str = "http://worldwide.mania-karma.com/api/tmforever-trackmania-v4.php"
    api_url: str = ""
    website: str = "www.mania-karma.com"
    nation: str = ""

    show_welcome: bool = True
    show_at_start: bool = True
    show_karma: bool = True
    show_votes: bool = True
    show_details: bool = False
    allow_public_vote: bool = True
    show_player_vote_public: bool = True
    messages_in_window: bool = True
    score_mx_window: bool = True
    remind_to_vote: str = "SCORE"
    require_finish: int = 1
    reminder_window_display: str = "SCORE"
    uptime_check: bool = False
    uptodate_info: str = "MASTERADMIN"
    import_done: bool = True
    save_karma_also_local: bool = True
    sync_global_karma_local: bool = True
    karma_calculation_method: str = "DEFAULT"
    number_format: str = "english"
    connect_timeout: int = 30
    wait_timeout: int = 40
    keepalive_min_timeout: int = 300

    bg_pos_default: str = "DFDF"
    bg_pos_focus: str = "FFFF"
    text_pos_color: str = "070F"
    bg_neg_default: str = "FDDF"
    bg_neg_focus: str = "FFFF"
    text_neg_color: str = "700F"
    bg_vote: str = "F70F"
    bg_disabled: str = "9CFF"

    race_title: str = "$FFFManiaKarma"
    race_icon_style: str = "Icons64x64_1"
    race_icon_substyle: str = "ToolLeague1"
    race_bg_style: str = "Bgs1InRace"
    race_bg_substyle: str = "NavButton"
    race_title_style: str = "BgsPlayerCard"
    race_title_substyle: str = "BgRacePlayerName"

    score_title: str = "$FFFManiaKarma"
    score_icon_style: str = "Icons64x64_1"
    score_icon_substyle: str = "ToolLeague1"
    score_bg_style: str = "BgsPlayerCard"
    score_bg_substyle: str = "BgRacePlayerName"
    score_title_style: str = "BgsPlayerCard"
    score_title_substyle: str = "ProgressBar"

    img_cup_gold: str = "http://maniacdn.net/undef.de/xaseco1/mania-karma/cup_gold.png"
    img_cup_silver: str = "http://maniacdn.net/undef.de/xaseco1/mania-karma/cup_silver.png"
    img_open_left: str = "http://maniacdn.net/undef.de/xaseco1/mania-karma/edge-open-ld-dark.png"
    img_open_right: str = "http://maniacdn.net/undef.de/xaseco1/mania-karma/edge-open-rd-dark.png"
    img_tmx_logo_normal: str = ""
    img_tmx_logo_focus: str = ""
    img_maniakarma_logo: str = ""
    img_progress_indicator: str = ""

    msg_welcome: str = ""
    msg_uptodate_ok: str = ""
    msg_uptodate_new: str = ""
    msg_uptodate_failed: str = ""
    msg_karma_message: str = "{#server}> {#karma}Karma of {#highlite}{1}{#karma} is {#highlite}{2}"
    msg_karma_your_vote: str = " {#karma}(your vote: {#highlite}{1}{#karma} with {#highlite}{2}{#karma})"
    msg_karma_not_voted: str = " {#karma}(you did not vote yet)"
    msg_karma_details: str = (
        "{#server}>{#karma} Total: {1}, +++ {2}% ({3}), ++ {4}% ({5}), + {6}% ({7}), - {8}% ({9}), -- {10}% ({11}), --- {12}% ({13})"
    )
    msg_karma_done: str = "{#server}> {#karma}Vote successful for Track {#highlite}{1}{#karma}!"
    msg_karma_change: str = "{#server}> {#karma}Vote changed for Track {#highlite}{1}{#karma}!"
    msg_karma_voted: str = "{#server}> {#karma}You have already voted for this Track"
    msg_karma_remind: str = "{#server}> {#karma}Please vote for this track with /+++ /++ /+ /- /-- /--- or use the Karma widget."
    msg_require_finish: str = "{#server}> {#error}You need to finish this Track at least {#highlite}$I {1}{#error} time{2} before being able to vote!"
    msg_no_public: str = "{#server}> {#error}Public karma vote is disabled. Use {#highlite}{1}{#error} privately."
    msg_karma_list_help: str = ""
    msg_karma_help: str = "Use /karma, /karma details, /karma help, /+++ /++ /+ /- /-- /---"
    msg_reminder_at_score: str = "Your vote"
    msg_vote_singular: str = "vote"
    msg_vote_plural: str = "votes"
    msg_you_have_voted: str = "{#server}> {#karma}You already voted {#highlite}{1}{#karma} with {#highlite}{2}{#karma}."
    msg_fantastic: str = "fantastic"
    msg_beautiful: str = "beautiful"
    msg_good: str = "good"
    msg_undecided: str = "undecided"
    msg_bad: str = "bad"
    msg_poor: str = "poor"
    msg_waste: str = "waste"
    msg_show_opinion: str = "{#server}> {#highlite}{1}{#server} thinks this Track is {#highlite}{2}{#server}! What do you think?"
    msg_show_undecided: str = "{#server}> {#highlite}{1}{#server} is undecided about this Track. What do you think?"

    gamemodes: dict[int, WidgetGamemodeCfg] = field(default_factory=dict)
    reminder_race: ReminderStateCfg = field(default_factory=lambda: ReminderStateCfg(-40.9, -31.5))
    reminder_score: ReminderStateCfg = field(default_factory=lambda: ReminderStateCfg(-40.9, 32.5))

    current_state: int = 1

    def gm_cfg(self, mode: int) -> WidgetGamemodeCfg:
        return self.gamemodes.get(mode, WidgetGamemodeCfg())


_cfg = KarmaConfig()
_api_authcode = ""
_api_connected = False
_retrytime = 0
_window_state: dict[str, tuple[str, int]] = {}
_current_map: dict[str, Any] = {}


_karma: dict[str, Any] = {}


def _set_empty_karma(reset_locals: bool = False) -> dict[str, Any]:
    data = {
        "data": {"uid": "", "id": False, "name": "", "author": "", "env": "", "tmx": ""},
        "new": {"players": {}},
        "global": {
            "votes": {
                "karma": 0, "total": 0,
                "fantastic": {"count": 0, "percent": 0.0},
                "beautiful": {"count": 0, "percent": 0.0},
                "good": {"count": 0, "percent": 0.0},
                "bad": {"count": 0, "percent": 0.0},
                "poor": {"count": 0, "percent": 0.0},
                "waste": {"count": 0, "percent": 0.0},
            },
            "players": {},
        },
        "local": {
            "votes": {
                "karma": 0, "total": 0,
                "fantastic": {"count": 0, "percent": 0.0},
                "beautiful": {"count": 0, "percent": 0.0},
                "good": {"count": 0, "percent": 0.0},
                "bad": {"count": 0, "percent": 0.0},
                "poor": {"count": 0, "percent": 0.0},
                "waste": {"count": 0, "percent": 0.0},
            },
            "players": {},
        },
    }
    if not reset_locals and _karma:
        data["global"]["players"] = dict(_karma.get("global", {}).get("players", {}))
        data["local"]["players"] = dict(_karma.get("local", {}).get("players", {}))
    return data


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def _x(node: ET.Element | None, path: str, default: str = "") -> str:
    if node is None:
        return default
    el = node.find(path)
    return el.text.strip() if el is not None and el.text is not None else default


def _xb(node: ET.Element | None, path: str, default: bool = False) -> bool:
    return _x(node, path, "true" if default else "false").upper() == "TRUE"


def _xi(node: ET.Element | None, path: str, default: int = 0) -> int:
    try:
        return int(_x(node, path, str(default)))
    except Exception:
        return default


def _xf(node: ET.Element | None, path: str, default: float = 0.0) -> float:
    try:
        return float(_x(node, path, str(default)))
    except Exception:
        return default


def _fmt_message(aseco: Aseco, template: str, *args: Any) -> str:
    msg = template or ""
    for idx, val in enumerate(args, 1):
        msg = msg.replace(f"{{{idx}}}", str(val))
    msg = msg.replace("{br}", "\n")
    return aseco.format_colors(msg)


def _fmt_template(template: str, *args: Any) -> str:
    msg = template or ""
    for idx, val in enumerate(args, 1):
        msg = msg.replace(f"{{{idx}}}", str(val))
    return msg




def _sanitize_ml_text(text: Any) -> str:
    from xml.sax.saxutils import escape as _esc
    try:
        return _esc(str(text or ''), {'"': '&quot;'})
    except Exception:
        return ''
def _number(n: int | float, decimals: int = 0) -> str:
    fmt = NUMBER_FORMATS.get(_cfg.number_format.lower(), NUMBER_FORMATS["english"])
    try:
        value = float(n)
    except Exception:
        value = 0.0

    if decimals > 0:
        s = f"{value:,.{decimals}f}"
        return s.replace(",", "X").replace(".", fmt["decimal_sep"]).replace("X", fmt["thousands_sep"])

    if value.is_integer():
        s = f"{int(value):,}"
        return s.replace(",", fmt["thousands_sep"])

    s = f"{value:,.2f}"
    return s.replace(",", "X").replace(".", fmt["decimal_sep"]).replace("X", fmt["thousands_sep"])


def _players_all(aseco: Aseco) -> list[Any]:
    try:
        return list(aseco.server.players.all())
    except Exception:
        try:
            return list(aseco.server.players.player_list)
        except Exception:
            return []


def _get_player(aseco: Aseco, login: str):
    try:
        return aseco.server.players.get_player(login)
    except Exception:
        try:
            return aseco.server.players.getPlayer(login)
        except Exception:
            for p in _players_all(aseco):
                if getattr(p, "login", None) == login:
                    return p
    return None


def _is_spectator(aseco: Aseco, player: Any) -> bool:
    try:
        return bool(aseco.is_spectator(player))
    except Exception:
        try:
            return bool(aseco.isSpectator(player))
        except Exception:
            return bool(getattr(player, "isspectator", False) or getattr(player, "spectator", False))


def _is_master_admin(aseco: Aseco, player: Any) -> bool:
    try:
        return bool(aseco.is_master_admin(player))
    except Exception:
        try:
            return bool(aseco.isMasterAdmin(player))
        except Exception:
            return False


def _startup_phase(aseco: Aseco) -> bool:
    return bool(getattr(aseco, "startup_phase", False))


def _get_mode(aseco: Aseco) -> int:
    try:
        return int(aseco.server.gameinfo.mode)
    except Exception:
        return 1


def _current_uid() -> str:
    return str(_current_map.get("uid") or "").strip()


def _vote_label(vote: int) -> str:
    return {
        3: _cfg.msg_fantastic,
        2: _cfg.msg_beautiful,
        1: _cfg.msg_good,
        0: _cfg.msg_undecided,
        -1: _cfg.msg_bad,
        -2: _cfg.msg_poor,
        -3: _cfg.msg_waste,
    }.get(vote, _cfg.msg_undecided)


def _track_page_url(aseco: Aseco) -> str:
    uid = urllib.parse.quote(str(_current_map.get("uid", "") or ""))
    env = urllib.parse.quote(str(_current_map.get("environment", "") or ""))
    game = urllib.parse.quote(str(getattr(aseco.server, "game", "TMF") or "TMF"))
    return f"http://{_cfg.website}/goto?uid={uid}&env={env}&game={game}"


def _normalise_web_url(url: str) -> str:
    val = str(url or "").strip()
    if not val:
        return ""
    if val.startswith("https://"):
        return "http://" + val[len("https://"):]
    if val.startswith("http://"):
        return val
    return f"http://{val.lstrip('/')}"


def _tmx_public_host(aseco: Aseco) -> str:
    game = aseco.server.get_game()
    if game == "TMF":
        section = "TMNF" if getattr(aseco.server, "packmask", "") == "Stadium" else "TMU"
    else:
        section = game
    return TMX_HOST_ALIASES.get((section or "").upper(), "tmnf.exchange")


def _tmx_page_url(aseco: Aseco) -> str:
    # First try challenge object attributes set by plugin_tmxinfo
    ch = getattr(aseco.server, "challenge", None)
    for attr in ("tmx", "mx"):
        obj = getattr(ch, attr, None)
        if obj is not None:
            pageurl = getattr(obj, "pageurl", "") or ""
            if pageurl:
                return _normalise_web_url(pageurl).replace("&", "&amp;")
            obj_id = str(getattr(obj, "id", "") or "").strip()
            if obj_id.isdigit():
                return f"http://{_tmx_public_host(aseco)}/trackshow/{obj_id}"
    tmx_id = str(getattr(ch, "tmx_id", "") or "").strip()
    if tmx_id.isdigit():
        prefix = str(getattr(ch, "tmx_prefix", "") or "").strip().lower()
        host = TMX_PREFIX_HOSTS.get(prefix, _tmx_public_host(aseco))
        return f"http://{host}/trackshow/{tmx_id}"
    # Fall back to TMX track ID stored in karma data
    tmx_id = str(_karma.get("data", {}).get("tmx", "") or "").strip()
    if tmx_id and tmx_id.isdigit():
        return f"http://{_tmx_public_host(aseco)}/trackshow/{tmx_id}"
    return f"http://{_tmx_public_host(aseco)}"


def _ensure_player_state(player: Any) -> None:
    if not hasattr(player, "data") or player.data is None:
        player.data = {}
    player.data.setdefault("ManiaKarma", {})
    mk = player.data["ManiaKarma"]
    mk.setdefault("ReminderWindow", False)
    mk.setdefault("FinishedMapCount", 0)
    mk.setdefault("LotteryPayout", 0)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _get_pool():
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        return await get_pool()
    except Exception:
        return None


async def _get_player_id(login: str) -> int:
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_player_id
        return int(await get_player_id(login))
    except Exception:
        return 0


async def _db_fetchone(query: str, params: tuple = ()):
    pool = await _get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()


async def _db_fetchall(query: str, params: tuple = ()):
    pool = await _get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def _db_execute(query: str, params: tuple = ()) -> None:
    pool = await _get_pool()
    if not pool:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params)


async def _get_current_map_info(aseco: Aseco) -> dict[str, Any]:
    ch = getattr(aseco.server, "challenge", None)
    if ch is None:
        return {
            "id": False,
            "uid": "",
            "name": "",
            "author": "",
            "environment": "",
            "authortime": 0,
            "authorscore": 0,
            "nblaps": 0,
            "nbchecks": 0,
            "mood": "",
            "mx": {},
        }

    map_id = getattr(ch, "id", False)
    uid = str(getattr(ch, "uid", "") or "")
    if not map_id and uid:
        row = await _db_fetchone("SELECT Id FROM challenges WHERE Uid=%s LIMIT 1", (uid,))
        if row:
            map_id = int(row[0])

    mx = {}
    for attr in ("mx", "tmx"):
        obj = getattr(ch, attr, None)
        if obj is not None:
            mx = {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_") and not callable(getattr(obj, k, None))}
            break

    return {
        "id": map_id if map_id not in (None, 0, "") else False,
        "uid": uid,
        "name": getattr(ch, "name", "") or "",
        "author": getattr(ch, "author", "") or "",
        "environment": getattr(ch, "environment", "") or getattr(ch, "environnement", "") or "",
        "authortime": int(getattr(ch, "authortime", 0) or 0),
        "authorscore": int(getattr(ch, "authorscore", 0) or 0),
        "nblaps": int(getattr(ch, "nblaps", 0) or 0),
        "nbchecks": int(getattr(ch, "nbchecks", 0) or 0),
        "mood": getattr(ch, "mood", "") or "",
        "mx": mx,
    }


async def _seed_finish_counts(aseco: Aseco, players: list[Any] | None = None) -> None:
    if _cfg.require_finish <= 0 or not _current_map.get("id"):
        return
    if players is None:
        players = _players_all(aseco)
    ids = [int(getattr(p, "id", 0) or 0) for p in players if int(getattr(p, "id", 0) or 0) > 0]
    if not ids:
        return
    in_clause = ",".join(["%s"] * len(ids))
    query = (
        "SELECT p.Login, COUNT(t.Id) AS cnt "
        "FROM rs_times t "
        "LEFT JOIN players p ON p.Id=t.playerID "
        f"WHERE t.playerID IN ({in_clause}) AND t.ChallengeId=%s "
        "GROUP BY p.Login"
    )
    rows = await _db_fetchall(query, tuple(ids) + (int(_current_map["id"]),))
    counts = {str(r[0]): int(r[1] or 0) for r in rows}
    for p in players:
        _ensure_player_state(p)
        p.data["ManiaKarma"]["FinishedMapCount"] = counts.get(p.login, p.data["ManiaKarma"].get("FinishedMapCount", 0))


async def _get_local_votes(map_id: int | bool, login: str | None = None) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    if not map_id:
        return result

    # schema 1: rs_karma(Score, PlayerId, ChallengeId)
    try:
        if login:
            rows = await _db_fetchall(
                "SELECT p.Login, k.Score FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId WHERE k.ChallengeId=%s AND p.Login=%s",
                (int(map_id), login),
            )
        else:
            rows = await _db_fetchall(
                "SELECT p.Login, k.Score FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId WHERE k.ChallengeId=%s",
                (int(map_id),),
            )
        for row in rows:
            result[str(row[0])] = {"vote": int(row[1] or 0), "previous": 0}
        return result
    except Exception:
        pass

    # schema 2 fallback: rs_karma(vote, PlayerId, uid)
    uid = _current_uid()
    if not uid:
        return result
    try:
        if login:
            rows = await _db_fetchall(
                "SELECT p.Login, k.vote FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId WHERE k.uid=%s AND p.Login=%s",
                (uid, login),
            )
        else:
            rows = await _db_fetchall(
                "SELECT p.Login, k.vote FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId WHERE k.uid=%s",
                (uid,),
            )
        for row in rows:
            result[str(row[0])] = {"vote": int(row[1] or 0), "previous": 0}
    except Exception:
        pass
    return result


async def _save_local_votes(votes: dict[str, int]) -> None:
    if not votes:
        return
    map_id = _current_map.get("id")
    uid = _current_uid()
    for login, vote in votes.items():
        player_id = await _get_player_id(login)
        if player_id <= 0:
            continue
        ok = False
        if map_id:
            try:
                await _db_execute(
                    "INSERT INTO rs_karma (Score, PlayerId, ChallengeId) VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE Score=VALUES(Score)",
                    (int(vote), int(player_id), int(map_id)),
                )
                ok = True
            except Exception:
                pass
            if not ok:
                try:
                    row = await _db_fetchone(
                        "SELECT Id FROM rs_karma WHERE PlayerId=%s AND ChallengeId=%s LIMIT 1",
                        (int(player_id), int(map_id)),
                    )
                    if row:
                        await _db_execute("UPDATE rs_karma SET Score=%s WHERE Id=%s", (int(vote), int(row[0])))
                    else:
                        await _db_execute(
                            "INSERT INTO rs_karma (Score, PlayerId, ChallengeId) VALUES (%s, %s, %s)",
                            (int(vote), int(player_id), int(map_id)),
                        )
                    ok = True
                except Exception:
                    pass
        if not ok and uid:
            try:
                await _db_execute(
                    "INSERT INTO rs_karma (PlayerId, uid, vote) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE vote=VALUES(vote)",
                    (int(player_id), uid, int(vote)),
                )
            except Exception as exc:
                logger.debug("[ManiaKarma] failed to store local vote for %s: %s", login, exc)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def _api_get(url: str, timeout: int) -> str | None:
    try:
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as sess:
            async with sess.get(url) as resp:
                if resp.status == 200:
                    return await resp.text(errors="replace")
    except Exception as exc:
        logger.debug("[ManiaKarma] api GET failed: %s", exc)
    return None


async def _api_post(url: str, payload: str, timeout: int) -> tuple[int, str | None]:
    try:
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as sess:
            async with sess.post(url, data=payload.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"}) as resp:
                return resp.status, await resp.text(errors="replace")
    except Exception as exc:
        logger.debug("[ManiaKarma] api POST failed: %s", exc)
    return 0, None


async def _api_auth(aseco: Aseco) -> bool:
    global _api_authcode, _api_connected, _retrytime
    login = getattr(aseco.server, "serverlogin", "") or getattr(aseco.server, "login", "") or ""
    server_name = getattr(aseco.server, "name", "") or ""
    zone = getattr(aseco.server, "zone", "") or ""
    name_b64 = base64.b64encode(server_name.encode()).decode()
    url = (
        f"{_cfg.api_auth_url}?Action=Auth"
        f"&login={urllib.parse.quote(login)}"
        f"&name={name_b64}"
        f"&game=TmForever"
        f"&zone={urllib.parse.quote(zone)}"
        f"&nation={urllib.parse.quote(_cfg.nation)}"
    )
    body = await _api_get(url, _cfg.connect_timeout)
    if not body:
        _api_connected = False
        _retrytime = int(asyncio.get_running_loop().time()) + 60
        return False
    try:
        xml = ET.fromstring(body)
        status = int(xml.findtext("status") or 0)
        if status == 200:
            _api_authcode = xml.findtext("authcode") or ""
            _cfg.api_url = xml.findtext("api_url") or _cfg.api_auth_url
            _api_connected = True
            _retrytime = 0
            return True
    except Exception as exc:
        logger.debug("[ManiaKarma] auth parse failed: %s", exc)
    _api_connected = False
    _retrytime = int(asyncio.get_running_loop().time()) + 60
    return False


async def _api_get_votes(aseco: Aseco, target_login: str | None = None) -> dict[str, Any]:
    if not _api_connected or not _cfg.api_url or not _current_uid():
        return {}
    server_login = getattr(aseco.server, "serverlogin", "") or getattr(aseco.server, "login", "") or ""
    map_b64 = base64.b64encode(str(_current_map.get("name", "")).encode()).decode()
    players = [target_login] if target_login else [p.login for p in _players_all(aseco)]
    player_param = "|".join(urllib.parse.quote(p) for p in players)
    url = (
        f"{_cfg.api_url}?Action=Get"
        f"&login={urllib.parse.quote(server_login)}"
        f"&authcode={urllib.parse.quote(_api_authcode)}"
        f"&uid={urllib.parse.quote(str(_current_map.get('uid', '')))}"
        f"&map={map_b64}"
        f"&author={urllib.parse.quote(str(_current_map.get('author', '')))}"
        f"&env={urllib.parse.quote(str(_current_map.get('environment', '')))}"
        f"&player={player_param}"
    )
    body = await _api_get(url, _cfg.wait_timeout)
    if not body:
        return {}
    try:
        xml = ET.fromstring(body)
        if int(xml.findtext("status") or 0) != 200:
            return {}
        votes_node = xml.find("votes")
        out = {
            "karma": 0,
            "total": 0,
            "fantastic": {"count": 0, "percent": 0.0},
            "beautiful": {"count": 0, "percent": 0.0},
            "good": {"count": 0, "percent": 0.0},
            "bad": {"count": 0, "percent": 0.0},
            "poor": {"count": 0, "percent": 0.0},
            "waste": {"count": 0, "percent": 0.0},
            "players": {},
        }
        if votes_node is not None:
            out["karma"] = int(votes_node.findtext("karma") or 0)
            total = 0
            for key in ("fantastic", "beautiful", "good", "bad", "poor", "waste"):
                node = votes_node.find(key)
                if node is not None:
                    cnt = int(node.get("count", "0") or 0)
                    pct = float(node.get("percent", "0") or 0.0)
                    out[key] = {"count": cnt, "percent": pct}
                    total += cnt
            out["total"] = total
        players_node = xml.find("players")
        if players_node is not None:
            for pl in players_node.findall("player"):
                login = pl.get("login", "")
                if login:
                    out["players"][login] = {
                        "vote": int(pl.get("vote", "0") or 0),
                        "previous": int(pl.get("previous", "0") or 0),
                    }
        return out
    except Exception as exc:
        logger.debug("[ManiaKarma] get parse failed: %s", exc)
        return {}


async def _api_vote_multisend(aseco: Aseco, votes: dict[str, int]) -> None:
    global _retrytime
    if not votes:
        return
    if _retrytime > 0:
        return
    if not _api_connected:
        await _api_auth(aseco)
        if not _api_connected:
            return
    login = getattr(aseco.server, "serverlogin", "") or getattr(aseco.server, "login", "") or ""
    authortime = 0 if _get_mode(aseco) == 4 else int(_current_map.get("authortime", 0) or 0)
    authorscore = int(_current_map.get("authorscore", 0) or 0) if _get_mode(aseco) == 4 else 0
    pairs = "|".join(f"{urllib.parse.quote(k)}={int(v)}" for k, v in votes.items())
    url = (
        f"{_cfg.api_url}?Action=Vote"
        f"&login={urllib.parse.quote(login)}"
        f"&authcode={urllib.parse.quote(_api_authcode)}"
        f"&uid={urllib.parse.quote(str(_current_map.get('uid', '')))}"
        f"&map={base64.b64encode(str(_current_map.get('name', '')).encode()).decode()}"
        f"&author={urllib.parse.quote(str(_current_map.get('author', '')))}"
        f"&atime={authortime}"
        f"&ascore={authorscore}"
        f"&nblaps={urllib.parse.quote(str(_current_map.get('nblaps', 0)))}"
        f"&nbchecks={urllib.parse.quote(str(_current_map.get('nbchecks', 0)))}"
        f"&mood={urllib.parse.quote(str(_current_map.get('mood', '')))}"
        f"&env={urllib.parse.quote(str(_current_map.get('environment', '')))}"
        f"&votes={pairs}"
        f"&tmx={urllib.parse.quote(str(_karma.get('data', {}).get('tmx', '')))}"
    )
    body = await _api_get(url, _cfg.wait_timeout)
    if not body:
        _retrytime = int(asyncio.get_running_loop().time()) + 60


# ---------------------------------------------------------------------------
# calculation / sync helpers
# ---------------------------------------------------------------------------

def _calculate_karma(which: list[str]) -> None:
    for side in which:
        votes = _karma[side]["votes"]
        total = sum(int(votes[key]["count"] or 0) for key in VOTE_KEYS.values())
        votes["total"] = total
        if total <= 0:
            votes["karma"] = 0
            for key in VOTE_KEYS.values():
                votes[key]["percent"] = 0.0
            continue
        for val, key in VOTE_KEYS.items():
            votes[key]["percent"] = round(votes[key]["count"] * 100.0 / total, 2)
        if _cfg.karma_calculation_method.upper() == "RASP":
            positive = votes["fantastic"]["count"] + votes["beautiful"]["count"] + votes["good"]["count"]
            votes["karma"] = int(round(positive * 100.0 / total))
        else:
            score = sum(int(votes[key]["count"] or 0) * value for key, value in VOTE_SCORES.items())
            votes["karma"] = int(round(score / total))


async def _load_local_karma() -> None:
    local_votes = _karma["local"]["votes"]
    for key in VOTE_KEYS.values():
        local_votes[key]["count"] = 0
        local_votes[key]["percent"] = 0.0
    local_votes["total"] = 0
    local_votes["karma"] = 0
    players = await _get_local_votes(_current_map.get("id"), None)
    _karma["local"]["players"] = players
    for data in players.values():
        vote = int(data.get("vote", 0) or 0)
        key = VOTE_KEYS.get(vote)
        if key:
            local_votes[key]["count"] += 1
    _calculate_karma(["local"])


async def _fetch_global_votes(aseco: Aseco, target_login: str | None = None) -> None:
    result = await _api_get_votes(aseco, target_login)
    if not result:
        return
    gvotes = _karma["global"]["votes"]
    for key in VOTE_KEYS.values():
        gvotes[key]["count"] = int(result.get(key, {}).get("count", 0) or 0)
        gvotes[key]["percent"] = float(result.get(key, {}).get("percent", 0.0) or 0.0)
    gvotes["total"] = int(result.get("total", 0) or 0)
    gvotes["karma"] = int(result.get("karma", 0) or 0)
    if target_login:
        player_data = result.get("players", {}).get(target_login)
        if player_data is not None:
            _karma["global"]["players"][target_login] = {
                "vote": int(player_data.get("vote", 0) or 0),
                "previous": int(player_data.get("previous", 0) or 0),
            }
    else:
        for login, pdata in result.get("players", {}).items():
            _karma["global"]["players"][login] = {
                "vote": int(pdata.get("vote", 0) or 0),
                "previous": int(pdata.get("previous", 0) or 0),
            }


def _rebuild_counts_from_players(side: str) -> None:
    votes = _karma[side]["votes"]
    for key in VOTE_KEYS.values():
        votes[key]["count"] = 0
        votes[key]["percent"] = 0.0
    for pdata in _karma[side]["players"].values():
        key = VOTE_KEYS.get(int(pdata.get("vote", 0) or 0))
        if key:
            votes[key]["count"] += 1
    _calculate_karma([side])


async def _sync_global_and_local(source: str, setup_global: bool = False) -> None:
    destination = "local" if source == "global" else "global"
    players = _karma.get(source, {}).get("players", {})
    if not players:
        return
    changed_dest = False
    changed_local_db: dict[str, int] = {}
    for login, pdata in players.items():
        vote = int(pdata.get("vote", 0) or 0)
        if vote == 0:
            continue
        dest_vote = int(_karma[destination]["players"].get(login, {}).get("vote", 0) or 0)
        if dest_vote != vote:
            _karma[destination]["players"][login] = {"vote": vote, "previous": dest_vote}
            changed_dest = True
            if destination == "local":
                changed_local_db[login] = vote
            if setup_global and source == "local":
                _karma["new"]["players"][login] = vote
    if changed_dest:
        _rebuild_counts_from_players(destination)
    if changed_local_db and _cfg.save_karma_also_local:
        await _save_local_votes(changed_local_db)


# ---------------------------------------------------------------------------
# UI builders
# ---------------------------------------------------------------------------

def _build_widget_skeleton(mode: int) -> str:
    gm = _cfg.gm_cfg(mode)
    is_score = mode == 7
    bg_style = _cfg.score_bg_style if is_score else _cfg.race_bg_style
    bg_substyle = _cfg.score_bg_substyle if is_score else _cfg.race_bg_substyle
    title_style = _cfg.score_title_style if is_score else _cfg.race_title_style
    title_substyle = _cfg.score_title_substyle if is_score else _cfg.race_title_substyle
    title = _cfg.score_title if is_score else _cfg.race_title
    icon_style = _cfg.score_icon_style if is_score else _cfg.race_icon_style
    icon_substyle = _cfg.score_icon_substyle if is_score else _cfg.race_icon_substyle

    parts = [f'<manialink id="{ML_SKELETON}">', f'<frame posn="{gm.pos_x} {gm.pos_y} 10">']
    if is_score:
        parts.append(f'<quad posn="0 0 0.02" sizen="15.76 10.75" style="{bg_style}" substyle="{bg_substyle}"/>')
    else:
        parts.append(f'<quad posn="0 0 0.02" sizen="15.76 10.75" action="{ACT_OPEN_DETAIL}" style="{bg_style}" substyle="{bg_substyle}"/>')
        parts.append(
            f'<quad posn="{-0.3 if gm.pos_x > 0 else 12.46} -7.4 0.05" sizen="3.5 3.5" image="{_cfg.img_open_left if gm.pos_x > 0 else _cfg.img_open_right}"/>'
        )
    parts.append('<frame posn="0 0 0">')
    parts.append(f'<quad posn="0.4 -0.3 3" sizen="14.96 2" url="{_track_page_url_dummy()}" style="{title_style}" substyle="{title_substyle}"/>')
    if gm.pos_x > 0:
        parts.append(f'<quad posn="0.6 -0.15 3.1" sizen="2.3 2.3" style="{icon_style}" substyle="{icon_substyle}"/>')
        parts.append(f'<label posn="3.2 -0.6 3.2" sizen="10 0" halign="left" textsize="1" text="{title}"/>')
    else:
        parts.append(f'<quad posn="13.1 -0.15 3.1" sizen="2.3 2.3" style="{icon_style}" substyle="{icon_substyle}"/>')
        parts.append(f'<label posn="12.86 -0.6 3.2" sizen="10 0" halign="right" textsize="1" text="{title}"/>')
    parts.append(f'<frame posn="1.83 -8.3 1"><quad posn="0.2 -0.08 0.1" sizen="11.8 1.4" action="{ACT_IGNORE}" bgcolor="0000"/></frame>')
    buttons = [
        (1.83, ACT_VOTE_P3, _cfg.bg_pos_default, _cfg.bg_pos_focus, _cfg.text_pos_color, '+++', '0.8', '-0.25'),
        (3.83, ACT_VOTE_P2, _cfg.bg_pos_default, _cfg.bg_pos_focus, _cfg.text_pos_color, '++', '0.8', '-0.25'),
        (5.83, ACT_VOTE_P1, _cfg.bg_pos_default, _cfg.bg_pos_focus, _cfg.text_pos_color, '+', '0.8', '-0.25'),
        (7.83, ACT_VOTE_N1, _cfg.bg_neg_default, _cfg.bg_neg_focus, _cfg.text_neg_color, '-', '0.9', '0'),
        (9.83, ACT_VOTE_N2, _cfg.bg_neg_default, _cfg.bg_neg_focus, _cfg.text_neg_color, '--', '0.9', '0'),
        (11.83, ACT_VOTE_N3, _cfg.bg_neg_default, _cfg.bg_neg_focus, _cfg.text_neg_color, '---', '0.9', '0'),
    ]
    for bx, act, c1, c2, tc, txt, scale, ty in buttons:
        parts.append(f'<frame posn="{bx} -8.5 1">')
        parts.append(f'<label posn="0.2 -0.08 0.2" sizen="1.8 1.4" action="{act}" focusareacolor1="{c1}" focusareacolor2="{c2}" text=" "/>')
        parts.append(f'<label posn="1.12 {ty} 0.4" sizen="1.8 0" textsize="1" scale="{scale}" halign="center" textcolor="{tc}" text="{txt}"/>')
        parts.append('</frame>')
    parts.append('</frame></frame></manialink>')
    return ''.join(parts)


def _track_page_url_dummy() -> str:
    uid = urllib.parse.quote(str(_current_map.get("uid", "") or ""))
    env = urllib.parse.quote(str(_current_map.get("environment", "") or ""))
    return f"http://{_cfg.website}/goto?uid={uid}&amp;env={env}&amp;game=TmForever"


def _build_widget_cups(mode: int) -> str:
    gm = _cfg.gm_cfg(mode)
    global_votes = _karma["global"]["votes"]
    local_votes = _karma["local"]["votes"]

    total_cups = 10
    cup_offset = [0.8, 0.85, 0.85, 0.875, 0.90, 0.925, 0.95, 0.975, 1.0, 1.025]
    cup_gold_amount = 0
    source = global_votes if global_votes["karma"] > 0 else local_votes
    if source["karma"] > 0 and source["total"] > 0:
        if _cfg.karma_calculation_method.upper() == "RASP":
            positive = source["fantastic"]["count"] + source["beautiful"]["count"] + source["good"]["count"]
            cup_gold_amount = round(positive / source["total"] * total_cups)
        else:
            cup_gold_amount = int(source["karma"] / total_cups)
    cup_gold_amount = max(0, min(total_cups, cup_gold_amount))

    cups_xml = []
    for i in range(total_cups):
        layer = f"0.{i + 1:02d}"
        width = 1.1 + (i / total_cups) * cup_offset[i]
        height = 1.5 + (i / total_cups) * cup_offset[i]
        image = _cfg.img_cup_gold if i < cup_gold_amount else _cfg.img_cup_silver
        cups_xml.append(f'<quad posn="{cup_offset[i] * i} 0 {layer}" sizen="{width} {height}" valign="bottom" image="{image}"/>')

    def _color(value: int, local: bool) -> str:
        if value <= 30:
            return 'F00F' if local else 'D00F'
        if value <= 60:
            return 'FF0F' if local else 'DD0F'
        return '0F0F' if local else '0D0F'

    parts = [f'<manialink id="{ML_CUPS}"><frame posn="{gm.pos_x} {gm.pos_y} 10">']
    parts.append(f'<frame posn="2.23 -4.95 0.01">{"".join(cups_xml)}</frame>')
    parts.append('<frame posn="2.1 -5.35 0">')
    parts.append('<quad posn="0 -0.1 1" sizen="0.1 2.85" bgcolor="FFF5"/>')
    parts.append('<label posn="0.3 -0.1 1" sizen="4 1.1" textsize="1" scale="0.65" textcolor="FFFF" text="GLOBAL"/>')
    parts.append(f'<label posn="3.3 0 1" sizen="3 1.4" textsize="1" scale="0.9" textcolor="{_color(global_votes["karma"], False)}" text="$O{global_votes["karma"]}"/>')
    parts.append(f'<label posn="0.3 -1.3 1" sizen="6.6 1.2" textsize="1" scale="0.85" textcolor="0F3F" text="{_number(global_votes["total"])} {(_cfg.msg_vote_singular if global_votes["total"] == 1 else _cfg.msg_vote_plural)}"/>')
    parts.append('</frame>')
    parts.append('<frame posn="8.75 -5.35 0">')
    parts.append('<quad posn="0 -0.1 1" sizen="0.1 2.85" bgcolor="FFF5"/>')
    parts.append('<label posn="0.3 -0.1 1" sizen="4 1.1" textsize="1" scale="0.65" textcolor="FFFF" text="LOCAL " />')
    parts.append(f'<label posn="3 0 1" sizen="3 1.4" textsize="1" scale="0.9" textcolor="{_color(local_votes["karma"], True)}" text="$O{local_votes["karma"]}"/>')
    parts.append(f'<label posn="0.3 -1.3 1" sizen="6.6 1.2" textsize="1" scale="0.85" textcolor="0F3F" text="{_number(local_votes["total"])} {(_cfg.msg_vote_singular if local_votes["total"] == 1 else _cfg.msg_vote_plural)}"/>')
    parts.append('</frame></frame></manialink>')
    return ''.join(parts)


def _build_player_marker(player: Any, mode: int) -> str:
    _ensure_player_state(player)
    pdata = _karma["global"]["players"].get(player.login, {"vote": 0})
    vote = int(pdata.get("vote", 0) or 0)
    finished = int(player.data["ManiaKarma"].get("FinishedMapCount", 0) or 0)
    locked = _cfg.require_finish > 0 and finished < _cfg.require_finish and vote == 0
    preset: dict[int, tuple[str, int]] = {}
    for v in (3, 2, 1, -1, -2, -3):
        if vote == v:
            preset[v] = (_cfg.bg_disabled, ACT_IGNORE)
        elif locked:
            preset[v] = (_cfg.bg_vote, ACT_VOTE_LOCKED)
    positions = {3: 1.83, 2: 3.83, 1: 5.83, -1: 7.83, -2: 9.83, -3: 11.83}
    gm = _cfg.gm_cfg(mode)
    marker = []
    for v, (bg, act) in preset.items():
        marker.append(f'<frame posn="{positions[v]} -8.5 1"><quad posn="0.2 -0.08 0.3" sizen="1.8 1.4" action="{act}" bgcolor="{bg}"/></frame>')
    xml = [f'<manialink id="{ML_MARKER}">']
    if marker:
        xml.append(f'<frame posn="{gm.pos_x} {gm.pos_y} 10">{"".join(marker)}</frame>')
    xml.append('</manialink>')
    return ''.join(xml)


async def _send_widget_combination(aseco: Aseco, widgets: list[str], player: Any | None = None) -> None:
    if not _players_all(aseco):
        return
    xml = ['<?xml version="1.0" encoding="UTF-8"?><manialinks>']
    for widget in widgets:
        if widget == 'hide_all':
            for ml in (ML_WINDOWS, ML_SKELETON, ML_MARKER, ML_CUPS, ML_CONNECTION, ML_LOADING):
                xml.append(f'<manialink id="{ml}"></manialink>')
            break
        if widget == 'hide_window':
            xml.append(f'<manialink id="{ML_WINDOWS}"></manialink>')
            continue
        gm_enabled = _cfg.gm_cfg(_cfg.current_state).enabled
        if not gm_enabled:
            for ml in (ML_SKELETON, ML_MARKER, ML_CUPS):
                xml.append(f'<manialink id="{ml}"></manialink>')
            continue
        if widget == 'skeleton_race':
            xml.append(_build_widget_skeleton(_get_mode(aseco)))
        elif widget == 'skeleton_score':
            xml.append(_build_widget_skeleton(7))
        elif widget == 'cups_values':
            xml.append(_build_widget_cups(_cfg.current_state))
        elif widget == 'player_marker' and player is not None:
            xml.append(_build_player_marker(player, _cfg.current_state))
    xml.append('</manialinks>')
    payload = ''.join(xml)
    if player is not None:
        await aseco.client.query_ignore_result('SendDisplayManialinkPageToLogin', player.login, payload, 0, False)
    else:
        await aseco.client.query_ignore_result('SendDisplayManialinkPage', payload, 0, False)


async def _send_connection_status(aseco: Aseco, status: bool, mode: int) -> None:
    xml = [f'<manialink id="{ML_CONNECTION}">']
    if status is False:
        await _send_loading_indicator(aseco, False, mode)
        gm = _cfg.gm_cfg(mode)
        xml.append(f'<frame posn="{gm.pos_x} {gm.pos_y} 20"><quad posn="0.5 -5.2 0.9" sizen="1.4 1.4" style="Icons128x128_1" substyle="Multiplayer"/></frame>')
    xml.append('</manialink>')
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', ''.join(xml), 0, False)


async def _send_loading_indicator(aseco: Aseco, status: bool, mode: int) -> None:
    xml = [f'<manialink id="{ML_LOADING}">']
    if status and _cfg.img_progress_indicator:
        gm = _cfg.gm_cfg(mode)
        xml.append(f'<frame posn="{gm.pos_x} {gm.pos_y} 20"><quad posn="0.5 -5.2 0.9" sizen="1.4 1.4" image="{_cfg.img_progress_indicator}"/></frame>')
    xml.append('</manialink>')
    await aseco.client.query_ignore_result('SendDisplayManialinkPage', ''.join(xml), 0, False)


async def _send_window(aseco: Aseco, login: str, window_xml: str) -> None:
    payload = f'<?xml version="1.0" encoding="UTF-8"?><manialinks>{window_xml}</manialinks>'
    await aseco.client.query_ignore_result('SendDisplayManialinkPageToLogin', login, payload, 0, False)


async def _show_help_window(aseco: Aseco, player: Any, message: str) -> None:
    logo = f'<quad posn="57.2 -8.0 0.05" sizen="18 18" image="{_cfg.img_maniakarma_logo}" url="http://www.mania-karma.com"/>' if _cfg.img_maniakarma_logo else ''
    msg = _sanitize_ml_text(aseco.format_colors((message or '').replace('{br}', '\n')))
    xml = (
        f'<manialink id="{ML_WINDOWS}">'
        f'<frame posn="-40.1 30.45 18.50">'
        f'<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>'
        f'<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>'
        f'<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>'
        f'<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>'
        f'<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>'
        f'<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="Rankings"/>'
        f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="ManiaKarma help"/>'
        f'<frame posn="77.4 1.3 0.05">'
        f'<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>'
        f'<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>'
        f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ACT_CLOSE}" style="Icons64x64_1" substyle="Close"/>'
        f'</frame>'
        f'<frame posn="3.2 -7.4 0.04">'
        f'{logo}'
        f'<label posn="0 0 0.05" sizen="52 0" autonewline="1" textsize="1" scale="0.9" textcolor="FFFF" text="{msg}"/>'
        f'</frame>'
        f'<frame posn="28.6 -53.35 0.10">'
        f'<quad posn="0 0 0.01" sizen="21.5 2.5" url="{_track_page_url_dummy()}" style="Bgs1" substyle="BgIconBorder"/>'
        f'<label posn="1.5 -0.65 0.01" sizen="30 1" textsize="1" scale="0.8" textcolor="000F" text="MORE INFO ON MANIA-KARMA.COM"/>'
        f'</frame>'
        f'</frame></manialink>'
    )
    _window_state[player.login] = ("help", 0)
    await _send_window(aseco, player.login, xml)


async def _show_details_window(aseco: Aseco, login: str) -> None:
    g = _karma["global"]["votes"]
    l = _karma["local"]["votes"]

    def _karma_color(value: int, local: bool = False) -> str:
        if _cfg.karma_calculation_method.upper() != "DEFAULT":
            return "$FFF"
        if 0 <= value <= 30:
            return "$F00" if local else "$D00"
        if 31 <= value <= 60:
            return "$FF0" if local else "$DD0"
        if 61 <= value <= 100:
            return "$0F0" if local else "$0D0"
        return "$FFF"

    def _window_start(title: str, buttons: str) -> list[str]:
        return [
            f'<manialink id="{ML_WINDOWS}">',
            '<frame posn="-40.1 30.45 18.50">',
            '<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>',
            '<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>',
            '<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>',
            '<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>',
            '<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>',
            '<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="Rankings"/>',
            f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="{_sanitize_ml_text(title)}"/>',
            '<frame posn="77.4 1.3 0.05">',
            '<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>',
            '<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>',
            f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ACT_CLOSE}" style="Icons64x64_1" substyle="Close"/>',
            '</frame>',
            buttons,
        ]

    def _window_footer() -> str:
        return (
            '<frame posn="28.6 -53.35 0.10">'
            f'<quad posn="0 0 0.01" sizen="21.5 2.5" url="{_track_page_url_dummy()}" style="Bgs1" substyle="BgIconBorder"/>'
            '<label posn="1.5 -0.65 0.01" sizen="30 1" textsize="1" scale="0.8" textcolor="000F" text="MORE INFO ON MANIA-KARMA.COM"/>'
            '</frame>'
            '</frame>'
            '</manialink>'
        )

    buttons = (
        '<frame posn="67.05 -53.2 0.04">'
        f'<quad posn="1.65 0 0.12" sizen="3.2 3.2" action="{ACT_REFRESH}" style="Icons64x64_1" substyle="Refresh"/>'
        '<quad posn="4.95 0 0.12" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        '<quad posn="4.95 0 0.13" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        f'<quad posn="8.25 0 0.12" sizen="3.2 3.2" action="{ACT_OPEN_WHO}" style="Icons64x64_1" substyle="ArrowNext"/>'
        '</frame>'
    )

    def _percent_text(v: Any) -> str:
        try:
            return _number(float(v), 2)
        except Exception:
            return _number(0.0, 2)

    def _vote_frame(base_x: float, votes: dict[str, Any]) -> str:
        h_fantastic = (float(votes['fantastic']['percent']) / 3.3333333333) if float(votes['fantastic']['percent']) != 0 else 0.0
        h_beautiful = (float(votes['beautiful']['percent']) / 3.3333333333) if float(votes['beautiful']['percent']) != 0 else 0.0
        h_good = (float(votes['good']['percent']) / 3.3333333333) if float(votes['good']['percent']) != 0 else 0.0
        h_bad = (float(votes['bad']['percent']) / 3.3333333333) if float(votes['bad']['percent']) != 0 else 0.0
        h_poor = (float(votes['poor']['percent']) / 3.3333333333) if float(votes['poor']['percent']) != 0 else 0.0
        h_waste = (float(votes['waste']['percent']) / 3.3333333333) if float(votes['waste']['percent']) != 0 else 0.0

        xml = [f'<frame posn="{base_x} -0.6 0.01">', '<format textsize="1" textcolor="FFFF"/>']

        for pct, y in ((100, 12), (90, 15), (80, 18), (70, 21), (60, 24), (50, 27), (40, 30), (30, 33), (20, 36), (10, 39)):
            xml.append(f'<label posn="4.7 -{y - 0.65:.2f} 0.03" sizen="3 0" halign="right" scale="0.8" text="{pct}%"/>')
            xml.append(f'<quad posn="5.5 -{y} 0.04" sizen="1.5 0.1" bgcolor="FFFD"/>')
            xml.append(f'<quad posn="7.1 -{y} 0.04" sizen="28 0.1" bgcolor="FFF5"/>')
        xml.append('<quad posn="7.1 -42 0.04" sizen="28 0.1" bgcolor="FFFD"/>')
        xml.append('<quad posn="7 -12 0.03" sizen="0.1 30" bgcolor="FFFD"/>')

        xml.append(f'<label posn="10.2 -{40 - h_fantastic:.2f} 0.06" sizen="3.8 0" halign="center" textcolor="FFFF" scale="0.8" text="{_percent_text(votes["fantastic"]["percent"])}%"/>')
        xml.append(f'<label posn="14.7 -{40 - h_beautiful:.2f} 0.06" sizen="3.8 0" halign="center" textcolor="FFFF" scale="0.8" text="{_percent_text(votes["beautiful"]["percent"])}%"/>')
        xml.append(f'<label posn="19.2 -{40 - h_good:.2f} 0.06" sizen="3.8 0" halign="center" textcolor="FFFF" scale="0.8" text="{_percent_text(votes["good"]["percent"])}%"/>')
        xml.append(f'<quad posn="10 -{42 - h_fantastic:.2f} 0.02" sizen="4 {h_fantastic:.2f}" halign="center" bgcolor="170F"/>')
        xml.append(f'<quad posn="14.5 -{42 - h_beautiful:.2f} 0.02" sizen="4 {h_beautiful:.2f}" halign="center" bgcolor="170F"/>')
        xml.append(f'<quad posn="19 -{42 - h_good:.2f} 0.02" sizen="4 {h_good:.2f}" halign="center" bgcolor="170F"/>')
        xml.append(f'<quad posn="10 -{42 - h_fantastic:.2f} 0.03" sizen="4 {h_fantastic:.2f}" halign="center" style="BgRaceScore2" substyle="CupFinisher"/>')
        xml.append(f'<quad posn="14.5 -{42 - h_beautiful:.2f} 0.03" sizen="4 {h_beautiful:.2f}" halign="center" style="BgRaceScore2" substyle="CupFinisher"/>')
        xml.append(f'<quad posn="19 -{42 - h_good:.2f} 0.03" sizen="4 {h_good:.2f}" halign="center" style="BgRaceScore2" substyle="CupFinisher"/>')
        xml.append(f'<quad posn="10 -{42 - h_fantastic:.2f} 0.035" sizen="4.4 {min(h_fantastic, 3):.2f}" halign="center" style="BgsPlayerCard" substyle="BgRacePlayerLine"/>')
        xml.append(f'<quad posn="14.5 -{42 - h_beautiful:.2f} 0.035" sizen="4.4 {min(h_beautiful, 3):.2f}" halign="center" style="BgsPlayerCard" substyle="BgRacePlayerLine"/>')
        xml.append(f'<quad posn="19 -{42 - h_good:.2f} 0.035" sizen="4.4 {min(h_good, 3):.2f}" halign="center" style="BgsPlayerCard" substyle="BgRacePlayerLine"/>')

        xml.append(f'<label posn="23.7 -{40 - h_bad:.2f} 0.06" sizen="3.8 0" halign="center" textcolor="FFFF" scale="0.8" text="{_percent_text(votes["bad"]["percent"])}%"/>')
        xml.append(f'<label posn="28.2 -{40 - h_poor:.2f} 0.06" sizen="3.8 0" halign="center" textcolor="FFFF" scale="0.8" text="{_percent_text(votes["poor"]["percent"])}%"/>')
        xml.append(f'<label posn="32.7 -{40 - h_waste:.2f} 0.06" sizen="3.8 0" halign="center" textcolor="FFFF" scale="0.8" text="{_percent_text(votes["waste"]["percent"])}%"/>')
        xml.append(f'<quad posn="23.5 -{42 - h_bad:.2f} 0.02" sizen="4 {h_bad:.2f}" halign="center" bgcolor="701F"/>')
        xml.append(f'<quad posn="28 -{42 - h_poor:.2f} 0.02" sizen="4 {h_poor:.2f}" halign="center" bgcolor="701F"/>')
        xml.append(f'<quad posn="32.5 -{42 - h_waste:.2f} 0.02" sizen="4 {h_waste:.2f}" halign="center" bgcolor="701F"/>')
        xml.append(f'<quad posn="23.5 -{42 - h_bad:.2f} 0.03" sizen="4 {h_bad:.2f}" halign="center" style="BgRaceScore2" substyle="CupPotentialFinisher"/>')
        xml.append(f'<quad posn="28 -{42 - h_poor:.2f} 0.03" sizen="4 {h_poor:.2f}" halign="center" style="BgRaceScore2" substyle="CupPotentialFinisher"/>')
        xml.append(f'<quad posn="32.5 -{42 - h_waste:.2f} 0.03" sizen="4 {h_waste:.2f}" halign="center" style="BgRaceScore2" substyle="CupPotentialFinisher"/>')
        xml.append(f'<quad posn="23.5 -{42 - h_bad:.2f} 0.035" sizen="4.4 {min(h_bad, 3):.2f}" halign="center" style="BgsPlayerCard" substyle="BgRacePlayerLine"/>')
        xml.append(f'<quad posn="28 -{42 - h_poor:.2f} 0.035" sizen="4.4 {min(h_poor, 3):.2f}" halign="center" style="BgsPlayerCard" substyle="BgRacePlayerLine"/>')
        xml.append(f'<quad posn="32.5 -{42 - h_waste:.2f} 0.035" sizen="4.4 {min(h_waste, 3):.2f}" halign="center" style="BgsPlayerCard" substyle="BgRacePlayerLine"/>')

        xml.append('<label posn="3 -43 0.03" sizen="6 0" textcolor="FFFF" text="Votes:"/>')
        xml.append(f'<label posn="10 -43 0.03" sizen="10 0" halign="center" text="{_number(int(votes["fantastic"]["count"] or 0))}"/>')
        xml.append(f'<label posn="14.5 -43 0.03" sizen="10 0" halign="center" text="{_number(int(votes["beautiful"]["count"] or 0))}"/>')
        xml.append(f'<label posn="19 -43 0.03" sizen="10 0" halign="center" text="{_number(int(votes["good"]["count"] or 0))}"/>')
        xml.append(f'<label posn="23.5 -43 0.03" sizen="10 0" halign="center" text="{_number(int(votes["bad"]["count"] or 0))}"/>')
        xml.append(f'<label posn="28 -43 0.03" sizen="10 0" halign="center" text="{_number(int(votes["poor"]["count"] or 0))}"/>')
        xml.append(f'<label posn="32.5 -43 0.03" sizen="10 0" halign="center" text="{_number(int(votes["waste"]["count"] or 0))}"/>')
        xml.append(f'<label posn="10 -45.05 0.03" sizen="10 0" halign="center" scale="0.8" text="$6C0{_cfg.msg_fantastic.capitalize()}"/>')
        xml.append(f'<label posn="14.5 -45.05 0.03" sizen="10 0" halign="center" scale="0.8" text="$6C0{_cfg.msg_beautiful.capitalize()}"/>')
        xml.append(f'<label posn="19 -45.05 0.03" sizen="10 0" halign="center" scale="0.8" text="$6C0{_cfg.msg_good.capitalize()}"/>')
        xml.append(f'<label posn="23.5 -45.05 0.03" sizen="10 0" halign="center" scale="0.8" text="$F02{_cfg.msg_bad.capitalize()}"/>')
        xml.append(f'<label posn="28 -45.05 0.03" sizen="10 0" halign="center" scale="0.8" text="$F02{_cfg.msg_poor.capitalize()}"/>')
        xml.append(f'<label posn="32.5 -45.05 0.03" sizen="10 0" halign="center" scale="0.8" text="$F02{_cfg.msg_waste.capitalize()}"/>')
        xml.append('<label posn="10 -46.05 0.03" sizen="10 0" halign="center" text="$6C0+++"/>')
        xml.append('<label posn="14.5 -46.05 0.03" sizen="10 0" halign="center" text="$6C0++"/>')
        xml.append('<label posn="19 -46.05 0.03" sizen="10 0" halign="center" text="$6C0+"/>')
        xml.append('<label posn="23.5 -46.05 0.03" sizen="10 0" halign="center" text="$F02-"/>')
        xml.append('<label posn="28 -46.05 0.03" sizen="10 0" halign="center" text="$F02--"/>')
        xml.append('<label posn="32.5 -46.05 0.03" sizen="10 0" halign="center" text="$F02---"/>')
        xml.append('</frame>')
        return ''.join(xml)

    def _player_marker(base_x: float, vote: int) -> str:
        if vote == 3:
            pos = 10
        elif vote == 2:
            pos = 14.5
        elif vote == 1:
            pos = 19
        elif vote == -1:
            pos = 23.5
        elif vote == -2:
            pos = 28
        elif vote == -3:
            pos = 32.5
        else:
            return ''
        return (
            f'<frame posn="{base_x} -48.5 0.02">'
            f'<quad posn="{pos} 0 0.05" sizen="2.8 2.8" halign="center" style="Icons64x64_1" substyle="YellowHigh"/>'
            f'<label posn="{pos} -2.5 0.03" sizen="6 0" halign="center" textsize="1" scale="0.85" textcolor="FFFF" text="Your vote"/>'
            '</frame>'
        )

    xml = _window_start('ManiaKarma detailed vote statistic', buttons)
    xml.append(f'<label posn="9.6 -6.5 0.03" sizen="20 0" textsize="2" scale="0.9" text="$FFFGlobal Karma: $O{_karma_color(int(g["karma"] or 0), False)}{int(g["karma"] or 0)}"/>')
    xml.append(f'<label posn="37.6 -6.5 0.03" sizen="20 0" textsize="2" scale="0.9" halign="right" text="$FFF{_number(int(g["total"] or 0))} {(_cfg.msg_vote_singular if int(g["total"] or 0) == 1 else _cfg.msg_vote_plural)}"/>')
    xml.append(f'<label posn="46.6 -6.5 0.03" sizen="20 0" textsize="2" scale="0.9" text="$FFFLocal Karma: $O{_karma_color(int(l["karma"] or 0), True)}{int(l["karma"] or 0)}"/>')
    xml.append(f'<label posn="74.6 -6.5 0.03" sizen="20 0" textsize="2" scale="0.9" halign="right" text="$FFF{_number(int(l["total"] or 0))} {(_cfg.msg_vote_singular if int(l["total"] or 0) == 1 else _cfg.msg_vote_plural)}"/>')
    xml.append(_vote_frame(2.6, g))
    xml.append(_vote_frame(39.6, l))

    if login in _karma['global']['players']:
        gvote = int(_karma['global']['players'].get(login, {}).get('vote', 0) or 0)
        if gvote:
            xml.append(_player_marker(2.6, gvote))
    if login in _karma['local']['players']:
        lvote = int(_karma['local']['players'].get(login, {}).get('vote', 0) or 0)
        if lvote:
            xml.append(_player_marker(39.6, lvote))

    xml.append(_window_footer())
    _window_state[login] = ("details", 0)
    await _send_window(aseco, login, ''.join(xml))


async def _show_who_window(aseco: Aseco, login: str, page: int = 0) -> None:
    def _window_start(title: str, buttons: str) -> list[str]:
        return [
            f'<manialink id="{ML_WINDOWS}">',
            '<frame posn="-40.1 30.45 18.50">',
            '<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>',
            '<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>',
            '<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>',
            '<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>',
            '<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>',
            '<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x128_1" substyle="Rankings"/>',
            f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="{_sanitize_ml_text(title)}"/>',
            '<frame posn="77.4 1.3 0.05">',
            '<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>',
            '<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>',
            f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ACT_CLOSE}" style="Icons64x64_1" substyle="Close"/>',
            '</frame>',
            buttons,
        ]

    def _window_footer() -> str:
        return (
            '<frame posn="28.6 -53.35 0.10">'
            f'<quad posn="0 0 0.01" sizen="21.5 2.5" url="{_track_page_url_dummy()}" style="Bgs1" substyle="BgIconBorder"/>'
            '<label posn="1.5 -0.65 0.01" sizen="30 1" textsize="1" scale="0.8" textcolor="000F" text="MORE INFO ON MANIA-KARMA.COM"/>'
            '</frame>'
            '</frame>'
            '</manialink>'
        )

    buttons = (
        '<frame posn="67.05 -53.2 0.04">'
        f'<quad posn="1.65 0 0.12" sizen="3.2 3.2" action="{ACT_OPEN_WHO}" style="Icons64x64_1" substyle="Refresh"/>'
        f'<quad posn="4.95 0 0.12" sizen="3.2 3.2" action="{ACT_OPEN_DETAIL}" style="Icons64x64_1" substyle="ArrowPrev"/>'
        '<quad posn="8.25 0 0.12" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        '<quad posn="8.25 0 0.13" sizen="3.2 3.2" style="Icons64x64_1" substyle="StarGold"/>'
        '</frame>'
    )
    xml = _window_start('ManiaKarma who voted what', buttons)
    xml.extend([
        '<frame posn="2.6 -6.5 0.05">',
        '<format textsize="1" textcolor="FFFF"/>',
        '<quad posn="0 0.8 0.02" sizen="17.75 46.88" style="BgsPlayerCard" substyle="BgRacePlayerName"/>',
        '<quad posn="19.05 0.8 0.02" sizen="17.75 46.88" style="BgsPlayerCard" substyle="BgRacePlayerName"/>',
        '<quad posn="38.1 0.8 0.02" sizen="17.75 46.88" style="BgsPlayerCard" substyle="BgRacePlayerName"/>',
        '<quad posn="57.15 0.8 0.02" sizen="17.75 46.88" style="BgsPlayerCard" substyle="BgRacePlayerName"/>',
    ])

    players: list[dict[str, Any]] = []
    for player in _players_all(aseco):
        plogin = getattr(player, 'login', '') or ''
        gvote = int(_karma['global']['players'].get(plogin, {}).get('vote', 0) or 0)
        players.append({
            'id': int(getattr(player, 'id', 0) or 0),
            'nickname': _sanitize_ml_text(getattr(player, 'nickname', plogin) or plogin),
            'vote': -4 if gvote == 0 else gvote,
        })

    players.sort(key=lambda row: (-row['vote'], row['id']))
    vote_index = {3: '+++', 2: '++', 1: '+', -1: '-', -2: '--', -3: '---', -4: 'none'}

    rank = 1
    line = 0
    offset = 0.0
    for player in players:
        quad_y = (-(1.83 * line - 0.2)) if ((1.83 * line - 0.2) > 0) else 0.2
        label_y = -(1.83 * line)
        xml.append(f'<quad posn="{offset + 0.4} {quad_y} 0.03" sizen="16.95 1.83" style="BgsPlayerCard" substyle="BgCardSystem"/>')
        xml.append(f'<label posn="{1 + offset} {label_y} 0.04" sizen="14 1.7" scale="0.9" text="{player["nickname"]}"/>')
        xml.append(f'<label posn="{16.6 + offset} {label_y} 0.04" sizen="3 1.7" halign="right" scale="0.9" textcolor="FFFF" text="{vote_index[player["vote"]]}"/>')
        line += 1
        rank += 1
        if line >= 25:
            offset += 19.05
            line = 0
        if rank >= 101:
            break

    xml.append('</frame>')
    xml.append(_window_footer())
    _window_state[login] = ("who", page)
    await _send_window(aseco, login, ''.join(xml))


async def _show_reminder_window(aseco: Aseco, players: str | list[str]) -> None:
    if isinstance(players, str):
        player_logins = [p for p in players.split(',') if p]
    else:
        player_logins = list(players)
    if not player_logins:
        return
    state = 'score' if _cfg.current_state == 7 else 'race'
    rcfg = _cfg.reminder_score if state == 'score' else _cfg.reminder_race
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?><manialinks>',
        f'<manialink id="{ML_REMINDER}">',
        f'<frame posn="{rcfg.pos_x} {rcfg.pos_y} 2">',
        '<quad posn="0 1 0" sizen="81.8 4.5" style="BgsPlayerCard" substyle="BgRacePlayerName"/>',
        f'<label posn="16.5 0.3 1" sizen="18 1.8" textsize="2" scale="0.8" halign="right" textcolor="FFFF" text="{_cfg.msg_reminder_at_score}"/>',
        '<label posn="16.5 -1.5 1" sizen="14 0.2" textsize="1" scale="0.8" halign="right" textcolor="FFFF" text="powered by mania-karma.com"/>',
        '<frame posn="19.2 0.45 1">',
        '<quad posn="0 0.15 0" sizen="7.5 3.75" style="Bgs1InRace" substyle="BgIconBorder"/>',
        f'<label posn="3.75 -0.5 0" sizen="7 0" textsize="1" halign="center" text="$888{_cfg.msg_undecided.capitalize()}"/>',
        '<label posn="3.75 -1.8 0" sizen="10 0" textsize="1" halign="center" text="$888-/+"/>',
        '</frame>',
        '<frame posn="33 0.3 1">',
    ]
    if _cfg.img_tmx_logo_normal:
        xml.append(f'<quad posn="41.25 0.08 0" sizen="7 4" image="{_cfg.img_tmx_logo_normal}" imagefocus="{_cfg.img_tmx_logo_focus}" url="{_tmx_page_url(aseco)}"/>')
    xml.extend(['</frame>', '</frame>', '</manialink>', '</manialinks>'])
    payload = ''.join(xml)
    await aseco.client.query_ignore_result('SendDisplayManialinkPageToLogin', ','.join(player_logins), payload, 0, False)
    for login in player_logins:
        p = _get_player(aseco, login)
        if p is not None:
            _ensure_player_state(p)
            p.data['ManiaKarma']['ReminderWindow'] = True


async def _show_mx_window(aseco: Aseco, player: Any) -> None:
    if _cfg.current_state != 7:
        return
    pdata = _karma["global"]["players"].get(player.login, {"vote": 0})
    vote = int(pdata.get("vote", 0) or 0)
    voted = {
        3: '$390' + _cfg.msg_fantastic.capitalize(), 2: '$390' + _cfg.msg_beautiful.capitalize(), 1: '$390' + _cfg.msg_good.capitalize(),
        -1: '$D02' + _cfg.msg_bad.capitalize(), -2: '$D02' + _cfg.msg_poor.capitalize(), -3: '$D02' + _cfg.msg_waste.capitalize(),
    }.get(vote, '$888' + _cfg.msg_undecided.capitalize())
    cmd = {3: '$390+++', 2: '$390++', 1: '$390+', -1: '$D02-', -2: '$D02--', -3: '$D02---'}.get(vote, '$888-/+')
    rcfg = _cfg.reminder_score
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?><manialinks>',
        f'<manialink id="{ML_REMINDER}"><frame posn="{rcfg.pos_x} {rcfg.pos_y} 2">',
        '<quad posn="0 1 0" sizen="81.8 4.5" style="BgsPlayerCard" substyle="BgRacePlayerName"/>',
        f'<label posn="16.5 0.3 1" sizen="18 1.8" textsize="2" scale="0.8" halign="right" textcolor="FFFF" text="{_cfg.msg_reminder_at_score}"/>',
        '<label posn="16.5 -1.5 1" sizen="14 0.2" textsize="1" scale="0.8" halign="right" textcolor="FFFF" text="powered by mania-karma.com"/>',
        '<frame posn="19.2 0.45 1">',
        '<quad posn="0 0.15 0" sizen="7.5 3.75" style="Bgs1InRace" substyle="BgIconBorder"/>',
        f'<label posn="3.75 -0.5 0" sizen="7 0" textsize="1" halign="center" text="{voted}"/>',
        f'<label posn="3.75 -1.8 0" sizen="10 0" textsize="1" halign="center" text="{cmd}"/>',
        '</frame>',
        '<frame posn="33 0.2 1">',
        f'<label posn="40.5 -1.3 0" sizen="50 0" halign="right" textsize="1" text="$000Visit &#187; {strip_colors(str(_current_map.get("name", ""))).replace("$", "")} $Z$000 &#171; at"/>',
    ]
    if _cfg.img_tmx_logo_normal:
        xml.append(f'<quad posn="41.25 0.08 0" sizen="7 4" image="{_cfg.img_tmx_logo_normal}" imagefocus="{_cfg.img_tmx_logo_focus}" url="{_tmx_page_url(aseco)}"/>')
    xml.extend(['</frame></frame></manialink></manialinks>'])
    await aseco.client.query_ignore_result('SendDisplayManialinkPageToLogin', player.login, ''.join(xml), 0, False)
    _ensure_player_state(player)
    player.data['ManiaKarma']['ReminderWindow'] = True


async def _close_reminder_window(aseco: Aseco, player: Any | None = None) -> None:
    if not _players_all(aseco):
        return
    xml = f'<?xml version="1.0" encoding="UTF-8"?><manialinks><manialink id="{ML_REMINDER}"></manialink></manialinks>'
    if player is not None:
        _ensure_player_state(player)
        if player.data['ManiaKarma'].get('ReminderWindow'):
            await aseco.client.query_ignore_result('SendDisplayManialinkPageToLogin', player.login, xml, 0, False)
            player.data['ManiaKarma']['ReminderWindow'] = False
    else:
        for p in _players_all(aseco):
            _ensure_player_state(p)
            p.data['ManiaKarma']['ReminderWindow'] = False
        await aseco.client.query_ignore_result('SendDisplayManialinkPage', xml, 0, False)


# ---------------------------------------------------------------------------
# messaging helpers
# ---------------------------------------------------------------------------

def _create_karma_message(login: str, force_display: bool = False) -> str | bool:
    message = ""
    if _cfg.show_karma or force_display:
        message = _cfg.msg_karma_message.replace('{1}', strip_colors(str(_current_map.get('name', '')))).replace('{2}', str(_karma['global']['votes']['karma']))
    if _cfg.show_votes or force_display:
        vote = int(_karma['global']['players'].get(login, {}).get('vote', 0) or 0)
        if vote != 0:
            cmd = {3: '/+++', 2: '/++', 1: '/+', -1: '/-', -2: '/--', -3: '/---'}[vote]
            message += _cfg.msg_karma_your_vote.replace('{1}', _vote_label(vote)).replace('{2}', cmd)
        else:
            message += _cfg.msg_karma_not_voted
    if _cfg.show_details or force_display:
        gv = _karma['global']['votes']
        message += '\n' + _fmt_template(
            _cfg.msg_karma_details,
            gv['karma'],
            gv['fantastic']['percent'], gv['fantastic']['count'],
            gv['beautiful']['percent'], gv['beautiful']['count'],
            gv['good']['percent'], gv['good']['count'],
            gv['bad']['percent'], gv['bad']['count'],
            gv['poor']['percent'], gv['poor']['count'],
            gv['waste']['percent'], gv['waste']['count'],
        )
    return message or False


async def _send_map_karma_message(aseco: Aseco, login: str | None) -> None:
    message = _create_karma_message(login or '', False)
    if not message:
        return
    if login:
        if _cfg.messages_in_window and _cfg.current_state != 7:
            player = _get_player(aseco, login)
            if player is not None:
                await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, message), login)
        else:
            await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, message), login)
    else:
        await aseco.client.query_ignore_result('ChatSendServerMessage', _fmt_message(aseco, message))


# ---------------------------------------------------------------------------
# vote handler
# ---------------------------------------------------------------------------

async def _handle_player_vote(aseco: Aseco, player: Any, vote: int) -> None:
    if _startup_phase(aseco):
        return
    _ensure_player_state(player)
    await _close_reminder_window(aseco, player)

    if _cfg.require_finish > 0 and int(player.data['ManiaKarma'].get('FinishedMapCount', 0) or 0) < _cfg.require_finish:
        msg = _cfg.msg_require_finish.replace('{1}', str(_cfg.require_finish)).replace('{2}', '' if _cfg.require_finish == 1 else 's')
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, msg), player.login)
        return
    if vote == 0:
        return

    global_player = _karma['global']['players'].setdefault(player.login, {'vote': 0, 'previous': 0})
    local_player = _karma['local']['players'].setdefault(player.login, {'vote': 0, 'previous': 0})
    if int(global_player.get('vote', 0) or 0) == vote:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, _cfg.msg_karma_voted), player.login)
        return

    old_global = int(global_player.get('vote', 0) or 0)
    old_local = int(local_player.get('vote', 0) or 0)
    global_player['previous'] = old_global
    local_player['previous'] = old_local

    if old_global != vote:
        _karma['new']['players'][player.login] = vote

    for side, old_vote in (("global", old_global), ("local", old_local)):
        old_key = VOTE_KEYS.get(old_vote)
        if old_key:
            _karma[side]['votes'][old_key]['count'] -= 1

    global_player['vote'] = vote
    local_player['vote'] = vote
    new_key = VOTE_KEYS[vote]
    _karma['global']['votes'][new_key]['count'] += 1
    _karma['local']['votes'][new_key]['count'] += 1
    _calculate_karma(['global', 'local'])

    if _cfg.score_mx_window:
        await _show_mx_window(aseco, player)

    if old_global == 0:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, _cfg.msg_karma_done, strip_colors(str(_current_map.get('name', '')))), player.login)
    elif old_global != vote:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, _cfg.msg_karma_change, strip_colors(str(_current_map.get('name', '')))), player.login)

    msg = _create_karma_message(player.login, False)
    if msg:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, msg), player.login)

    await _send_widget_combination(aseco, ['player_marker'], player)

    if _cfg.show_player_vote_public:
        logins: list[str] = []
        for pl in _players_all(aseco):
            _ensure_player_state(pl)
            if pl.login == player.login:
                continue
            if _cfg.require_finish > 0 and int(pl.data['ManiaKarma'].get('FinishedMapCount', 0) or 0) < _cfg.require_finish:
                continue
            if int(_karma['global']['players'].get(pl.login, {}).get('vote', 0) or 0) != 0:
                continue
            if _is_spectator(aseco, pl):
                continue
            logins.append(pl.login)
        if logins:
            pub = _cfg.msg_show_opinion.replace('{1}', strip_colors(getattr(player, 'nickname', player.login))).replace('{2}', _vote_label(vote))
            await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, pub), ','.join(logins))

    await aseco.release_event('onKarmaChange', {
        'Karma': _karma['global']['votes']['karma'],
        'Total': _karma['global']['votes']['total'],
        'FantasticCount': _karma['global']['votes']['fantastic']['count'],
        'FantasticPercent': _karma['global']['votes']['fantastic']['percent'],
        'BeautifulCount': _karma['global']['votes']['beautiful']['count'],
        'BeautifulPercent': _karma['global']['votes']['beautiful']['percent'],
        'GoodCount': _karma['global']['votes']['good']['count'],
        'GoodPercent': _karma['global']['votes']['good']['percent'],
        'BadCount': _karma['global']['votes']['bad']['count'],
        'BadPercent': _karma['global']['votes']['bad']['percent'],
        'PoorCount': _karma['global']['votes']['poor']['count'],
        'PoorPercent': _karma['global']['votes']['poor']['percent'],
        'WasteCount': _karma['global']['votes']['waste']['count'],
        'WastePercent': _karma['global']['votes']['waste']['percent'],
    })


# ---------------------------------------------------------------------------
# lifecycle / events
# ---------------------------------------------------------------------------

async def _load_config(aseco: Aseco) -> None:
    global _cfg
    base = pathlib.Path(getattr(aseco, '_base_dir', '.'))
    xml_path = base / 'mania_karma.xml'
    if not xml_path.exists():
        raise FileNotFoundError('mania_karma.xml not found')
    root = ET.parse(xml_path).getroot()
    _cfg = KarmaConfig()
    _cfg.api_auth_url = _x(root, 'urls/api_auth', _cfg.api_auth_url)
    _cfg.website = _x(root, 'urls/website', _cfg.website)
    _cfg.nation = _x(root, 'nation', _cfg.nation).upper()
    if not _cfg.api_auth_url:
        raise ValueError('<urls><api_auth> is empty in mania_karma.xml')
    if not _cfg.nation or _cfg.nation == 'YOUR_SERVER_NATION' or _cfg.nation not in ISO3166_ALPHA3:
        raise ValueError('<nation> must be a valid ISO-3166 alpha-3 code in mania_karma.xml')

    _cfg.connect_timeout = _xi(root, 'connect_timeout', _cfg.connect_timeout)
    _cfg.wait_timeout = _xi(root, 'wait_timeout', _cfg.wait_timeout)
    _cfg.keepalive_min_timeout = _xi(root, 'keepalive_min_timeout', _cfg.keepalive_min_timeout)
    _cfg.show_welcome = _xb(root, 'show_welcome', _cfg.show_welcome)
    _cfg.show_at_start = _xb(root, 'show_at_start', _cfg.show_at_start)
    _cfg.show_karma = _xb(root, 'show_karma', _cfg.show_karma)
    _cfg.show_votes = _xb(root, 'show_votes', _cfg.show_votes)
    _cfg.show_details = _xb(root, 'show_details', _cfg.show_details)
    _cfg.allow_public_vote = _xb(root, 'allow_public_vote', _cfg.allow_public_vote)
    _cfg.messages_in_window = _xb(root, 'messages_in_window', _cfg.messages_in_window)
    _cfg.show_player_vote_public = _xb(root, 'show_player_vote_public', _cfg.show_player_vote_public)
    _cfg.save_karma_also_local = _xb(root, 'save_karma_also_local', _cfg.save_karma_also_local)
    _cfg.sync_global_karma_local = _xb(root, 'sync_global_karma_local', _cfg.sync_global_karma_local)
    _cfg.score_mx_window = _xb(root, 'score_mx_window', _cfg.score_mx_window)
    _cfg.import_done = _xb(root, 'import_done', _cfg.import_done)
    _cfg.require_finish = _xi(root, 'require_finish', _cfg.require_finish)
    _cfg.remind_to_vote = _x(root, 'remind_to_vote', _cfg.remind_to_vote).upper()
    _cfg.reminder_window_display = _x(root, 'reminder_window/display', _cfg.reminder_window_display).upper()
    _cfg.uptime_check = _xb(root, 'uptodate_check', _cfg.uptime_check)
    _cfg.uptodate_info = _x(root, 'uptodate_info', _cfg.uptodate_info).upper()
    _cfg.karma_calculation_method = _x(root, 'karma_calculation_method', _cfg.karma_calculation_method).upper()
    _cfg.number_format = _x(root, 'number_format', _cfg.number_format).lower()

    _cfg.img_open_left = _x(root, 'images/widget_open_left', _cfg.img_open_left)
    _cfg.img_open_right = _x(root, 'images/widget_open_right', _cfg.img_open_right)
    _cfg.img_tmx_logo_normal = _x(root, 'images/tmx_logo_normal', _cfg.img_tmx_logo_normal)
    _cfg.img_tmx_logo_focus = _x(root, 'images/tmx_logo_focus', _cfg.img_tmx_logo_focus)
    _cfg.img_cup_gold = _x(root, 'images/cup_gold', _cfg.img_cup_gold)
    _cfg.img_cup_silver = _x(root, 'images/cup_silver', _cfg.img_cup_silver)
    _cfg.img_maniakarma_logo = _x(root, 'images/maniakarma_logo', _cfg.img_maniakarma_logo)
    _cfg.img_progress_indicator = _x(root, 'images/progress_indicator', _cfg.img_progress_indicator)

    _cfg.msg_welcome = _x(root, 'messages/welcome', _cfg.msg_welcome)
    _cfg.msg_uptodate_ok = _x(root, 'messages/uptodate_ok', _cfg.msg_uptodate_ok)
    _cfg.msg_uptodate_new = _x(root, 'messages/uptodate_new', _cfg.msg_uptodate_new)
    _cfg.msg_uptodate_failed = _x(root, 'messages/uptodate_failed', _cfg.msg_uptodate_failed)
    _cfg.msg_karma_message = _x(root, 'messages/karma_message', _cfg.msg_karma_message)
    _cfg.msg_karma_your_vote = _x(root, 'messages/karma_your_vote', _cfg.msg_karma_your_vote)
    _cfg.msg_karma_not_voted = _x(root, 'messages/karma_not_voted', _cfg.msg_karma_not_voted)
    _cfg.msg_karma_details = _x(root, 'messages/karma_details', _cfg.msg_karma_details)
    _cfg.msg_karma_done = _x(root, 'messages/karma_done', _cfg.msg_karma_done)
    _cfg.msg_karma_change = _x(root, 'messages/karma_change', _cfg.msg_karma_change)
    _cfg.msg_karma_voted = _x(root, 'messages/karma_voted', _cfg.msg_karma_voted)
    _cfg.msg_karma_remind = _x(root, 'messages/karma_remind', _cfg.msg_karma_remind)
    _cfg.msg_require_finish = _x(root, 'messages/karma_require_finish', _cfg.msg_require_finish)
    _cfg.msg_no_public = _x(root, 'messages/karma_no_public', _cfg.msg_no_public)
    _cfg.msg_karma_list_help = _x(root, 'messages/karma_list_help', _cfg.msg_karma_list_help)
    _cfg.msg_karma_help = _x(root, 'messages/karma_help', _cfg.msg_karma_help)
    _cfg.msg_reminder_at_score = _x(root, 'messages/karma_reminder_at_score', _cfg.msg_reminder_at_score)
    _cfg.msg_vote_singular = _x(root, 'messages/karma_vote_singular', _cfg.msg_vote_singular)
    _cfg.msg_vote_plural = _x(root, 'messages/karma_vote_plural', _cfg.msg_vote_plural)
    _cfg.msg_you_have_voted = _x(root, 'messages/karma_you_have_voted', _cfg.msg_you_have_voted)
    _cfg.msg_fantastic = _x(root, 'messages/karma_fantastic', _cfg.msg_fantastic)
    _cfg.msg_beautiful = _x(root, 'messages/karma_beautiful', _cfg.msg_beautiful)
    _cfg.msg_good = _x(root, 'messages/karma_good', _cfg.msg_good)
    _cfg.msg_undecided = _x(root, 'messages/karma_undecided', _cfg.msg_undecided)
    _cfg.msg_bad = _x(root, 'messages/karma_bad', _cfg.msg_bad)
    _cfg.msg_poor = _x(root, 'messages/karma_poor', _cfg.msg_poor)
    _cfg.msg_waste = _x(root, 'messages/karma_waste', _cfg.msg_waste)
    _cfg.msg_show_opinion = _x(root, 'messages/karma_show_opinion', _cfg.msg_show_opinion)
    _cfg.msg_show_undecided = _x(root, 'messages/karma_show_undecided', _cfg.msg_show_undecided)

    _cfg.bg_pos_default = _x(root, 'widget_styles/vote_buttons/positive/bgcolor_default', _cfg.bg_pos_default)
    _cfg.bg_pos_focus = _x(root, 'widget_styles/vote_buttons/positive/bgcolor_focus', _cfg.bg_pos_focus)
    _cfg.text_pos_color = _x(root, 'widget_styles/vote_buttons/positive/text_color', _cfg.text_pos_color)
    _cfg.bg_neg_default = _x(root, 'widget_styles/vote_buttons/negative/bgcolor_default', _cfg.bg_neg_default)
    _cfg.bg_neg_focus = _x(root, 'widget_styles/vote_buttons/negative/bgcolor_focus', _cfg.bg_neg_focus)
    _cfg.text_neg_color = _x(root, 'widget_styles/vote_buttons/negative/text_color', _cfg.text_neg_color)
    _cfg.bg_vote = _x(root, 'widget_styles/vote_buttons/votes/bgcolor_vote', _cfg.bg_vote)
    _cfg.bg_disabled = _x(root, 'widget_styles/vote_buttons/votes/bgcolor_disabled', _cfg.bg_disabled)

    _cfg.race_title = _x(root, 'widget_styles/race/title', _cfg.race_title)
    _cfg.race_icon_style = _x(root, 'widget_styles/race/icon_style', _cfg.race_icon_style)
    _cfg.race_icon_substyle = _x(root, 'widget_styles/race/icon_substyle', _cfg.race_icon_substyle)
    _cfg.race_bg_style = _x(root, 'widget_styles/race/background_style', _cfg.race_bg_style)
    _cfg.race_bg_substyle = _x(root, 'widget_styles/race/background_substyle', _cfg.race_bg_substyle)
    _cfg.race_title_style = _x(root, 'widget_styles/race/title_style', _cfg.race_title_style)
    _cfg.race_title_substyle = _x(root, 'widget_styles/race/title_substyle', _cfg.race_title_substyle)

    _cfg.score_title = _x(root, 'widget_styles/score/title', _cfg.score_title)
    _cfg.score_icon_style = _x(root, 'widget_styles/score/icon_style', _cfg.score_icon_style)
    _cfg.score_icon_substyle = _x(root, 'widget_styles/score/icon_substyle', _cfg.score_icon_substyle)
    _cfg.score_bg_style = _x(root, 'widget_styles/score/background_style', _cfg.score_bg_style)
    _cfg.score_bg_substyle = _x(root, 'widget_styles/score/background_substyle', _cfg.score_bg_substyle)
    _cfg.score_title_style = _x(root, 'widget_styles/score/title_style', _cfg.score_title_style)
    _cfg.score_title_substyle = _x(root, 'widget_styles/score/title_substyle', _cfg.score_title_substyle)

    _cfg.reminder_race = ReminderStateCfg(_xf(root, 'reminder_window/race/pos_x', _cfg.reminder_race.pos_x), _xf(root, 'reminder_window/race/pos_y', _cfg.reminder_race.pos_y))
    _cfg.reminder_score = ReminderStateCfg(_xf(root, 'reminder_window/score/pos_x', _cfg.reminder_score.pos_x), _xf(root, 'reminder_window/score/pos_y', _cfg.reminder_score.pos_y))

    _cfg.gamemodes = {}
    for mode, tag in GM_TAG.items():
        node = root.find(f'karma_widget/gamemode/{tag}')
        if node is not None:
            _cfg.gamemodes[mode] = WidgetGamemodeCfg(
                enabled=_xb(root, f'karma_widget/gamemode/{tag}/enabled', True),
                pos_x=_xf(root, f'karma_widget/gamemode/{tag}/pos_x', 49.2),
                pos_y=_xf(root, f'karma_widget/gamemode/{tag}/pos_y', 32.86 if mode != 4 else 17.5),
            )
    defaults = {0: (49.2, 32.86), 1: (49.2, 32.86), 2: (49.2, 32.86), 3: (49.2, 27.36), 4: (49.2, 17.5), 5: (49.2, 32.86), 7: (49.2, 32.86)}
    for mode, (x, y) in defaults.items():
        _cfg.gamemodes.setdefault(mode, WidgetGamemodeCfg(True, x, y))


async def _mk_onSync(aseco: Aseco, _data=None) -> None:
    global _karma, _current_map
    await _load_config(aseco)
    _cfg.current_state = _get_mode(aseco)
    _current_map = await _get_current_map_info(aseco)
    if not _karma or _startup_phase(aseco):
        _karma = _set_empty_karma(True)
        _karma['data'].update({
            'uid': _current_map.get('uid', ''),
            'id': _current_map.get('id', False),
            'name': _current_map.get('name', ''),
            'author': _current_map.get('author', ''),
            'env': _current_map.get('environment', ''),
            'tmx': (_current_map.get('mx') or {}).get('id', ''),
        })
    await _api_auth(aseco)
    await _load_local_karma()
    await _fetch_global_votes(aseco)
    _calculate_karma(['global', 'local'])

    if _api_connected:
        if _cfg.current_state == 7:
            await _send_widget_combination(aseco, ['skeleton_score', 'cups_values'], None)
        else:
            await _send_widget_combination(aseco, ['skeleton_race', 'cups_values'], None)
        for p in _players_all(aseco):
            await _send_widget_combination(aseco, ['player_marker'], p)
        await _send_connection_status(aseco, True, _cfg.current_state)


async def _mk_onEverySecond(aseco: Aseco, _data=None) -> None:
    if _retrytime > 0:
        now = int(asyncio.get_running_loop().time())
        if now >= _retrytime:
            await _api_auth(aseco)
            if _api_connected:
                await _send_connection_status(aseco, True, _cfg.current_state)


async def _mk_onShutdown(aseco: Aseco, _data=None) -> None:
    await _store_karma_votes(aseco)


async def _mk_onChat(aseco: Aseco, chat: list) -> None:
    if len(chat) < 3 or chat[0] == getattr(aseco.server, 'id', None):
        return
    text = str(chat[2]).strip()
    if text not in ('+++', '++', '+', '-', '--', '---'):
        return
    player = _get_player(aseco, str(chat[1]))
    if player is None:
        return
    if _cfg.allow_public_vote:
        await _handle_player_vote(aseco, player, {'+++': 3, '++': 2, '+': 1, '-': -1, '--': -2, '---': -3}[text])
    else:
        msg = _cfg.msg_no_public.replace('{1}', '/' + text)
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, msg), player.login)


async def chat_karma(aseco: Aseco, command: dict) -> None:
    author = command['author']
    login = author.login
    params = str(command.get('params') or '').strip().upper()
    if params in ('HELP', 'ABOUT'):
        await _show_help_window(aseco, author, _cfg.msg_karma_help)
        return
    if params == 'DETAILS':
        msg = _fmt_template(
            _cfg.msg_karma_details,
            _karma['global']['votes']['karma'],
            _karma['global']['votes']['fantastic']['percent'], _karma['global']['votes']['fantastic']['count'],
            _karma['global']['votes']['beautiful']['percent'], _karma['global']['votes']['beautiful']['count'],
            _karma['global']['votes']['good']['percent'], _karma['global']['votes']['good']['count'],
            _karma['global']['votes']['bad']['percent'], _karma['global']['votes']['bad']['count'],
            _karma['global']['votes']['poor']['percent'], _karma['global']['votes']['poor']['count'],
            _karma['global']['votes']['waste']['percent'], _karma['global']['votes']['waste']['count'],
        )
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, msg), login)
        return
    if params == 'RELOAD' and _is_master_admin(aseco, author):
        aseco.console('[plugin.mania_karma.py] MasterAdmin %s reloads the configuration.', login)
        await _mk_onSync(aseco)
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, '{#admin}Reloading the configuration "mania_karma.xml" now.'), login)
        return
    if params == 'EXPORT' and _is_master_admin(aseco, author):
        await _api_export_votes(aseco, author)
        return
    if params == 'UPTODATE' and _is_master_admin(aseco, author):
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, '{#server}> {#karma}Up-to-date check is not implemented for this PyXaseco port.'), login)
        return
    if params == '' or params == 'LOTTERY':
        msg = _create_karma_message(login, True)
        if msg:
            await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, msg), login)
        return


async def chat_plusplusplus(aseco: Aseco, command: dict):
    await _handle_player_vote(aseco, command['author'], 3)


async def chat_plusplus(aseco: Aseco, command: dict):
    await _handle_player_vote(aseco, command['author'], 2)


async def chat_plus(aseco: Aseco, command: dict):
    await _handle_player_vote(aseco, command['author'], 1)


async def chat_dash(aseco: Aseco, command: dict):
    await _handle_player_vote(aseco, command['author'], -1)


async def chat_dashdash(aseco: Aseco, command: dict):
    await _handle_player_vote(aseco, command['author'], -2)


async def chat_dashdashdash(aseco: Aseco, command: dict):
    await _handle_player_vote(aseco, command['author'], -3)


async def _mk_onKarmaChange(aseco: Aseco, _unused=None) -> None:
    await _send_widget_combination(aseco, ['cups_values'], None)


async def _mk_onPlayerConnect(aseco: Aseco, player: Any) -> None:
    global _current_map
    _ensure_player_state(player)
    if _cfg.show_welcome and _cfg.msg_welcome:
        msg = _cfg.msg_welcome.replace('{1}', f'http://{_cfg.website}/').replace('{2}', _cfg.website)
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, msg), player.login)
    if _is_master_admin(aseco, player) and not _cfg.import_done:
        warn = '{#server}> {#emotic}#################################################\n{#server}> {#emotic}Please start the export of your current local votes with the command "/karma export". Thanks!\n{#server}> {#emotic}#################################################'
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, warn), player.login)

    if not _current_map:
        _current_map = await _get_current_map_info(aseco)
    if _cfg.require_finish > 0:
        await _seed_finish_counts(aseco, [player])

    if not _startup_phase(aseco):
        _karma['global']['players'].setdefault(player.login, {'vote': 0, 'previous': 0})
        if player.login not in _karma['local']['players']:
            local_one = await _get_local_votes(_current_map.get('id'), player.login)
            if local_one:
                _karma['local']['players'].update(local_one)
                _rebuild_counts_from_players('local')
        await _fetch_global_votes(aseco, player.login)
        if _cfg.sync_global_karma_local:
            await _sync_global_and_local('global', False)
        if _cfg.current_state == 7:
            await _send_widget_combination(aseco, ['skeleton_score', 'cups_values', 'player_marker'], player)
        else:
            await _send_widget_combination(aseco, ['skeleton_race', 'cups_values', 'player_marker'], player)


async def _mk_onPlayerDisconnect(aseco: Aseco, player: Any) -> None:

    _ensure_player_state(player)


async def _mk_onPlayerFinish(aseco: Aseco, finish_item: Any) -> None:
    player = getattr(finish_item, 'player', None)
    if player is None:
        return
    _ensure_player_state(player)
    if _cfg.require_finish > 0:
        player.data['ManiaKarma']['FinishedMapCount'] = int(player.data['ManiaKarma'].get('FinishedMapCount', 0) or 0) + 1
        await _send_widget_combination(aseco, ['player_marker'], player)

    if _cfg.remind_to_vote in ('FINISHED', 'ALWAYS'):
        voted = int(_karma['global']['players'].get(player.login, {}).get('vote', 0) or 0)
        if voted == 0 and (_cfg.require_finish <= 0 or int(player.data['ManiaKarma']['FinishedMapCount']) >= _cfg.require_finish):
            if _cfg.reminder_window_display in ('FINISHED', 'ALWAYS'):
                await _show_reminder_window(aseco, [player.login])
                player.data['ManiaKarma']['ReminderWindow'] = True
            else:
                await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, _cfg.msg_karma_remind), player.login)


async def _mk_onPlayerManialinkPageAnswer(aseco: Aseco, answer: list) -> None:
    if len(answer) < 3 or int(answer[2] or 0) == 0:
        return
    player = _get_player(aseco, str(answer[1]))
    if player is None:
        return
    action = int(answer[2])
    if action == ACT_CLOSE:
        await _send_window(aseco, player.login, f'<manialink id="{ML_WINDOWS}"></manialink>')
        _window_state.pop(player.login, None)
    elif action == ACT_OPEN_HELP:
        await _show_help_window(aseco, player, _cfg.msg_karma_help)
    elif action == ACT_OPEN_DETAIL:
        await _show_details_window(aseco, player.login)
    elif action == ACT_OPEN_WHO:
        await _show_who_window(aseco, player.login, 0)
    elif action == ACT_VOTE_P3:
        await _handle_player_vote(aseco, player, 3)
    elif action == ACT_VOTE_P2:
        await _handle_player_vote(aseco, player, 2)
    elif action == ACT_VOTE_P1:
        await _handle_player_vote(aseco, player, 1)
    elif action == ACT_VOTE_UNDECIDED:
        await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, _cfg.msg_show_undecided.replace('{1}', strip_colors(getattr(player, 'nickname', player.login)))), player.login)
    elif action == ACT_VOTE_N1:
        await _handle_player_vote(aseco, player, -1)
    elif action == ACT_VOTE_N2:
        await _handle_player_vote(aseco, player, -2)
    elif action == ACT_VOTE_N3:
        await _handle_player_vote(aseco, player, -3)
    elif action == ACT_VOTE_LOCKED:
        await _handle_player_vote(aseco, player, 0)
    elif action == ACT_REFRESH:
        await _fetch_global_votes(aseco)
        state = _window_state.get(player.login, ('details', 0))
        if state[0] == 'who':
            await _show_who_window(aseco, player.login, state[1])
        elif state[0] == 'help':
            await _show_help_window(aseco, player, _cfg.msg_karma_help)
        else:
            await _show_details_window(aseco, player.login)
    elif action == ACT_PAGE_PREV:
        kind, page = _window_state.get(player.login, ('who', 0))
        await _show_who_window(aseco, player.login, page - 1)
    elif action == ACT_PAGE_NEXT:
        kind, page = _window_state.get(player.login, ('who', 0))
        await _show_who_window(aseco, player.login, page + 1)


async def _mk_onNewChallenge(aseco: Aseco, map_obj: Any) -> None:
    _cfg.current_state = _get_mode(aseco)
    await _close_reminder_window(aseco, None)
    await _send_widget_combination(aseco, ['hide_all'], None)
    await _store_karma_votes(aseco)
    if _cfg.require_finish > 0:
        for p in _players_all(aseco):
            _ensure_player_state(p)
            p.data['ManiaKarma']['FinishedMapCount'] = 0


async def _mk_onNewChallenge2(aseco: Aseco, map_obj: Any) -> None:
    global _current_map, _karma
    _current_map = await _get_current_map_info(aseco)
    _karma = _set_empty_karma(True)
    _karma['data'].update({
        'uid': getattr(map_obj, 'uid', _current_map.get('uid', '')) or _current_map.get('uid', ''),
        'id': getattr(map_obj, 'id', _current_map.get('id', False)) or _current_map.get('id', False),
        'name': getattr(map_obj, 'name', _current_map.get('name', '')) or _current_map.get('name', ''),
        'author': getattr(map_obj, 'author', _current_map.get('author', '')) or _current_map.get('author', ''),
        'env': getattr(map_obj, 'environment', _current_map.get('environment', '')) or _current_map.get('environment', ''),
        'tmx': getattr(getattr(map_obj, 'mx', None), 'id', '') or (_current_map.get('mx') or {}).get('id', ''),
    })
    if not _players_all(aseco):
        await _load_local_karma()
        return
    await _load_local_karma()
    if _cfg.require_finish > 0:
        await _seed_finish_counts(aseco)
    await _fetch_global_votes(aseco)
    if _cfg.sync_global_karma_local:
        await _sync_global_and_local('global', False)
    _cfg.current_state = _get_mode(aseco)
    await _send_loading_indicator(aseco, True, _cfg.current_state)
    await _send_widget_combination(aseco, ['skeleton_race', 'cups_values'], None)
    for p in _players_all(aseco):
        await _send_widget_combination(aseco, ['player_marker'], p)
    await _send_loading_indicator(aseco, False, _cfg.current_state)  # hide spinner once votes are loaded
    if _retrytime > 0:
        await _send_connection_status(aseco, False, _cfg.current_state)
    if _cfg.show_at_start:
        await _send_map_karma_message(aseco, None)


async def _mk_onRestartChallenge2(aseco: Aseco, _map: Any) -> None:
    await _close_reminder_window(aseco, None)
    _cfg.current_state = _get_mode(aseco)
    await _send_widget_combination(aseco, ['skeleton_race', 'cups_values'], None)
    for p in _players_all(aseco):
        await _send_widget_combination(aseco, ['player_marker'], p)


async def _mk_onEndRace1(aseco: Aseco, _data: Any) -> None:
    if not _players_all(aseco):
        return
    _cfg.current_state = 7
    if _retrytime > 0:
        await _send_connection_status(aseco, False, _cfg.current_state)
    await _send_widget_combination(aseco, ['hide_window', 'skeleton_score', 'cups_values'], None)
    for p in _players_all(aseco):
        await _send_widget_combination(aseco, ['player_marker'], p)

    if _cfg.remind_to_vote in ('SCORE', 'ALWAYS'):
        remind: list[str] = []
        for p in _players_all(aseco):
            _ensure_player_state(p)
            if _cfg.require_finish > 0 and int(p.data['ManiaKarma'].get('FinishedMapCount', 0) or 0) < _cfg.require_finish:
                continue
            if int(_karma['global']['players'].get(p.login, {}).get('vote', 0) or 0) == 0:
                remind.append(p.login)
                p.data['ManiaKarma']['ReminderWindow'] = True
            elif _cfg.score_mx_window:
                await _show_mx_window(aseco, p)
        if remind:
            if _cfg.reminder_window_display in ('SCORE', 'ALWAYS'):
                await _show_reminder_window(aseco, remind)
            else:
                await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', _fmt_message(aseco, _cfg.msg_karma_remind), ','.join(remind))
    elif _cfg.score_mx_window:
        for p in _players_all(aseco):
            if _is_spectator(aseco, p):
                continue
            if int(_karma['global']['players'].get(p.login, {}).get('vote', 0) or 0) != 0:
                await _show_mx_window(aseco, p)


# ---------------------------------------------------------------------------
# export helper
# ---------------------------------------------------------------------------

async def _export_votes_csv(aseco: Aseco) -> str:
    rows = []
    try:
        rows = await _db_fetchall(
            "SELECT c.Uid, c.Name, p.Login, p.NickName, k.Score FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId LEFT JOIN challenges c ON c.Id=k.ChallengeId ORDER BY c.Name ASC, p.Login ASC"
        )
    except Exception:
        try:
            rows = await _db_fetchall(
                "SELECT k.uid, '', p.Login, p.NickName, k.vote FROM rs_karma k LEFT JOIN players p ON p.Id=k.PlayerId ORDER BY k.uid ASC, p.Login ASC"
            )
        except Exception:
            rows = []
    out = ['uid,map,login,nickname,vote']
    for row in rows:
        out.append(','.join('"' + str(x or '').replace('"', '""') + '"' for x in row))
    return '\n'.join(out) + '\n'


async def _build_export_payload(aseco: Aseco) -> tuple[str, int]:
    server_login = getattr(aseco.server, "serverlogin", "") or getattr(aseco.server, "login", "") or ""
    rows = []
    try:
        rows = await _db_fetchall(
            "SELECT c.Uid, c.Name, c.Author, c.Environment, p.Login, k.Score "
            "FROM rs_karma k "
            "LEFT JOIN challenges c ON c.Id=k.ChallengeId "
            "LEFT JOIN players p ON p.Id=k.PlayerId "
            "ORDER BY c.Uid ASC"
        )
    except Exception:
        try:
            rows = await _db_fetchall(
                "SELECT k.uid, '', '', '', p.Login, k.vote "
                "FROM rs_karma k "
                "LEFT JOIN players p ON p.Id=k.PlayerId "
                "ORDER BY k.uid ASC"
            )
        except Exception:
            rows = []

    lines: list[str] = []
    count = 0
    for row in rows:
        uid = str(row[0] or '')
        if not uid:
            continue
        count += 1
        lines.append(
            "\t".join([
                uid,
                str(row[1] or ''),
                str(row[2] or ''),
                str(row[3] or ''),
                server_login,
                _api_authcode,
                str(_cfg.nation or ''),
                str(row[4] or ''),
                str(int(row[5] or 0)),
            ])
        )

    raw = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii"), count


async def _api_export_votes(aseco: Aseco, player: Any) -> None:
    if _cfg.import_done:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            _fmt_message(aseco, '{#server}>> {#admin}Export of local votes already done, skipping...'),
            player.login,
        )
        return

    if not _api_connected or not _cfg.api_url or not _api_authcode:
        await _api_auth(aseco)
        if not _api_connected or not _cfg.api_url or not _api_authcode:
            await aseco.client.query_ignore_result(
                'ChatSendServerMessageToLogin',
                _fmt_message(aseco, '{#server}>> {#error}Export failed because ManiaKarma is not connected.'),
                player.login,
            )
            return

    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        _fmt_message(aseco, '{#server}>> {#admin}Collecting players with their votes on Maps...'),
        player.login,
    )
    payload, count = await _build_export_payload(aseco)
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        _fmt_message(aseco, f'{{#server}}>> {{#admin}}Found {count} votes in database.'),
        player.login,
    )
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        _fmt_message(aseco, '{#server}>> {#admin}Compressing collected data...'),
        player.login,
    )
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        _fmt_message(aseco, '{#server}>> {#admin}Encoding data...'),
        player.login,
    )
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        _fmt_message(aseco, f'{{#server}}>> {{#admin}}Sending now the export with size of {len(payload)} bytes...'),
        player.login,
    )

    login = getattr(aseco.server, "serverlogin", "") or getattr(aseco.server, "login", "") or ""
    url = (
        f"{_cfg.api_url}?Action=Import"
        f"&login={urllib.parse.quote(login)}"
        f"&authcode={urllib.parse.quote(_api_authcode)}"
        f"&nation={urllib.parse.quote(str(_cfg.nation or ''))}"
    )
    status, _body = await _api_post(url, payload, _cfg.wait_timeout)
    if status == 200:
        _cfg.import_done = True
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            _fmt_message(aseco, '{#server}>> {#admin}Export done. Thanks for supporting mania-karma.com!'),
            player.login,
        )
    elif status == 406:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            _fmt_message(aseco, '{#server}>> {#error}Export rejected! Please check your <login> and <nation> in config file "mania_karma.xml"!'),
            player.login,
        )
    elif status == 409:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            _fmt_message(aseco, '{#server}>> {#error}Export rejected! Export was already done, allowed only one time!'),
            player.login,
        )
    else:
        await aseco.client.query_ignore_result(
            'ChatSendServerMessageToLogin',
            _fmt_message(aseco, f'{{#server}}>> {{#error}}Connection failed with {status} for url [{url}]'),
            player.login,
        )


async def _store_karma_votes(aseco: Aseco) -> None:
    new_votes = dict(_karma.get('new', {}).get('players', {}) or {})
    if not new_votes:
        return
    if _retrytime > 0:
        try:
            now = int(asyncio.get_running_loop().time())
            if now >= _retrytime:
                await _api_auth(aseco)
        except Exception:
            pass
    if _retrytime == 0:
        await _api_vote_multisend(aseco, new_votes)
    if _cfg.save_karma_also_local:
        await _save_local_votes(new_votes)
    _karma['new']['players'].clear()


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def register(aseco: Aseco) -> None:
    global _karma
    _karma = _set_empty_karma(True)
    aseco.register_event('onSync', _mk_onSync)
    aseco.register_event('onEverySecond', _mk_onEverySecond)
    aseco.register_event('onShutdown', _mk_onShutdown)
    aseco.register_event('onChat', _mk_onChat)
    aseco.register_event('onKarmaChange', _mk_onKarmaChange)
    aseco.register_event('onPlayerConnect', _mk_onPlayerConnect)
    aseco.register_event('onPlayerDisconnect', _mk_onPlayerDisconnect)
    aseco.register_event('onPlayerFinish1', _mk_onPlayerFinish)
    aseco.register_event('onPlayerManialinkPageAnswer', _mk_onPlayerManialinkPageAnswer)
    aseco.register_event('onNewChallenge', _mk_onNewChallenge)
    aseco.register_event('onNewChallenge2', _mk_onNewChallenge2)
    aseco.register_event('onRestartChallenge2', _mk_onRestartChallenge2)
    aseco.register_event('onEndRace1', _mk_onEndRace1)

    aseco.add_chat_command('karma', 'Shows karma for the current Map (see: /karma help)')
    aseco.add_chat_command('+++', 'Set "Fantastic" karma for the current Map')
    aseco.add_chat_command('++', 'Set "Beautiful" karma for the current Map')
    aseco.add_chat_command('+', 'Set "Good" karma for the current Map')
    aseco.add_chat_command('-', 'Set "Bad" karma for the current Map')
    aseco.add_chat_command('--', 'Set "Poor" karma for the current Map')
    aseco.add_chat_command('---', 'Set "Waste" karma for the current Map')

    aseco.register_event('onChat_karma', chat_karma)
    aseco.register_event('onChat_+++', chat_plusplusplus)
    aseco.register_event('onChat_++', chat_plusplus)
    aseco.register_event('onChat_+', chat_plus)
    aseco.register_event('onChat_-', chat_dash)
    aseco.register_event('onChat_--', chat_dashdash)
    aseco.register_event('onChat_---', chat_dashdashdash)
