"""
plugin_panels.py — port of plugins/plugin.panels.php

Covers:
- loading default panel templates from /panels
- loading player-selected panel templates from DB
- /donpanel, /recpanel, /votepanel
- /admin panel ...
- panel selection through manialink actions
- display helpers for admin/donate/records/vote/stats panels

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink, display_manialink_multi, format_time

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

PANEL_ID_ADMIN = 3
PANEL_ID_RECORDS = 4
PANEL_ID_VOTE = 5
PANEL_ID_DONATE = 6
PANEL_ID_STATS = 9

ACTION_ADMIN_BASE = -7       # -8.. etc
ACTION_RECPANEL_BASE = -49   # -50.. etc
ACTION_VOTEPANEL_BASE = 36   # 37.. etc
ACTION_DONPANEL_BASE = 7200  # 7201.. etc

# Functional panel action ids
# Records panel templates use the original XAseco ids 7..10.
# Keep the higher legacy aliases too in case any custom XML still uses them.
ACTION_REC_PB    = 7
ACTION_REC_LOCAL = 8
ACTION_REC_DEDI  = 9
ACTION_REC_TMX   = 10
ACTION_REC_LOCAL_ALT = 91001
ACTION_REC_DEDI_ALT  = 91002

ACTION_DONATE_20   = 30
ACTION_DONATE_50   = 31
ACTION_DONATE_100  = 32
ACTION_DONATE_200  = 33
ACTION_DONATE_500  = 34
ACTION_DONATE_1000 = 35
ACTION_DONATE_2000 = 36

ACTION_ADMIN_RESTART = 21
ACTION_ADMIN_ENDROUND = 22
ACTION_ADMIN_SKIP = 23
ACTION_ADMIN_REPLAY = 24
ACTION_ADMIN_PASS = 25
ACTION_ADMIN_CANCEL = 26
ACTION_ADMIN_PLAYERS_LIVE = 27
ACTION_VOTE_YES = 18
ACTION_VOTE_NO = 19
ACTION_JUKEBOX_CLEAR = 20

_default_panels: dict[str, str] = {
    "admin": "",
    "donate": "",
    "records": "",
    "vote": "",
}
_stats_panel_xml: str = ""

_records_cache = {
    "tmx": "",
    "local": "",
    "dedi": "",
}

_last_records_snapshot = ("", "", "")

def register(aseco: "Aseco"):
    aseco.register_event("onStartup", panels_default)
    aseco.register_event("onSync", init_statspanel)
    aseco.register_event("onEndRace", update_allstatspanels)

    aseco.register_event("onNewChallenge2", update_allrecpanels)
    aseco.register_event("onNewChallenge2", display_alldonpanels)
    aseco.register_event("onNewChallenge2", _redisplay_all_admin_panels)
    aseco.register_event("onNewChallenge2", _update_allstatspanels_on_challenge)

    aseco.register_event("onPlayerConnect", init_playerpanels)
    aseco.register_event("onPlayerConnect", load_donpanel)
    aseco.register_event("onPlayerConnect", load_recpanel)
    aseco.register_event("onPlayerFinish", finish_recpanel)
    aseco.register_event("onPlayerManialinkPageAnswer", event_panels)
    aseco.register_event("onLocalRecord", update_allrecpanels)
    aseco.register_event("onDedimaniaRecord", update_allrecpanels)

    aseco.add_chat_command("donpanel", "Selects donate panel (see: /donpanel help)")
    aseco.add_chat_command("recpanel", "Selects records panel (see: /recpanel help)")
    aseco.add_chat_command("votepanel", "Selects vote panel (see: /votepanel help)")

    aseco.register_event("onChat_donpanel", chat_donpanel)
    aseco.register_event("onChat_recpanel", chat_recpanel)
    aseco.register_event("onChat_votepanel", chat_votepanel)


def _base_dir(aseco: "Aseco") -> Path:
    return Path(getattr(aseco, "_base_dir", "."))


def _panels_dir(aseco: "Aseco") -> Path:
    return _base_dir(aseco) / "panels"


def _server_is_tmf(aseco: "Aseco") -> bool:
    try:
        return aseco.server.get_game() == "TMF"
    except Exception:
        return getattr(aseco.server, "game", "") == "TMF"


async def _send_login(aseco: "Aseco", login: str, msg: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors(msg),
        login,
    )


async def _send_panel_xml(aseco: "Aseco", login: str, xml: str, timeout: int = 0, autoclose: bool = False):
    await aseco.client.query_ignore_result(
        "SendDisplayManialinkPageToLogin",
        login,
        aseco.format_colors(xml),
        timeout,
        autoclose,
    )


def _empty_panel_xml(panel_id: int) -> str:
    return f'<manialink id="{panel_id}"></manialink>'


def _read_panel_file(aseco: "Aseco", panel_name: str) -> str:
    panel_file = _panels_dir(aseco) / f"{panel_name}.xml"
    return panel_file.read_text(encoding="utf-8", errors="ignore")


def _player_panel(player: "Player", key: str) -> str:
    if not hasattr(player, "panels") or not isinstance(player.panels, dict):
        player.panels = {}
    return player.panels.get(key, "")


def _set_player_panel(player: "Player", key: str, value: str):
    if not hasattr(player, "panels") or not isinstance(player.panels, dict):
        player.panels = {}
    player.panels[key] = value


def _parse_panels_db_value(raw) -> dict[str, str]:
    """
    Supports either:
      - dict: {"admin": "...", "donate": "...", "records": "...", "vote": "..."}
      - slash string: "AdminBelowChat/DonateBelowCPList/RecordsRightBottom/VoteBelowChat"

    DB order is:
      admin / donate / records / vote
    """
    if isinstance(raw, dict):
        return {
            "admin": (raw.get("admin") or "").strip(),
            "donate": (raw.get("donate") or "").strip(),
            "records": (raw.get("records") or "").strip(),
            "vote": (raw.get("vote") or "").strip(),
        }

    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split("/")]
        while len(parts) < 4:
            parts.append("")
        return {
            "admin": parts[0],
            "donate": parts[1],
            "records": parts[2],
            "vote": parts[3],
        }

    return {
        "admin": "",
        "donate": "",
        "records": "",
        "vote": "",
    }


async def _get_player_panel_names_from_db(aseco: "Aseco", login: str) -> dict[str, str]:
    """
    Reads players_extra.panels through plugin_localdatabase and normalizes it.
    """
    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_get_panels
        raw = await ldb_get_panels(aseco, login)
        return _parse_panels_db_value(raw)
    except Exception as e:
        logger.debug("[Panels] Could not load panel names from DB for %s: %s", login, e)
        return {
            "admin": "",
            "donate": "",
            "records": "",
            "vote": "",
        }


async def _persist_all_panel_choices(aseco: "Aseco", login: str, panel_names: dict[str, str]):
    """
    Persists the whole slash-separated panel string into players_extra.panels:
      admin/donate/records/vote
    """
    panel_names = {
        "admin": (panel_names.get("admin") or "").strip(),
        "donate": (panel_names.get("donate") or "").strip(),
        "records": (panel_names.get("records") or "").strip(),
        "vote": (panel_names.get("vote") or "").strip(),
    }

    joined = "/".join([
        panel_names["admin"],
        panel_names["donate"],
        panel_names["records"],
        panel_names["vote"],
    ])

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
                await cur.execute(
                    """
                    INSERT INTO players_extra (playerID, panels)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE panels = VALUES(panels)
                    """,
                    (pid, joined)
                )
    except Exception as e:
        logger.debug("[Panels] Could not persist merged panels for %s: %s", login, e)


def _list_templates(aseco: "Aseco", prefix: str, max_count: int) -> list[str]:
    result = []
    pdir = _panels_dir(aseco)
    if not pdir.exists():
        return result

    plen = len(prefix)
    for file in sorted(pdir.glob(f"{prefix}*.xml")):
        name = file.stem
        if name.lower().startswith(prefix.lower()):
            result.append(name[plen:])
    return result[:max_count]


async def _redisplay_all_admin_panels(aseco: "Aseco", _data=None):
    """Redisplay admin panel for all admins on new challenge (PHP parity)."""
    for player in aseco.server.players.all():
        try:
            if aseco.is_any_admin(player) and _player_panel(player, "admin"):
                await display_admpanel(aseco, player)
        except Exception as e:
            logger.debug("[Panels] redisplay admin for %s: %s", player.login, e)


async def _update_allstatspanels_on_challenge(aseco: "Aseco", _data=None):
    """Refresh stats panel on new challenge as well as end of race (PHP parity)."""
    await update_allstatspanels(aseco, _data)


async def panels_default(aseco: "Aseco", _param=None):
    global _default_panels

    if not _server_is_tmf(aseco):
        return

    mapping = {
        "admin": getattr(aseco.settings, "admin_panel", ""),
        "donate": getattr(aseco.settings, "donate_panel", ""),
        "records": getattr(aseco.settings, "records_panel", ""),
        "vote": getattr(aseco.settings, "vote_panel", ""),
    }

    for key, panel_name in mapping.items():
        if not panel_name:
            _default_panels[key] = ""
            continue
        try:
            aseco.console(f"[Panels] Load default {key} panel [{{1}}]", f"panels/{panel_name}.xml")
            _default_panels[key] = _read_panel_file(aseco, panel_name)
        except Exception as e:
            logger.warning("[Panels] Could not load default %s panel %s: %s", key, panel_name, e)
            _default_panels[key] = ""


async def init_statspanel(aseco: "Aseco", _param=None):
    global _stats_panel_xml

    if not _server_is_tmf(aseco):
        return
    if not getattr(aseco.settings, "sb_stats_panels", False):
        return

    panel_name = "StatsUnited" if getattr(aseco.server, "rights", False) else "StatsNations"
    try:
        aseco.console("[Panels] Load stats panel [{1}]", f"panels/{panel_name}.xml")
        _stats_panel_xml = _read_panel_file(aseco, panel_name)
    except Exception as e:
        logger.warning("[Panels] Could not load stats panel %s: %s", panel_name, e)
        _stats_panel_xml = ""

def _panel_name_from_db_value(value: str) -> str:
    return (value or "").strip()

async def init_playerpanels(aseco: "Aseco", player: "Player"):
    panel_names = await _get_player_panel_names_from_db(aseco, player.login)

    logger.debug("[Panels] DB panel names for %s: %r", player.login, panel_names)

    for key in ("admin", "donate", "records", "vote"):
        panel_name = (panel_names.get(key) or "").strip()
        if not panel_name:
            _set_player_panel(player, key, "")
            continue

        try:
            _set_player_panel(player, key, _read_panel_file(aseco, panel_name))
        except Exception as e:
            logger.warning(
                "[Panels] Could not load player %s panel %s for %s: %s",
                key, panel_name, player.login, e
            )
            _set_player_panel(player, key, "")

    # Draw admin panel here too, after the XML is definitely loaded.
    try:
        if aseco.is_any_admin(player) and _player_panel(player, "admin"):
            logger.debug("[Panels] Drawing admin panel for %s after DB load", player.login)
            await display_admpanel(aseco, player)
    except Exception as e:
        logger.debug("[Panels] Could not draw admin panel for %s: %s", player.login, e)


async def update_allstatspanels(aseco: "Aseco", _data=None):
    if not _server_is_tmf(aseco) or not getattr(aseco.settings, "sb_stats_panels", False):
        return
    if not _stats_panel_xml:
        return

    rec_counts = await _get_online_record_counts(aseco)

    for pl in aseco.server.players.all():
        rank, avg = await _get_rank_and_avg(pl.login)
        recs = rec_counts.get(pl.login, 0)
        wins = pl.get_wins() if hasattr(pl, "get_wins") else getattr(pl, "wins", 0)
        play = _format_time_h((pl.get_time_online() if hasattr(pl, "get_time_online") else 0) * 1000)
        dons = await _get_donations(aseco, pl.login) if getattr(pl, "rights", False) else "N/A"
        await display_statspanel(aseco, pl, rank, avg, recs, wins, play, dons)


async def _get_online_record_counts(aseco: "Aseco") -> dict[str, int]:
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        if not pool:
            return {}

        ids = [str(pl.id) for pl in aseco.server.players.all() if getattr(pl, "id", 0)]
        if not ids:
            return {}

        query = (
            f"SELECT p.Login, COUNT(p.Id) AS Count "
            f"FROM players p, records r "
            f"WHERE p.Id=r.PlayerId AND p.Id IN ({','.join(ids)}) "
            f"GROUP BY p.Id"
        )

        out: dict[str, int] = {}
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query)
                for login, count in await cur.fetchall():
                    out[login] = int(count or 0)
        return out
    except Exception as e:
        logger.debug("[Panels] online record counts failed: %s", e)
        return {}


async def _get_rank_and_avg(login: str) -> tuple[str, str]:
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool, get_player_id

        pool = await get_pool()
        if not pool:
            return "-", "-"

        pid = await get_player_id(login)
        if not pid:
            return "-", "-"

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT avg FROM rs_rank WHERE playerID=%s", (pid,))
                row = await cur.fetchone()
                if not row:
                    return "-", "-"
                avg_val = float(row[0] or 0)
                await cur.execute("SELECT COUNT(*) FROM rs_rank WHERE avg < %s", (avg_val,))
                better = await cur.fetchone()
                rank = str(int((better[0] if better else 0) + 1))
                avg = f"{avg_val / 10000.0:.1f}"
                return rank, avg
    except Exception as e:
        logger.debug("[Panels] rank/avg failed for %s: %s", login, e)
    return "-", "-"


async def _get_donations(aseco: "Aseco", login: str) -> int:
    try:
        from pyxaseco.plugins.plugin_localdatabase import ldb_get_donations
        return await ldb_get_donations(aseco, login)
    except Exception:
        return 0


def _format_time_h(ms: int) -> str:
    total_sec = max(0, int(ms // 1000))
    hours = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours}:{mins:02d}:{secs:02d}"


async def display_statspanel(aseco: "Aseco", player: "Player", rank, avg, recs, wins, play, dons):
    if not _stats_panel_xml:
        return
    xml = (
        _stats_panel_xml
        .replace("%RANK%", str(rank))
        .replace("%AVG%", str(avg))
        .replace("%RECS%", str(recs))
        .replace("%WINS%", str(wins))
        .replace("%PLAY%", str(play))
        .replace("%DONS%", str(dons))
    )
    await _send_panel_xml(aseco, player.login, xml, 0, False)

async def admin_panel(aseco: "Aseco", command: dict):
    command = dict(command)
    command["params"] = (command.get("params") or "").strip()

    await _handle_panel_command(
        aseco,
        command,
        panel_type="admin",
        prefix="Admin",
        title="admin",
        max_count=40,
        action_base=ACTION_ADMIN_BASE,
        require_rights=False,
        default_setting=getattr(aseco.settings, "admin_panel", ""),
        admin_only=True,
    )

async def display_admpanel(aseco: "Aseco", player: "Player"):
    xml = _player_panel(player, "admin")
    if not xml:
        logger.debug("[Panels] No admin panel XML loaded for %s", player.login)
        return

    logger.debug("[Panels] Sending admin panel to %s", player.login)
    await _send_panel_xml(aseco, player.login, xml, 0, False)

async def display_donpanel(aseco: "Aseco", player: "Player", coppers: list[int]):
    xml = _player_panel(player, "donate")
    if not xml:
        return
    for i in range(1, 8):
        xml = xml.replace(f"%COP{i}%", str(coppers[i - 1]))
    await _send_panel_xml(aseco, player.login, xml, 0, False)

async def donpanel_off(aseco: "Aseco", login: str):
    await _send_panel_xml(aseco, login, _empty_panel_xml(PANEL_ID_DONATE), 0, False)

async def display_recpanel(aseco: "Aseco", player: "Player", pb: str):
    xml = _player_panel(player, "records")
    if not xml:
        return
    logger.debug(
        "[Panels] recpanel values for %s -> PB=%r LCL=%r DED=%r TMX=%r",
        player.login,
        pb,
        _records_cache["local"],
        _records_cache["dedi"],
        _records_cache["tmx"],
    )
    xml = (
        xml
        .replace("%PB%", pb)
        .replace("%TMX%", _records_cache["tmx"])
        .replace("%LCL%", _records_cache["local"])
        .replace("%DED%", _records_cache["dedi"])
    )
    await _send_panel_xml(aseco, player.login, xml, 0, False)

async def recpanel_off(aseco: "Aseco", login: str):
    await _send_panel_xml(aseco, login, _empty_panel_xml(PANEL_ID_RECORDS), 0, False)

async def display_votepanel(aseco: "Aseco", player: "Player", yesstr: str, nostr: str, timeout: int):
    xml = _player_panel(player, "vote")
    if not xml:
        return
    xml = xml.replace("%YES%", yesstr).replace("%NO%", nostr)
    await _send_panel_xml(aseco, player.login, xml, timeout, True)

async def votepanel_off(aseco: "Aseco", login: str):
    await _send_panel_xml(aseco, login, _empty_panel_xml(PANEL_ID_VOTE), 0, False)

async def allvotepanels_off(aseco: "Aseco"):
    xml = _empty_panel_xml(PANEL_ID_VOTE)
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)

def _is_spectator(player) -> bool:
    """Canonical spec check via spectatorstatus % 10."""
    raw = getattr(player, 'spectatorstatus', None)
    if raw is not None:
        try:
            return (int(raw) % 10) != 0
        except (TypeError, ValueError):
            pass
    return bool(getattr(player, 'isspectator', False))


async def allvotepanels_on(aseco: "Aseco", starter_login: str, ycolor: str):
    """
    Shows the vote panel to all eligible players.
    Spectator state read via spectatorstatus % 10.
    """
    try:
        from pyxaseco.plugins.plugin_rasp_votes import auto_vote_starter, allow_spec_voting
    except Exception:
        auto_vote_starter = True
        allow_spec_voting = False

    for player in aseco.server.players.all():
        if player.login == starter_login and auto_vote_starter:
            continue
        if _is_spectator(player):
            if allow_spec_voting or aseco.is_any_admin(player):
                await display_votepanel(aseco, player,
                                       ycolor + 'Yes', '$333No', 0)
        else:
            await display_votepanel(aseco, player,
                                   ycolor + 'Yes - F5', '$333No - F6', 0)


async def load_donpanel(aseco: "Aseco", player: "Player"):
    if not _server_is_tmf(aseco):
        return
    if not getattr(aseco.server, "rights", False):
        return
    if not getattr(player, "rights", False):
        return
    if not _player_panel(player, "donate"):
        return

    values = _get_donation_values()
    await display_donpanel(aseco, player, values)

async def display_alldonpanels(aseco: "Aseco", _data=None):
    if not _server_is_tmf(aseco):
        return
    if not getattr(aseco.server, "rights", False):
        return

    values = _get_donation_values()
    for player in aseco.server.players.all():
        if getattr(player, "rights", False) and _player_panel(player, "donate"):
            await display_donpanel(aseco, player, values)

async def load_recpanel(aseco: "Aseco", player: "Player"):
    if not _player_panel(player, "records"):
        return
    pb = _get_player_local_pb(aseco, player.login)
    await display_recpanel(aseco, player, pb)

async def update_allrecpanels(aseco: "Aseco", _data=None):
    global _last_records_snapshot

    _update_records_cache(aseco)
    snapshot = (
        _records_cache["local"],
        _records_cache["dedi"],
        _records_cache["tmx"],
    )

    if snapshot == _last_records_snapshot and _data is not None:
        return

    _last_records_snapshot = snapshot

    for player in aseco.server.players.all():
        if _player_panel(player, "records"):
            pb = _get_player_local_pb(aseco, player.login)
            await display_recpanel(aseco, player, pb)

async def finish_recpanel(aseco: "Aseco", finish_item: list):
    if not finish_item or len(finish_item) < 3:
        return
    login = finish_item[1]
    player = aseco.server.players.get_player(login)
    if not player or not _player_panel(player, "records"):
        return
    _update_records_cache(aseco)
    pb = _get_player_local_pb(aseco, login)
    await display_recpanel(aseco, player, pb)


def _get_player_local_pb(aseco: "Aseco", login: str) -> str:
    try:
        records = aseco.server.records
        for i in range(records.count()):
            rec = records.get_record(i)
            if rec and rec.player and rec.player.login == login:
                return format_time(rec.score)
    except Exception:
        pass
    return "---.--"

def set_records_panel(which: str, value: str):
    if which not in _records_cache:
        return
    if which == "tmx" and not value:
        value = "---.--"
    logger.debug("[Panels] set_records_panel %s = %r", which, value)
    _records_cache[which] = value

def _update_records_cache(aseco: "Aseco"):
    _records_cache["local"] = ""
    _records_cache["dedi"] = ""

    try:
        if aseco.server.records.count() > 0:
            rec = aseco.server.records.get_record(0)
            if rec:
                _records_cache["local"] = format_time(rec.score)
    except Exception:
        pass

    try:
        from pyxaseco.plugins.plugin_dedimania import dedi_db
        recs = dedi_db.get("Challenge", {}).get("Records", [])
        if recs:
            _records_cache["dedi"] = format_time(int(recs[0].get("Best", 0) or 0))
    except Exception:
        pass

    if not _records_cache["tmx"]:
        _records_cache["tmx"] = ""


def _get_donation_values() -> list[int]:
    try:
        from pyxaseco.plugins.plugin_donate import donation_values
        return list(donation_values)
    except Exception:
        return [20, 50, 100, 200, 500, 1000, 2000]


async def chat_donpanel(aseco: "Aseco", command: dict):
    await _handle_panel_command(
        aseco,
        command,
        panel_type="donate",
        prefix="Donate",
        title="donate",
        max_count=20,
        action_base=ACTION_DONPANEL_BASE,
        require_rights=True,
        default_setting=getattr(aseco.settings, "donate_panel", ""),
    )


async def chat_recpanel(aseco: "Aseco", command: dict):
    await _handle_panel_command(
        aseco,
        command,
        panel_type="records",
        prefix="Records",
        title="records",
        max_count=40,
        action_base=ACTION_RECPANEL_BASE,
        require_rights=False,
        default_setting=getattr(aseco.settings, "records_panel", ""),
    )


async def chat_votepanel(aseco: "Aseco", command: dict):
    await _handle_panel_command(
        aseco,
        command,
        panel_type="vote",
        prefix="Vote",
        title="vote",
        max_count=12,
        action_base=ACTION_VOTEPANEL_BASE,
        require_rights=False,
        default_setting=getattr(aseco.settings, "vote_panel", ""),
    )


async def _handle_panel_command(
    aseco: "Aseco",
    command: dict,
    panel_type: str,
    prefix: str,
    title: str,
    max_count: int,
    action_base: int,
    default_setting: str,
    require_rights: bool = False,
    admin_only: bool = False,
):
    player = command["author"]
    login = player.login
    params = (command.get("params") or "").strip()

    if not _server_is_tmf(aseco):
        await _send_login(aseco, login, aseco.get_chat_message("FOREVER_ONLY"))
        return

    if require_rights and not getattr(aseco.server, "rights", False):
        await _send_login(aseco, login, aseco.get_chat_message("UNITED_ONLY").format("server"))
        return

    if require_rights and not getattr(player, "rights", False):
        await _send_login(aseco, login, aseco.get_chat_message("UNITED_ONLY").format("account"))
        return

    if admin_only:
        try:
            is_admin = aseco.is_any_admin(player)
        except Exception:
            is_admin = False
        if not is_admin:
            return

    if params == "help":
        help_rows = [
            ["...", "{#black}help", "Displays this help information"],
            ["...", "{#black}list", "Displays available panels"],
            ["...", "{#black}default", "Resets panel to server default"],
            ["...", "{#black}off", f"Disables {title} panel"],
            ["...", "{#black}xxx", f"Selects {title} panel xxx"],
        ]
        cmd_name = "/admin panel" if panel_type == "admin" else f"/{title}panel"
        display_manialink(
            aseco,
            login,
            f"{{#black}}{cmd_name}$g will change the {title} panel:",
            ["Icons64x64_1", "TrackInfo", -0.01],
            help_rows,
            [0.8, 0.05, 0.15, 0.6],
            "OK",
        )
        return

    if params == "list":
        files = _list_templates(aseco, prefix, max_count)
        files.extend(["default", "off"])

        player.tracklist = [{"panel": f} for f in files]
        player.msgs = [[
            1,
            f"Currently available {title} panels:",
            [0.8, 0.1, 0.7],
            ["Icons128x128_1", "Custom"],
        ]]

        page = []
        for i, file in enumerate(files, 1):
            action = _action_id(action_base, i)
            page.append([f"{i:02d}.", [f"{{#black}}{file}", action]])
            if len(page) >= 15:
                player.msgs.append(page)
                page = []
        if page:
            player.msgs.append(page)

        display_manialink_multi(aseco, player)
        return

    if not params:
        cmd_name = "/admin panel help" if panel_type == "admin" else f"/{title}panel help"
        await _send_login(
            aseco,
            login,
            f"{{#server}}> {{#error}}No {title} panel specified, use {{#highlite}}$i {cmd_name} {{#error}}!",
        )
        return

    panel = params
    if panel.isdigit():
        pid = int(panel.lstrip("0") or "0") - 1
        if 0 <= pid < len(player.tracklist) and "panel" in player.tracklist[pid]:
            panel = player.tracklist[pid]["panel"]

    if panel == "off":
        _set_player_panel(player, panel_type, "")
        await _persist_panel_choice(aseco, login, panel_type, "")
        await _disable_panel_by_type(aseco, login, panel_type)
        await _send_login(aseco, login, f"{{#server}}> {title.capitalize()} panel disabled!")
        return

    if panel == "default":
        _set_player_panel(player, panel_type, _default_panels.get(panel_type, ""))
        logger.debug(
            "[Panels] %s requested default %s panel -> %r",
            login, panel_type, default_setting
        )
        await _persist_panel_choice(aseco, login, panel_type, default_setting)
        await _refresh_panel_by_type(aseco, player, panel_type)
        pretty = _strip_prefix(default_setting, prefix)
        await _send_login(
            aseco,
            login,
            f"{{#server}}> {title.capitalize()} panel reset to server default {{#highlite}}{pretty}{{#server}} !",
        )
        return

    full_name = panel if panel.lower().startswith(prefix.lower()) else f"{prefix}{panel}"
    try:
        xml = _read_panel_file(aseco, full_name)
    except Exception:
        await _send_login(
            aseco,
            login,
            f"{{#server}}> {{#error}}No valid {title} panel file, use {{#highlite}}$i "
            f"{'/admin panel list' if panel_type == 'admin' else '/' + title + 'panel list'} "
            f"{{#error}}!",
        )
        return

    _set_player_panel(player, panel_type, xml)
    await _persist_panel_choice(aseco, login, panel_type, full_name)
    await _refresh_panel_by_type(aseco, player, panel_type)
    await _send_login(
        aseco,
        login,
        f"{{#server}}> {title.capitalize()} panel {{#highlite}}{params}{{#server}} selected!",
    )


def _action_id(base: int, index_1_based: int) -> int:
    return base + index_1_based


def _strip_prefix(name: str, prefix: str) -> str:
    if name.lower().startswith(prefix.lower()):
        return name[len(prefix):]
    return name


async def _persist_panel_choice(aseco: "Aseco", login: str, panel_type: str, value: str):
    try:
        current = await _get_player_panel_names_from_db(aseco, login)
        current[panel_type] = (value or "").strip()
        await _persist_all_panel_choices(aseco, login, current)

        logger.debug(
            "[Panels] Persisted %s panel for %s -> %r (merged=%r)",
            panel_type, login, value, current
        )
    except Exception as e:
        logger.debug("[Panels] Could not persist %s panel for %s: %s", panel_type, login, e)


async def _refresh_panel_by_type(aseco: "Aseco", player: "Player", panel_type: str):
    if panel_type == "admin":
        await display_admpanel(aseco, player)
    elif panel_type == "donate":
        await load_donpanel(aseco, player)
    elif panel_type == "records":
        await load_recpanel(aseco, player)
    elif panel_type == "vote":
        await display_votepanel(
            aseco,
            player,
            aseco.format_colors("{#vote}") + "Yes - F5",
            "$333No - F6",
            2000,
        )


async def _disable_panel_by_type(aseco: "Aseco", login: str, panel_type: str):
    if panel_type == "admin":
        await _send_panel_xml(aseco, login, _empty_panel_xml(PANEL_ID_ADMIN), 0, False)
    elif panel_type == "donate":
        await donpanel_off(aseco, login)
    elif panel_type == "records":
        await recpanel_off(aseco, login)
    elif panel_type == "vote":
        await votepanel_off(aseco, login)


async def _fire_chat_command(aseco: "Aseco", player: "Player", command_name: str, params: str = ""):
    """
    Simulate a chat command by firing the corresponding onChat_* event.
    """
    await aseco.release_event(
        f"onChat_{command_name}",
        {
            "author": player,
            "command": command_name,
            "params": params,
        }
    )


async def _fire_admin_command(aseco: "Aseco", player: "Player", params: str):
    """
    Simulate /admin <params>
    """
    await aseco.release_event(
        "onChat_admin",
        {
            "author": player,
            "command": "admin",
            "params": params,
        }
    )


async def event_panels(aseco: "Aseco", answer: list):
    if len(answer) < 3:
        return

    login = answer[1]
    try:
        action = int(answer[2])
    except Exception:
        return

    player = aseco.server.players.get_player(login)
    if not player:
        return

    # ------------------------------------------------------------------
    # Functional panel buttons
    # ------------------------------------------------------------------

    # Records panel
    if action == ACTION_REC_PB:
        await _fire_chat_command(aseco, player, "topsums")
        return

    if action in (ACTION_REC_LOCAL, ACTION_REC_LOCAL_ALT):
        await _fire_chat_command(aseco, player, "recs")
        return

    if action in (ACTION_REC_DEDI, ACTION_REC_DEDI_ALT):
        await _fire_chat_command(aseco, player, "dedirecs")
        return

    if action == ACTION_REC_TMX:
        await _fire_chat_command(aseco, player, "tmxrecs")
        return

    # Donate panel
    donate_map = {
        ACTION_DONATE_20: "20",
        ACTION_DONATE_50: "50",
        ACTION_DONATE_100: "100",
        ACTION_DONATE_200: "200",
        ACTION_DONATE_500: "500",
        ACTION_DONATE_1000: "1000",
        ACTION_DONATE_2000: "2000",
    }
    if action in donate_map:
        await _fire_chat_command(aseco, player, "donate", donate_map[action])
        return

    # Vote panel
    if action == ACTION_VOTE_YES:
        await _fire_chat_command(aseco, player, "y")
        return

    if action == ACTION_VOTE_NO:
        return

    if action == ACTION_JUKEBOX_CLEAR:
        await _fire_admin_command(aseco, player, "clearjukebox")
        return

    # Admin panel
    if action == ACTION_ADMIN_RESTART:
        await _fire_admin_command(aseco, player, "restart")
        return

    if action == ACTION_ADMIN_ENDROUND:
        await _fire_admin_command(aseco, player, "endround")
        return

    if action == ACTION_ADMIN_SKIP:
        await _fire_admin_command(aseco, player, "skip")
        return

    if action == ACTION_ADMIN_REPLAY:
        await _fire_admin_command(aseco, player, "replay")
        return

    if action == ACTION_ADMIN_PASS:
        await _fire_admin_command(aseco, player, "pass")
        return

    if action == ACTION_ADMIN_CANCEL:
        await _fire_admin_command(aseco, player, "cancel")
        return

    if action == ACTION_ADMIN_PLAYERS_LIVE:
        await _fire_admin_command(aseco, player, "players live")
        return

    async def _dispatch(param: str, panel_name: str):
        command = {"author": player, "params": panel_name}
        if param == "admin":
            await _handle_panel_command(
                aseco, command,
                panel_type="admin", prefix="Admin", title="admin",
                max_count=40, action_base=ACTION_ADMIN_BASE,
                default_setting=getattr(aseco.settings, "admin_panel", ""),
                admin_only=True,
            )
        elif param == "donate":
            await chat_donpanel(aseco, command)
        elif param == "records":
            await chat_recpanel(aseco, command)
        elif param == "vote":
            await chat_votepanel(aseco, command)

    if -100 <= action <= -49:
        idx = abs(action) - 50
        if 0 <= idx < len(player.tracklist):
            await _dispatch("records", player.tracklist[idx]["panel"])
        return

    if -48 <= action <= -7:
        idx = abs(action) - 8
        if 0 <= idx < len(player.tracklist):
            await _dispatch("admin", player.tracklist[idx]["panel"])
        return

    if 37 <= action <= 48:
        idx = action - 37
        if 0 <= idx < len(player.tracklist):
            await _dispatch("vote", player.tracklist[idx]["panel"])
        return

    if 7201 <= action <= 7222:
        idx = action - 7201
        if 0 <= idx < len(player.tracklist):
            await _dispatch("donate", player.tracklist[idx]["panel"])
        return
