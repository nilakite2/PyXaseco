"""
plugin_donate.py — Port of plugins/plugin.donate.php

/donate <amount>  — Donates coppers to the server
/topdons          — Displays top 100 highest donators

Also exposes:
    admin_payment(aseco, login, target, amount)
    admin_pay(aseco, login, answer)
"""

from __future__ import annotations

import logging
from html import escape
from typing import TYPE_CHECKING

from pyxaseco.helpers import display_manialink_multi, format_text, strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

_bills: dict[int, tuple[str, str, int]] = {}

_payments: dict[str, tuple[str, int, str]] = {}

_mindonation = 10
_publicappr = 100
donation_values = [20, 50, 100, 200, 500, 1000, 2000]

ANSWER_PAY_YES = 2800001
ANSWER_PAY_NO = 2800002
ML_ID_PAYMENT = 2800000


def register(aseco: "Aseco"):
    aseco.register_event("onBillUpdated", bill_updated)
    aseco.register_event("onPlayerManialinkPageAnswer", donate_manialink)

    aseco.add_chat_command("donate", "Donates coppers to server")
    aseco.add_chat_command("topdons", "Displays top 100 highest donators")

    aseco.register_event("onChat_donate", chat_donate)
    aseco.register_event("onChat_topdons", chat_topdons)


async def _send_login(aseco: "Aseco", login: str, message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors(message),
        login,
    )


async def _send_all(aseco: "Aseco", message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessage",
        aseco.format_colors(message),
    )


def _server_is_tmf(aseco: "Aseco") -> bool:
    return getattr(aseco.server, "get_game", lambda: "")() == "TMF"


async def chat_donate(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login
    params = (command.get("params") or "").strip()

    if not _server_is_tmf(aseco):
        await _send_login(aseco, login, aseco.get_chat_message("FOREVER_ONLY"))
        return

    if not aseco.server.rights:
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("UNITED_ONLY"), "server"),
        )
        return

    if not getattr(player, "rights", False):
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("UNITED_ONLY"), "account"),
        )
        return

    if not params or not params.isdigit():
        await _send_login(aseco, login, aseco.get_chat_message("DONATE_HELP"))
        return

    coppers = int(params)
    if coppers < _mindonation:
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("DONATE_MINIMUM"), _mindonation),
        )
        return

    try:
        message = format_text(
            aseco.get_chat_message("DONATION"),
            coppers,
            aseco.server.name,
        )
        bill_id = await aseco.client.query(
            "SendBill",
            login,
            coppers,
            aseco.format_colors(message),
            "",
        )
        if bill_id is None:
            raise RuntimeError("SendBill returned no bill id")

        _bills[int(bill_id)] = (player.login, player.nickname, coppers)
    except Exception as e:
        logger.exception("[Donate] SendBill failed: %s", e)
        await _send_login(
            aseco,
            login,
            "{#server}> {#error}Could not start donation transaction.",
        )


async def admin_payment(aseco: "Aseco", login: str, target: str, amount):
    """
    Compatibility helper for admin payment flow.
    Can be called by admin/chat plugins later.
    """
    try:
        amount = int(amount)
    except Exception:
        amount = 0

    if not target or amount <= 0:
        await _send_login(aseco, login, aseco.get_chat_message("PAY_HELP"))
        return

    if target == aseco.server.serverlogin:
        await _send_login(aseco, login, aseco.get_chat_message("PAY_SERVER"))
        return

    try:
        coppers = int(await aseco.client.query("GetServerCoppers") or 0)
    except Exception:
        coppers = 0

    # Nadeo tax: 2 + 5%
    if amount > coppers - 2 - (amount * 5 // 100):
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("PAY_INSUFF"), coppers),
        )
        return

    label = format_text(aseco.get_chat_message("PAYMENT"), amount, target)
    _payments[login] = (target, amount, label)
    await _display_payment(aseco, login, aseco.server.nickname, label)


