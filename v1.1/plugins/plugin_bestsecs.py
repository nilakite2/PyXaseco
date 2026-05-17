"""
plugin_bestsecs.py - Python port of plugin_bestsecs.php (v2.0)

Tracks best sector times (time between consecutive checkpoints) for every
player on each challenge.

Two tables are maintained:
  secrecs_all  - one row per sector: the overall best time for that sector
  secrecs_own  - one row per (player, sector): each player's personal best
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

ML_BUTTON_ID = "0815470000122"
ACTION_SECRECS = 27008505
ACTION_MYSECRECS = 27008504


@dataclass
class SecRec:
    time: int
    login: str
    cp: int


_tab_sec_recs: dict[int, SecRec] = {}
_tab_own_recs: dict[str, dict[int, SecRec]] = {}
_last_cp: dict[str, dict] = {}

_challenge_uid: str = ""
_challenge_id: int = 0
_checkpoint_amount: int = 0
_show_secrecs: bool = False

_cfg_announce_sec: bool = True
_cfg_announce_own: bool = True
_cfg_compare_own_to_self: bool = True
_cfg_remove_on_delete: bool = True
_cfg_pos_x: float = 50.9
_cfg_pos_y: float = -30.0
_cfg_window_enabled: dict[int, bool] = {}


def register(aseco: "Aseco"):
    aseco.register_event("onSync", bestsecs_sync)
    aseco.register_event("onNewChallenge", bestsecs_new_challenge)
    aseco.register_event("onCheckpoint", bestsecs_checkpoint)
    aseco.register_event("onPlayerFinish1", bestsecs_player_finish)
    aseco.register_event("onPlayerConnect", bestsecs_player_connect)
    aseco.register_event("onPlayerManialinkPageAnswer", bestsecs_button_click)
    aseco.register_event("onTracklistChanged", bestsecs_tracklist_changed)

    aseco.add_chat_command("secrecs", "Shows Sector Records")
    aseco.add_chat_command("mysecrecs", "Shows own Sector Records")
    aseco.add_chat_command("delsecs", "Deletes all secrecs on this challenge", True)
    aseco.add_chat_command(
        "delsec",
        "Deletes sector N or range N-M on this challenge (e.g. /delsec 3 or /delsec 2-5)",
        True,
    )
    aseco.add_chat_command(
        "secrecs_cleanupdb",
        "Removes orphaned/duplicate secrecs from database",
        True,
    )

    aseco.register_event("onChat_secrecs", chat_secrecs)
    aseco.register_event("onChat_mysecrecs", chat_mysecrecs)
    aseco.register_event("onChat_delsecs", chat_delsecs)
    aseco.register_event("onChat_delsec", chat_delsec)
    aseco.register_event("onChat_secrecs_cleanupdb", chat_secrecs_cleanupdb)


def _sec_to_time(ms: int, prefix: bool = False) -> str:
    pre = ""
    if prefix:
        pre = "-" if ms < 0 else "+"
    ms = abs(ms)
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    centis = (ms % 1000) // 10
    return f"{pre}{minutes}:{seconds:02d}.{centis:02d}"


def _sec_to_time_short(ms: int, prefix: bool = False) -> str:
    pre = ""
    if prefix:
        pre = "-" if ms < 0 else "+"
    ms = abs(ms)
    seconds = ms // 1000
    centis = (ms % 1000) // 10
    return f"{pre}{seconds}.{centis:02d}"


async def _get_pool():
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool

        return await get_pool()
    except Exception:
        return None


async def _get_nickname(pool, login: str) -> str:
    if not pool:
        return login
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT NickName FROM players WHERE Login=%s LIMIT 1", (login,))
                row = await cur.fetchone()
                return row[0] if row else login
    except Exception:
        return login


def _load_config(aseco: "Aseco") -> None:
    global _cfg_announce_sec, _cfg_announce_own, _cfg_compare_own_to_self
    global _cfg_remove_on_delete, _cfg_pos_x, _cfg_pos_y, _cfg_window_enabled

    candidates = [
        Path(getattr(aseco, "_base_dir", ".")).resolve() / "bestsecs.xml",
        Path(".").resolve() / "bestsecs.xml",
    ]
    path = None
    for candidate in candidates:
        if candidate.exists():
            path = candidate
            break

    if path is None:
        logger.warning("[BestSecs] bestsecs.xml not found - using defaults")
        return

    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(str(path)).getroot()

        def _text(node, tag, default=""):
            el = node.find(tag)
            return el.text.strip() if el is not None and el.text else default

        def _bool_val(value: str) -> bool:
            return value.strip() in ("1", "true", "True", "TRUE")

        pos = root.find("position")
        if pos is not None:
            try:
                _cfg_pos_x = float(_text(pos, "xPos", "50.9"))
                _cfg_pos_y = float(_text(pos, "yPos", "-30"))
            except ValueError:
                pass

        dr = root.find("display_recs")
        if dr is not None:
            _cfg_announce_sec = _bool_val(_text(dr, "sec_recs", "1"))
            _cfg_announce_own = _bool_val(_text(dr, "own_recs", "1"))

        _cfg_compare_own_to_self = _bool_val(
            _text(root, "compare_own_rec_to_self", "1")
        )
        _cfg_remove_on_delete = _bool_val(_text(root, "remove_sec_from_db", "1"))

        from pyxaseco.models import Gameinfo

        we = root.find("window_enabled")
        if we is not None:
            _cfg_window_enabled = {
                Gameinfo.RNDS: _bool_val(_text(we, "Rounds", "1")),
                Gameinfo.TA: _bool_val(_text(we, "TA", "1")),
                Gameinfo.TEAM: _bool_val(_text(we, "Team", "1")),
                Gameinfo.LAPS: _bool_val(_text(we, "Lap", "1")),
                Gameinfo.STNT: _bool_val(_text(we, "Stunts", "1")),
                Gameinfo.CUP: _bool_val(_text(we, "Cup", "1")),
            }

        logger.info("[BestSecs] Config loaded from %s", path)
    except Exception as exc:
        logger.warning("[BestSecs] Could not parse bestsecs.xml: %s", exc)


async def _ensure_tables(pool) -> None:
    ddl_all = (
        "CREATE TABLE IF NOT EXISTS `secrecs_all` ("
        "`Id` INT NOT NULL AUTO_INCREMENT,"
        "`ChallengeId` INT NOT NULL,"
        "`Sector` INT NOT NULL,"
        "`PlayerId` INT NOT NULL,"
        "`Time` INT NOT NULL,"
        "PRIMARY KEY (`Id`),"
        "UNIQUE KEY `unique_challenge_sector` (`ChallengeId`, `Sector`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    ddl_own = (
        "CREATE TABLE IF NOT EXISTS `secrecs_own` ("
        "`Id` INT NOT NULL AUTO_INCREMENT,"
        "`ChallengeId` INT NOT NULL,"
        "`Sector` INT NOT NULL,"
        "`PlayerId` INT NOT NULL,"
        "`Time` INT NOT NULL,"
        "PRIMARY KEY (`Id`),"
        "UNIQUE KEY `unique_challenge_sector_player` (`ChallengeId`, `Sector`, `PlayerId`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(ddl_all)
                await cur.execute(ddl_own)
    except Exception as exc:
        logger.error("[BestSecs] Table creation failed: %s", exc)


async def _upgrade_database_structure(pool) -> None:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SHOW TABLES LIKE 'secrecs_all'")
                if not await cur.fetchone():
                    return

                await cur.execute("SHOW COLUMNS FROM secrecs_all LIKE 'ChallengeID'")
                challenge_col = await cur.fetchone()
                if not challenge_col:
                    return

                old_type = str(challenge_col[1] if len(challenge_col) > 1 else "")
                if "varchar" not in old_type.lower():
                    return

                logger.warning("[BestSecs] Upgrading old string-keyed secrecs tables to v2.0 schema...")

                await cur.execute(
                    "SELECT ChallengeID, Sector, PlayerNick, Time, ID "
                    "FROM secrecs_all WHERE ChallengeID <> '' AND PlayerNick <> ''"
                )
                old_all = await cur.fetchall()

                await cur.execute(
                    "SELECT ChallengeID, Sector, PlayerNick, Time, ID "
                    "FROM secrecs_own WHERE ChallengeID <> '' AND PlayerNick <> ''"
                )
                old_own = await cur.fetchall()

                await cur.execute("SELECT Id, UId FROM challenges")
                challenge_rows = await cur.fetchall()
                challenge_map = {str(uid): int(ch_id) for ch_id, uid in challenge_rows if uid}

                await cur.execute("SELECT Id, Login FROM players")
                player_rows = await cur.fetchall()
                player_map = {str(login): int(player_id) for player_id, login in player_rows if login}

                best_all: dict[tuple[int, int], tuple[int, int]] = {}
                for uid, sector, login, time_ms, row_id in old_all:
                    challenge_id = challenge_map.get(str(uid))
                    player_id = player_map.get(str(login))
                    if not challenge_id or not player_id:
                        continue
                    key = (challenge_id, int(sector))
                    value = (int(time_ms), int(player_id))
                    current = best_all.get(key)
                    if current is None or value[0] < current[0]:
                        best_all[key] = value

                best_own: dict[tuple[int, int, int], int] = {}
                for uid, sector, login, time_ms, row_id in old_own:
                    challenge_id = challenge_map.get(str(uid))
                    player_id = player_map.get(str(login))
                    if not challenge_id or not player_id:
                        continue
                    key = (challenge_id, int(sector), int(player_id))
                    value = int(time_ms)
                    current = best_own.get(key)
                    if current is None or value < current:
                        best_own[key] = value

                await cur.execute("DROP TABLE IF EXISTS secrecs_all_old")
                await cur.execute("DROP TABLE IF EXISTS secrecs_own_old")
                await cur.execute("RENAME TABLE secrecs_all TO secrecs_all_old, secrecs_own TO secrecs_own_old")

                await _ensure_tables(pool)

                if best_all:
                    rows = [
                        (challenge_id, sector, player_id, time_ms)
                        for (challenge_id, sector), (time_ms, player_id) in best_all.items()
                    ]
                    await cur.executemany(
                        "INSERT INTO secrecs_all (ChallengeId, Sector, PlayerId, Time) "
                        "VALUES (%s, %s, %s, %s)",
                        rows,
                    )

                if best_own:
                    rows = [
                        (challenge_id, sector, player_id, time_ms)
                        for (challenge_id, sector, player_id), time_ms in best_own.items()
                    ]
                    await cur.executemany(
                        "INSERT INTO secrecs_own (ChallengeId, Sector, PlayerId, Time) "
                        "VALUES (%s, %s, %s, %s)",
                        rows,
                    )

                await cur.execute("DROP TABLE secrecs_all_old")
                await cur.execute("DROP TABLE secrecs_own_old")

                logger.warning(
                    "[BestSecs] Upgrade complete: secrecs_all=%d, secrecs_own=%d",
                    len(best_all),
                    len(best_own),
                )
    except Exception as exc:
        logger.error("[BestSecs] Database upgrade failed: %s", exc)


async def _load_all_from_db(challenge_id: int) -> None:
    global _tab_sec_recs
    _tab_sec_recs = {}
    pool = await _get_pool()
    if not pool or challenge_id <= 0:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT sec.Sector, p.Login, sec.Time "
                    "FROM secrecs_all sec "
                    "INNER JOIN players p ON sec.PlayerId = p.Id "
                    "WHERE sec.ChallengeId=%s ORDER BY sec.Sector",
                    (challenge_id,),
                )
                for sector, login, time_ms in await cur.fetchall():
                    _tab_sec_recs[int(sector)] = SecRec(int(time_ms), str(login), int(sector))
    except Exception as exc:
        logger.error("[BestSecs] Load secrecs_all failed: %s", exc)


async def _load_own_from_db(challenge_id: int, player: "Player") -> None:
    _tab_own_recs[player.login] = {}
    pool = await _get_pool()
    if not pool or challenge_id <= 0 or player.id <= 0:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT Sector, Time FROM secrecs_own "
                    "WHERE ChallengeId=%s AND PlayerId=%s ORDER BY Sector",
                    (challenge_id, player.id),
                )
                for sector, time_ms in await cur.fetchall():
                    _tab_own_recs[player.login][int(sector)] = SecRec(
                        int(time_ms), player.login, int(sector)
                    )
    except Exception as exc:
        logger.error("[BestSecs] Load secrecs_own for %s failed: %s", player.login, exc)


async def _update_all(time_ms: int, sector: int, challenge_id: int, player_id: int) -> None:
    pool = await _get_pool()
    if not pool or challenge_id <= 0 or player_id <= 0:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO secrecs_all (ChallengeId, Sector, PlayerId, Time) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE PlayerId=VALUES(PlayerId), Time=VALUES(Time)",
                    (challenge_id, sector, player_id, time_ms),
                )
    except Exception as exc:
        logger.error("[BestSecs] Update secrecs_all failed: %s", exc)


async def _update_own(
    time_ms: int, sector: int, challenge_id: int, player_id: int, login: str
) -> None:
    pool = await _get_pool()
    if not pool or challenge_id <= 0 or player_id <= 0:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO secrecs_own (ChallengeId, Sector, PlayerId, Time) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE Time=VALUES(Time)",
                    (challenge_id, sector, player_id, time_ms),
                )
    except Exception as exc:
        logger.error("[BestSecs] Update secrecs_own for %s failed: %s", login, exc)


async def _send_button(aseco: "Aseco", login: str | None = None) -> None:
    if not _show_secrecs:
        return

    xml = (
        f'<manialink id="{ML_BUTTON_ID}">'
        '<format style="TextCardInfoSmall" textsize="1"/>'
        f'<frame posn="{_cfg_pos_x} {_cfg_pos_y} 1">'
        '<quad posn="4.5 0 0" sizen="18 2.5" halign="center" valign="center"'
        ' style="Bgs1InRace" substyle="BgWindow1"/>'
        f'<label posn="0 0.2 1" sizen="8 2" halign="center" valign="center" text="$i$s$fffSecrecs" action="{ACTION_SECRECS}"/>'
        f'<label posn="8 0.2 1" sizen="8 2" halign="center" valign="center" text="$i$s$fffMy Secrecs" action="{ACTION_MYSECRECS}"/>'
        "</frame>"
        "</manialink>"
    )
    if login:
        await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)
    else:
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def _hide_button(aseco: "Aseco") -> None:
    xml = f'<manialink id="{ML_BUTTON_ID}"></manialink>'
    await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)


async def bestsecs_sync(aseco: "Aseco", _data=None) -> None:
    global _challenge_uid, _challenge_id

    _load_config(aseco)
    pool = await _get_pool()
    if pool:
        await _upgrade_database_structure(pool)
        await _ensure_tables(pool)

    challenge = getattr(aseco.server, "challenge", None)
    if challenge:
        _challenge_uid = getattr(challenge, "uid", "") or ""
        _challenge_id = int(getattr(challenge, "id", 0) or 0)
        if _challenge_id > 0:
            await _load_all_from_db(_challenge_id)
            for player in aseco.server.players.all():
                await _load_own_from_db(_challenge_id, player)

    _update_show_secrecs(aseco)
    await _send_button(aseco)


async def bestsecs_new_challenge(aseco: "Aseco", challenge) -> None:
    global _challenge_uid, _challenge_id, _last_cp, _checkpoint_amount

    _challenge_uid = getattr(challenge, "uid", "") or ""
    _challenge_id = int(getattr(challenge, "id", 0) or 0)
    _last_cp = {}

    await _load_all_from_db(_challenge_id)
    for player in aseco.server.players.all():
        await _load_own_from_db(_challenge_id, player)

    try:
        info = await aseco.client.query("GetCurrentChallengeInfo")
        _checkpoint_amount = int((info or {}).get("NbCheckpoints", 0) or 0)
    except Exception:
        _checkpoint_amount = 0

    _update_show_secrecs(aseco)
    if _show_secrecs:
        await _send_button(aseco)
    else:
        await _hide_button(aseco)


async def bestsecs_checkpoint(aseco: "Aseco", params: list) -> None:
    global _last_cp

    if len(params) < 5:
        return

    login = params[1]
    time_or_score = int(params[2])
    checkpoint_index = int(params[4])

    do_update = True
    sector_time = 0
    last = _last_cp.get(login)

    if last is None and checkpoint_index == 0:
        sector_time = time_or_score
    elif last is None and checkpoint_index != 0:
        do_update = False
        if _checkpoint_amount == 1:
            sector_time = time_or_score
            do_update = True
    elif last is not None and checkpoint_index == 0:
        sector_time = time_or_score
    else:
        sector_time = time_or_score - last["cpTime"]

    if do_update and sector_time > 0:
        player = aseco.server.players.get_player(login)
        if player and player.id > 0 and _challenge_id > 0:
            pool = await _get_pool()
            nickname = player.nickname or await _get_nickname(pool, login)

            overall_existing = _tab_sec_recs.get(checkpoint_index)
            sector_all_checkpoint_time = overall_existing.time if overall_existing else 0

            if overall_existing is None or sector_time < overall_existing.time:
                old_diff = sector_time if overall_existing is None else sector_time - overall_existing.time
                _tab_sec_recs[checkpoint_index] = SecRec(sector_time, login, checkpoint_index)
                if _cfg_announce_sec:
                    if overall_existing is None:
                        message = (
                            f"{nickname} $z$29fclaimed the record in sector {checkpoint_index}. "
                            f"Time: {_sec_to_time(sector_time)}"
                        )
                    else:
                        message = (
                            f"{nickname} $z$29fgained the record in sector {checkpoint_index}. "
                            f"Time: {_sec_to_time(sector_time)} ({_sec_to_time_short(old_diff, True)})"
                        )
                    await aseco.client.query_ignore_result(
                        "ChatSendServerMessage",
                        aseco.format_colors(message),
                    )
                await _update_all(sector_time, checkpoint_index, _challenge_id, player.id)

            own = _tab_own_recs.setdefault(login, {})
            own_existing = own.get(checkpoint_index)
            if own_existing is None or sector_time < own_existing.time:
                if _cfg_compare_own_to_self:
                    old_diff = sector_time if own_existing is None else sector_time - own_existing.time
                    was_improvement = own_existing is not None
                else:
                    old_diff = sector_time - sector_all_checkpoint_time
                    was_improvement = own_existing is not None and own_existing.time != 0

                own[checkpoint_index] = SecRec(sector_time, login, checkpoint_index)

                if _cfg_announce_own:
                    if was_improvement:
                        text = (
                            f"> You improved your record in sector {checkpoint_index}. "
                            f"Time: {_sec_to_time(sector_time)} ({_sec_to_time_short(old_diff, True)})"
                        )
                    else:
                        if _cfg_compare_own_to_self or old_diff == sector_time:
                            text = (
                                f"> You set a record in sector {checkpoint_index}. "
                                f"Time: {_sec_to_time(sector_time)}"
                            )
                        else:
                            text = (
                                f"> You set a record in sector {checkpoint_index}. "
                                f"Time: {_sec_to_time(sector_time)} ({_sec_to_time_short(old_diff, True)})"
                            )
                    await aseco.client.query_ignore_result(
                        "ChatSendServerMessageToLogin",
                        aseco.format_colors(text),
                        login,
                    )
                await _update_own(sector_time, checkpoint_index, _challenge_id, player.id, login)

    _last_cp[login] = {"cpIndex": checkpoint_index, "cpTime": time_or_score}


async def bestsecs_player_finish(aseco: "Aseco", finish) -> None:
    login = finish.player.login if finish and finish.player else ""
    if login:
        _last_cp.pop(login, None)


async def bestsecs_player_connect(aseco: "Aseco", player: "Player") -> None:
    if _challenge_id > 0:
        await _load_own_from_db(_challenge_id, player)
    await _send_button(aseco, player.login)
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors(
            "{#server}>> {#message}This server runs BestSecs. "
            "Type {#highlite}/secrecs {#message}or {#highlite}/mysecrecs "
            "{#message}to view sector records."
        ),
        player.login,
    )


async def bestsecs_button_click(aseco: "Aseco", answer: list) -> None:
    if len(answer) < 3:
        return
    login = answer[1]
    action = int(answer[2]) if answer[2] is not None else 0

    player = aseco.server.players.get_player(login)
    if not player:
        return

    if action == ACTION_SECRECS:
        await aseco.release_event("onChat_secrecs", {"author": player, "params": ""})
    elif action == ACTION_MYSECRECS:
        await aseco.release_event("onChat_mysecrecs", {"author": player, "params": ""})


async def bestsecs_tracklist_changed(aseco: "Aseco", data=None) -> None:
    if not _cfg_remove_on_delete:
        return
    if not isinstance(data, (list, tuple)) or not data or data[0] != "remove":
        return

    filename = data[1] if len(data) > 1 else ""
    if not filename:
        return

    try:
        info = await aseco.client.query("GetChallengeInfo", filename)
        uid = (info or {}).get("UId", "")
    except Exception:
        uid = ""

    if not uid:
        return

    pool = await _get_pool()
    if not pool:
        return

    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT Id FROM challenges WHERE UId=%s LIMIT 1", (uid,))
                row = await cur.fetchone()
                if not row:
                    return
                challenge_id = int(row[0])
                await cur.execute("DELETE FROM secrecs_own WHERE ChallengeId=%s", (challenge_id,))
                await cur.execute("DELETE FROM secrecs_all WHERE ChallengeId=%s", (challenge_id,))
        logger.info("[BestSecs] Removed secrecs for deleted map UID=%s", uid)
    except Exception as exc:
        logger.error("[BestSecs] Delete secrecs for %s failed: %s", uid, exc)


async def chat_secrecs(aseco: "Aseco", command: dict) -> None:
    from pyxaseco.helpers import display_manialink_multi

    player: Player = command["author"]
    await _load_all_from_db(_challenge_id)

    pool = await _get_pool()
    header = "Sector Records on this Map:"
    player.msgs = [[1, header, [1.25], ["Icons64x64_1", "TrackInfo"]]]

    recs = sorted(_tab_sec_recs.items())
    if not recs:
        player.msgs.append([""])
        display_manialink_multi(aseco, player)
        return

    pages: dict[int, list] = {}
    overall_time = 0
    for idx, (sector, rec) in enumerate(recs):
        page = (idx // 15) + 1
        overall_time += rec.time
        sec_str = f"{sector:02d}"
        nick = await _get_nickname(pool, rec.login)
        line = aseco.format_colors(
            f"{{#highlite}}Sec{sec_str}: {_sec_to_time(rec.time)} by {nick}"
        )
        pages.setdefault(page, []).append([line])

    for page in sorted(pages):
        rows = pages[page]
        rows.append([""])
        rows.append([aseco.format_colors(f"{{#highlite}}Total Time: {_sec_to_time(overall_time)}")])
        player.msgs.append(rows)

    display_manialink_multi(aseco, player)


async def chat_mysecrecs(aseco: "Aseco", command: dict) -> None:
    from pyxaseco.helpers import display_manialink_multi

    player: Player = command["author"]
    await _load_all_from_db(_challenge_id)
    await _load_own_from_db(_challenge_id, player)

    pool = await _get_pool()
    header = "Your own Sector Records on this Map:"
    player.msgs = [[1, header, [1.25], ["Icons64x64_1", "TrackInfo"]]]

    recs = sorted(_tab_own_recs.get(player.login, {}).items())
    if not recs:
        player.msgs.append([""])
        display_manialink_multi(aseco, player)
        return

    pages: dict[int, list] = {}
    overall_time = 0
    for idx, (sector, rec) in enumerate(recs):
        page = (idx // 15) + 1
        overall_time += rec.time
        sec_str = f"{sector:02d}"

        best = _tab_sec_recs.get(sector)
        if best:
            diff_str = _sec_to_time(rec.time - best.time, prefix=True)
            best_nick = await _get_nickname(pool, best.login)
            suffix = f" ( {diff_str} to TOP1 {best_nick}$z$o{{#highlite}} )"
        else:
            suffix = ""

        line = aseco.format_colors(
            f"{{#highlite}}Sec{sec_str}: {_sec_to_time(rec.time)}{suffix}"
        )
        pages.setdefault(page, []).append([line])

    for page in sorted(pages):
        rows = pages[page]
        rows.append([""])
        rows.append([aseco.format_colors(f"{{#highlite}}Total Time: {_sec_to_time(overall_time)}")])
        player.msgs.append(rows)

    display_manialink_multi(aseco, player)


def _can_delete(aseco: "Aseco", player: "Player") -> bool:
    return aseco.is_master_admin(player) or aseco.is_admin(player) or aseco.is_operator(player)


async def chat_delsecs(aseco: "Aseco", command: dict) -> None:
    admin: Player = command["author"]
    if not _can_delete(aseco, admin):
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            "> You must be an Admin to use this command",
            admin.login,
        )
        return

    pool = await _get_pool()
    if pool and _challenge_id > 0:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM secrecs_all WHERE ChallengeId=%s", (_challenge_id,))
                await cur.execute("DELETE FROM secrecs_own WHERE ChallengeId=%s", (_challenge_id,))

    _tab_sec_recs.clear()
    _tab_own_recs.clear()
    await _load_all_from_db(_challenge_id)
    for player in aseco.server.players.all():
        await _load_own_from_db(_challenge_id, player)

    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors("> All SecRecs deleted !"),
        admin.login,
    )


async def _delete_sectors(aseco: "Aseco", lo: int, hi: int) -> None:
    pool = await _get_pool()
    if pool and _challenge_id > 0:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for sector in range(lo, hi + 1):
                    await cur.execute(
                        "DELETE FROM secrecs_all WHERE ChallengeId=%s AND Sector=%s",
                        (_challenge_id, sector),
                    )
                    await cur.execute(
                        "DELETE FROM secrecs_own WHERE ChallengeId=%s AND Sector=%s",
                        (_challenge_id, sector),
                    )

    await _load_all_from_db(_challenge_id)
    for player in aseco.server.players.all():
        await _load_own_from_db(_challenge_id, player)


async def chat_delsec(aseco: "Aseco", command: dict) -> None:
    admin: Player = command["author"]
    if not _can_delete(aseco, admin):
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            "> You must be an Admin to use this command",
            admin.login,
        )
        return

    params = (command.get("params") or "").strip()

    async def _reply(msg: str) -> None:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors(msg),
            admin.login,
        )

    global _checkpoint_amount
    try:
        info = await aseco.client.query("GetCurrentChallengeInfo")
        _checkpoint_amount = int((info or {}).get("NbCheckpoints", 0) or 0)
    except Exception:
        pass

    numbers = re.findall(r"\d+", params)
    count = len(numbers)

    if count == 0:
        await _reply("> Usage: /delsec 2; /delsec 3-5")
        return

    if count == 1 and params == numbers[0]:
        sector = int(numbers[0])
        if not (0 <= sector < _checkpoint_amount):
            await _reply("> Please choose a valid sector.")
            return
        await _delete_sectors(aseco, sector, sector)
        await aseco.client.query_ignore_result(
            "ChatSendServerMessage",
            aseco.format_colors(f"> Sector {sector} deleted."),
        )
        return

    if count == 2 and re.fullmatch(r"\d+-\d+", params):
        lo, hi = int(numbers[0]), int(numbers[1])
        if lo > hi:
            lo, hi = hi, lo
        if not (0 <= lo and hi < _checkpoint_amount):
            await _reply("> Please choose a valid sector range.")
            return
        await _delete_sectors(aseco, lo, hi)
        if lo == hi:
            message = f"> Sector {lo} deleted."
        else:
            message = f"> Sectors {lo}-{hi} deleted."
        await aseco.client.query_ignore_result(
            "ChatSendServerMessage",
            aseco.format_colors(message),
        )
        return

    await _reply("> Usage: /delsec 2; /delsec 3-5")


async def chat_secrecs_cleanupdb(aseco: "Aseco", command: dict) -> None:
    author: Player = command["author"]
    if not aseco.is_master_admin(author):
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            "> You must be a MasterAdmin to use this command",
            author.login,
        )
        return

    async def _chat(msg: str) -> None:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors(msg),
            author.login,
        )

    pool = await _get_pool()
    if not pool:
        await _chat("> Database not available.")
        return

    total_removed = 0

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM secrecs_all WHERE ChallengeId NOT IN (SELECT Id FROM challenges)"
            )
            faulty = int((await cur.fetchone())[0] or 0)
            await cur.execute(
                "SELECT COUNT(*) FROM secrecs_own WHERE ChallengeId NOT IN (SELECT Id FROM challenges)"
            )
            faulty += int((await cur.fetchone())[0] or 0)
            await cur.execute(
                "SELECT COUNT(*) FROM secrecs_all WHERE PlayerId NOT IN (SELECT Id FROM players)"
            )
            faulty += int((await cur.fetchone())[0] or 0)
            await cur.execute(
                "SELECT COUNT(*) FROM secrecs_own WHERE PlayerId NOT IN (SELECT Id FROM players)"
            )
            faulty += int((await cur.fetchone())[0] or 0)

            await cur.execute("DELETE FROM secrecs_all WHERE ChallengeId NOT IN (SELECT Id FROM challenges)")
            await cur.execute("DELETE FROM secrecs_own WHERE ChallengeId NOT IN (SELECT Id FROM challenges)")
            await cur.execute("DELETE FROM secrecs_all WHERE PlayerId NOT IN (SELECT Id FROM players)")
            await cur.execute("DELETE FROM secrecs_own WHERE PlayerId NOT IN (SELECT Id FROM players)")
            total_removed += faulty

            try:
                tracks = await aseco.client.query("GetChallengeList", 5000, 0) or []
                live_uids = {t.get("UId") or t.get("Uid", "") for t in tracks}
                live_uids.discard("")
            except Exception:
                live_uids = set()

            await cur.execute("SELECT Id, UId FROM challenges")
            old_removed = 0
            for challenge_id, uid in await cur.fetchall():
                if not uid or uid in live_uids:
                    continue
                await cur.execute("SELECT COUNT(*) FROM secrecs_all WHERE ChallengeId=%s", (challenge_id,))
                count_all = int((await cur.fetchone())[0] or 0)
                await cur.execute("SELECT COUNT(*) FROM secrecs_own WHERE ChallengeId=%s", (challenge_id,))
                count_own = int((await cur.fetchone())[0] or 0)
                if count_all + count_own == 0:
                    continue
                await cur.execute("DELETE FROM secrecs_all WHERE ChallengeId=%s", (challenge_id,))
                await cur.execute("DELETE FROM secrecs_own WHERE ChallengeId=%s", (challenge_id,))
                old_removed += count_all + count_own
                await _chat(
                    f"[plugin_bestsecs.py] Deleting {count_all + count_own} entries of old secrecs on ID {challenge_id}"
                )

            total_removed += old_removed
            if old_removed:
                await _chat("[plugin_bestsecs.py] Done deleting old secrecs")

            dup_removed = 0
            await cur.execute("SELECT DISTINCT ChallengeId FROM secrecs_own")
            challenge_ids = [int(row[0]) for row in await cur.fetchall()]

            for challenge_id in challenge_ids:
                await cur.execute("SELECT MAX(Sector) FROM secrecs_own WHERE ChallengeId=%s", (challenge_id,))
                row = await cur.fetchone()
                max_sector = int(row[0]) if row and row[0] is not None else -1

                for sector in range(max_sector + 1):
                    await cur.execute(
                        "SELECT PlayerId, COUNT(*) AS c "
                        "FROM secrecs_own WHERE ChallengeId=%s AND Sector=%s "
                        "GROUP BY PlayerId HAVING c > 1",
                        (challenge_id, sector),
                    )
                    for player_id, dup_count in await cur.fetchall():
                        await cur.execute(
                            "SELECT Id FROM secrecs_own "
                            "WHERE ChallengeId=%s AND Sector=%s AND PlayerId=%s "
                            "ORDER BY Time ASC, Id ASC",
                            (challenge_id, sector, player_id),
                        )
                        ids = [int(r[0]) for r in await cur.fetchall()]
                        for delete_id in ids[1:]:
                            await cur.execute("DELETE FROM secrecs_own WHERE Id=%s", (delete_id,))
                            dup_removed += 1

            total_removed += dup_removed

    await _chat(f"[plugin_bestsecs.py] {total_removed} entries were removed from database in total.")
    logger.info("[BestSecs] cleanupdb removed %d entries", total_removed)


def _update_show_secrecs(aseco: "Aseco") -> None:
    global _show_secrecs
    mode = getattr(aseco.server.gameinfo, "mode", -1)
    _show_secrecs = bool(_cfg_window_enabled.get(mode, False))
