"""
chat_players2.py — Port of plugins/chat.players2.php

/ranks     — Displays list of online ranks/nicks
/clans     — Displays list of online clans/nicks
/topclans  — Displays top ranked clans
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink, display_manialink_multi, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)


def register(aseco: "Aseco"):
    aseco.add_chat_command("ranks", "Displays list of online ranks/nicks")
    aseco.add_chat_command("clans", "Displays list of online clans/nicks")
    aseco.add_chat_command("topclans", "Displays top ranked clans")

    aseco.register_event("onChat_ranks", chat_ranks)
    aseco.register_event("onChat_clans", chat_clans)
    aseco.register_event("onChat_topclans", chat_topclans)


async def _get_rank_value(login: str) -> int | None:
    """
    Return numeric server rank position for a login, or None if unranked.
    """
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool, get_player_id

        pool = await get_pool()
        if not pool:
            return None

        pid = await get_player_id(login)
        if not pid:
            return None

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT avg FROM rs_rank WHERE playerID=%s", (pid,))
                row = await cur.fetchone()
                if not row:
                    return None

                my_avg = row[0]
                await cur.execute("SELECT COUNT(*) FROM rs_rank WHERE avg < %s", (my_avg,))
                better = await cur.fetchone()
                return int((better[0] if better else 0) + 1)
    except Exception as e:
        logger.debug("[chat_players2] rank lookup failed for %s: %s", login, e)
        return None


async def chat_ranks(aseco: "Aseco", command: dict):
    player: Player = command["author"]

    ranked_players: list[tuple[int, str, str]] = []
    unranked_players: list[tuple[str, str]] = []

    for pl in aseco.server.players.all():
        rank = await _get_rank_value(pl.login)
        if rank is None:
            unranked_players.append((pl.login, pl.nickname))
        else:
            ranked_players.append((rank, pl.login, pl.nickname))

    ranked_players.sort(key=lambda x: (x[0], strip_colors(x[2]).lower(), x[1].lower()))
    unranked_players.sort(key=lambda x: (strip_colors(x[1]).lower(), x[0].lower()))

    rows = []
    for rank, _login, nickname in ranked_players:
        rows.append([f"{{#login}}{rank}", f"{{#black}}{nickname}"])
    for _login, nickname in unranked_players:
        rows.append(["{#grey}<none>", f"{{#black}}{nickname}"])

    if not rows:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors("{#server}> {#error}No player(s) found!"),
            player.login,
        )
        return

    player.msgs = [[
        1,
        "Online Ranks ({#login}rank $g/{#nick} nick$g):",
        [0.8, 0.15, 0.65],
        ["Icons128x128_1", "Buddies"],
    ]]
    player.msgs.extend([rows[i:i + 15] for i in range(0, len(rows), 15)])
    display_manialink_multi(aseco, player)


async def chat_clans(aseco: "Aseco", command: dict):
    player: Player = command["author"]

    clan_entries: list[tuple[str, str]] = []
    no_clan_entries: list[tuple[str, str]] = []

    for pl in aseco.server.players.all():
        clan = (pl.teamname or "").strip()
        if clan:
            clan_entries.append((clan, pl.nickname))
        else:
            no_clan_entries.append((pl.login, pl.nickname))

    clan_entries.sort(key=lambda x: (strip_colors(x[0]).lower(), strip_colors(x[1]).lower()))
    no_clan_entries.sort(key=lambda x: (strip_colors(x[1]).lower(), x[0].lower()))

    rows = []
    for clan, nickname in clan_entries:
        rows.append([f"{{#login}}{clan}", f"{{#black}}{nickname}"])
    for _login, nickname in no_clan_entries:
        rows.append(["{#grey}<none>", f"{{#black}}{nickname}"])

    if not rows:
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors("{#server}> {#error}No player(s) found!"),
            player.login,
        )
        return

    player.msgs = [[
        1,
        "Online Clans ({#login}clan $g/{#nick} nick$g):",
        [1.3, 0.65, 0.65],
        ["Icons128x128_1", "Buddies"],
    ]]
    player.msgs.extend([rows[i:i + 15] for i in range(0, len(rows), 15)])
    display_manialink_multi(aseco, player)


async def chat_topclans(aseco: "Aseco", command: dict):
    player: Player = command["author"]

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool

        pool = await get_pool()
        if not pool:
            await aseco.client.query_ignore_result(
                "ChatSendServerMessageToLogin",
                aseco.format_colors("{#server}> {#error}Local database unavailable!"),
                player.login,
            )
            return

        min_players = int(getattr(aseco.settings, "topclans_minplayers", 2) or 2)

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT TeamName, cnt, teamrank
                    FROM (
                        SELECT
                            p.TeamName AS TeamName,
                            COUNT(r.avg) AS cnt,
                            SUM(r.avg) / COUNT(r.avg) AS teamrank
                        FROM players p
                        JOIN rs_rank r ON p.Id = r.playerID
                        WHERE p.TeamName <> ''
                        GROUP BY p.TeamName
                    ) AS sub
                    WHERE sub.cnt >= %s
                    ORDER BY sub.teamrank ASC
                    LIMIT 10
                    """,
                    (min_players,),
                )
                result = await cur.fetchall()

        if not result:
            await aseco.client.query_ignore_result(
                "ChatSendServerMessageToLogin",
                aseco.format_colors("{#server}> {#error}No clan(s) found!"),
                player.login,
            )
            return

        rows = []
        for i, row in enumerate(result, 1):
            team_name = row[0] or "<none>"
            count = int(row[1] or 0)
            avg = float(row[2] or 0.0) / 10000.0
            rows.append([
                f"{i}.",
                f"{{#black}}{team_name}$z $n({count})$m",
                f"{avg:4.1f}",
            ])

        header = f"Current TOP 10 Clans $n(min. {min_players} players)$m:"
        display_manialink(
            aseco,
            player.login,
            header,
            ["BgRaceScore2", "Podium"],
            rows,
            [0.95, 0.1, 0.7, 0.15],
            "OK",
        )

    except Exception as e:
        logger.exception("[chat_players2] topclans failed: %s", e)
        await aseco.client.query_ignore_result(
            "ChatSendServerMessageToLogin",
            aseco.format_colors("{#server}> {#error}Error loading clan rankings."),
            player.login,
        )