async def admin_pay(aseco: "Aseco", login: str, answer: bool):
    info = _payments.get(login)
    if not info:
        return

    target, amount, label = info

    if answer:
        try:
            bill_id = await aseco.client.query(
                "Pay",
                target,
                amount,
                aseco.format_colors(label),
            )
            if bill_id is None:
                raise RuntimeError("Pay returned no bill id")

            # Negative amount = server paid out
            _bills[int(bill_id)] = (login, target, -amount)
        except Exception as e:
            logger.exception("[Donate] Pay failed: %s", e)
            await _send_login(
                aseco,
                login,
                "{#server}> {#error}Payment transaction failed to start.",
            )
    else:
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("PAY_CANCEL"), target),
        )

    _payments.pop(login, None)
    await aseco.client.query_ignore_result("SendHideManialinkPageToLogin", login, ML_ID_PAYMENT)


async def bill_updated(aseco: "Aseco", bill: list):
    """
    bill = [BillId, State, StateName, TransactionId]
    State:
      4 = paid
      5 = refused
      6 = error
    """
    if not bill or len(bill) < 4:
        return

    bill_id = int(bill[0])
    state = int(bill[1])
    state_name = str(bill[2])
    tx_id = bill[3]

    if bill_id not in _bills:
        aseco.console("BillUpdated for unknown BillId {1} {2} (TxId {3})",
                      bill_id, state_name, tx_id)
        return

    login, nickname, coppers = _bills[bill_id]

    if state == 4:
        if coppers > 0:
            if coppers >= _publicappr:
                message = format_text(
                    aseco.get_chat_message("THANKS_ALL"),
                    aseco.server.name,
                    coppers,
                    nickname,
                )
                await _send_all(aseco, message)
            else:
                message = format_text(
                    aseco.get_chat_message("THANKS_YOU"),
                    coppers,
                )
                await _send_login(aseco, login, message)

            aseco.console(
                "Player {1} donated {2} coppers to this server (TxId {3})",
                login, coppers, tx_id
            )

            try:
                from pyxaseco.plugins.plugin_localdatabase import ldb_update_donations
                await ldb_update_donations(aseco, login, coppers)
            except Exception as e:
                logger.debug("[Donate] Could not update donations in DB: %s", e)

            await aseco.release_event("onDonation", [login, coppers])

        else:
            try:
                new_coppers = int(await aseco.client.query("GetServerCoppers") or 0)
            except Exception:
                new_coppers = 0

            message = format_text(
                aseco.get_chat_message("PAY_CONFIRM"),
                abs(coppers),
                nickname,
                new_coppers,
            )
            await _send_login(aseco, login, message)
            aseco.console(
                'Server paid {1} coppers to login "{2}" (TxId {3})',
                abs(coppers), login, tx_id
            )

        _bills.pop(bill_id, None)

    elif state == 5:
        await _send_login(aseco, login, "{#server}> {#error}Transaction refused!")
        aseco.console(
            'Refused transaction of {1} to login "{2}" (TxId {3})',
            coppers, login, tx_id
        )
        _bills.pop(bill_id, None)

    elif state == 6:
        message = "{#server}> {#error}Transaction failed: {#highlite}$i " + state_name
        if login:
            await _send_login(aseco, login, message)
        else:
            await _send_all(aseco, message)

        aseco.console(
            'Failed transaction of {1} to login "{2}" (TxId {3})',
            coppers, login, tx_id
        )
        _bills.pop(bill_id, None)


async def chat_topdons(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login

    if not _server_is_tmf(aseco):
        await _send_login(aseco, login, aseco.get_chat_message("FOREVER_ONLY"))
        return

    if not aseco.server.rights:
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("UNITED_ONLY"), "server"),
        )
        return

    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool

        pool = await get_pool()
        if not pool:
            await _send_login(aseco, login, "{#server}> {#error}Local database unavailable!")
            return

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT p.NickName, x.donations
                    FROM players p
                    LEFT JOIN players_extra x ON (p.Id = x.playerID)
                    WHERE x.donations <> 0
                    ORDER BY x.donations DESC
                    LIMIT 100
                    """
                )
                rows_db = await cur.fetchall()

        if not rows_db:
            await _send_login(aseco, login, "{#server}> {#error}No donator(s) found!")
            return

        rows = []
        for i, row in enumerate(rows_db, 1):
            nick = row[0] or ""
            if not getattr(aseco.settings, "lists_colornicks", False):
                nick = strip_colors(nick)
            rows.append([f"{i:02d}.", "{#black}" + nick, int(row[1] or 0)])

        player.msgs = [[
            1,
            "Current TOP 100 Donators:",
            [0.9, 0.1, 0.6, 0.2],
            ["Icons128x128_1", "Coppers", -0.01],
        ]]
        player.msgs.extend([rows[i:i + 15] for i in range(0, len(rows), 15)])
        display_manialink_multi(aseco, player)

    except Exception as e:
        logger.exception("[Donate] /topdons failed: %s", e)
        await _send_login(
            aseco,
            login,
            "{#server}> {#error}Error loading donators list.",
        )


async def donate_manialink(aseco: "Aseco", answer: list):
    """Handles the payment confirmation dialog."""
    if len(answer) < 3:
        return

    login = answer[1]
    try:
        action = int(answer[2])
    except Exception:
        return

    if action == ANSWER_PAY_YES:
        await admin_pay(aseco, login, True)
    elif action == ANSWER_PAY_NO:
        await admin_pay(aseco, login, False)


async def _display_payment(aseco: "Aseco", login: str, server: str, label: str):
    server_xml = escape(server or "", {'"': "&quot;"})
    label_xml = escape(label or "", {'"': "&quot;"})

    xml = (
        f'<manialink id="{ML_ID_PAYMENT}"><frame pos="0.5 0.15 0">'
        '<quad size="1.0 0.3" style="Bgs1" substyle="BgWindow3"/>'
        f'<label pos="-0.04 -0.04 -0.2" textsize="2" text="$fffInitiating payment from server {server_xml}$z $fff:"/>'
        f'<label pos="-0.04 -0.08 -0.2" textsize="2" text="$fffLabel: {label_xml}"/>'
        '<label pos="-0.04 -0.12 -0.2" textsize="2" text="$fffWould you like to pay?"/>'
        f'<label pos="-0.27 -0.19 -0.2" halign="center" style="CardButtonMedium" text="Yes" action="{ANSWER_PAY_YES}"/>'
        f'<label pos="-0.73 -0.19 -0.2" halign="center" style="CardButtonMedium" text="No" action="{ANSWER_PAY_NO}"/>'
        '</frame></manialink>'
    )
    await aseco.client.query_ignore_result(
        "SendDisplayManialinkPageToLogin",
        login,
        aseco.format_colors(xml),
        0,
        True,
    )

async def chat_admin_donate(aseco: "Aseco", command: dict):
    player = command["author"]
    login = player.login
    params = command.get("params") or []

    # params usually: ['coppers'] or ['pay', '<login>', '<amount>']
    if isinstance(params, str):
        parts = [p for p in params.split() if p]
    else:
        parts = list(params)

    if not parts:
        await _send_login(aseco, login, aseco.get_chat_message("PAY_HELP"))
        return

    sub = str(parts[0]).lower()

    if not _server_is_tmf(aseco):
        await _send_login(aseco, login, aseco.get_chat_message("FOREVER_ONLY"))
        return

    if not aseco.server.rights:
        await _send_login(
            aseco,
            login,
            format_text(aseco.get_chat_message("UNITED_ONLY"), "server"),
        )
        return

    if sub == "coppers":
        try:
            coppers = int(await aseco.client.query("GetServerCoppers") or 0)
        except Exception:
            coppers = 0
        msg = format_text(
            aseco.get_chat_message("COPPERS"),
            aseco.server.name,
            coppers,
        )
        await _send_login(aseco, login, msg)
        return

    if sub == "pay":
        target = parts[1] if len(parts) > 1 else ""
        amount = parts[2] if len(parts) > 2 else ""
        await admin_payment(aseco, login, target, amount)
        return

    await _send_login(aseco, login, aseco.get_chat_message("PAY_HELP"))
