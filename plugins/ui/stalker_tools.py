"""
plugin_stalker_tools.py - port of stalker.tools.php

Implements:
- /st command group
- /chatall extended chat history
- PM forwarding
- chat hide/show via custom UI
- force spectator/player state helpers
- basic custom vote wrapper via CallVoteEx
- FuFi menu integration
"""

from __future__ import annotations

import html
import logging
import re
import shlex
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyxaseco.helpers import ML_ID_MAIN, display_manialink_multi, format_text, strip_colors, strip_sizes

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

PLUGIN_NAME = "STALKER's Tools"
PLUGIN_PREFIX = "$w$s$f00S$f80T$ff0A$0F0L$0FFK$00FE$009R$z$s"
CHATALL_WRAP = 80
CHATALL_PAGE = 15
CHAT_HIDE_MLID = 998877
_st_state: "_StalkerToolsState | None" = None


def _plugin_module(module_name: str):
    try:
        return __import__(f"pyxaseco.plugins.{module_name}", fromlist=["*"])
    except ImportError:
        return __import__(f"pyxaseco_plugins.{module_name}", fromlist=["*"])


def _ensure_player_state(player: "Player") -> dict[str, Any]:
    state = getattr(player, "st", None)
    if not isinstance(state, dict):
        state = {}
        player.st = state
    state.setdefault("spectarget", "")
    state.setdefault("fstate", 0)
    state.setdefault("fwdpms", False)
    return state


def _flatten_vote_response(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, tuple):
        return list(result)
    if isinstance(result, dict):
        return list(result.values())
    return [result]


def _strip_nick(nick: str) -> str:
    return str(nick or "").replace("$w", "").replace("$W", "")


def _is_masteradmin(aseco: "Aseco", player: "Player") -> bool:
    vals = getattr(aseco.settings, "masteradmin_list", {}).get("TMLOGIN", [])
    return str(player.login or "").lower() in {str(v).lower() for v in vals}


def _player_by_id(aseco: "Aseco", pid: int) -> "Player | None":
    for player in aseco.server.players.all():
        if getattr(player, "id", None) == pid:
            return player
    return None


def _safe_export_name(name: str) -> str | None:
    if not name:
        return None
    if re.search(r'(?:[\\/:*?"<>|&])|(?:\.{2})|^(?:NUL{1,2})$', name, flags=re.I):
        return None
    return name if "." in name else f"{name}.txt"


def _vote_xml(message: str) -> str:
    esc = html.escape(message, quote=False)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<methodCall>"
        "<methodName>Echo</methodName>"
        "<params>"
        f"<param><value><string>{esc}</string></value></param>"
        "<param><value><string>st_custom_vote</string></value></param>"
        "</params>"
        "</methodCall>"
    )


async def _send_login(aseco: "Aseco", login: str, message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        aseco.format_colors(message),
        login,
    )


async def _send_global(aseco: "Aseco", message: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessage",
        aseco.format_colors(message),
    )


async def _set_chat_visible(aseco: "Aseco", login: str, visible: bool):
    xml = (
        "<manialinks>"
        f"<manialink id=\"{CHAT_HIDE_MLID}\">"
        f"<custom_ui><chat visible=\"{'true' if visible else 'false'}\"/></custom_ui>"
        "</manialink>"
        "</manialinks>"
    )
    await aseco.client.query_ignore_result(
        "SendDisplayManialinkPageToLogin",
        login,
        xml,
        0,
        False,
    )


@dataclass
class _CustomVote:
    callback: str = ""
    caller: str = ""
    passed: bool = False
    running: bool = False


@dataclass
class _StalkerToolsState:
    aseco: "Aseco"
    chat_ignored: dict[str, float] = field(default_factory=dict)
    player_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    gamelog: list[tuple[int, tuple[tuple[str, str], str], int]] = field(default_factory=list)
    fstates: dict[str, int] = field(default_factory=dict)
    custom_vote: _CustomVote = field(default_factory=_CustomVote)
    uservote_command: list[str] | str = ""
    uservote_fail_command: list[str] | str = ""
    check_vote_every: float = 0.5
    nextvote_check: float = field(default_factory=lambda: time.monotonic() + 0.5)
    vote_released_event: bool = False

    def set_st_playerinfo(self, player: "Player", infos: dict[str, Any]):
        state = _ensure_player_state(player)
        pdata = self.player_data.setdefault(player.login, {})
        for key, value in infos.items():
            if value is None:
                state.pop(key, None)
                pdata.pop(key, None)
            else:
                state[key] = value
                pdata[key] = value

    def log_chat(self, chat: list):
        if len(chat) < 3:
            return
        uid, login, text = chat[0], chat[1], chat[2]
        if uid == self.aseco.server.id or not text:
            return
        if len(chat) >= 5 and chat[4]:
            return
        player = self.aseco.server.players.get_player(login)
        if not player:
            return
        self.gamelog.append((1, ((player.login, _strip_nick(player.nickname)), text), int(time.time())))
        if len(self.gamelog) > 1000:
            self.gamelog = self.gamelog[-1000:]

    async def clean_chat(self):
        for login in list(self.chat_ignored.keys()):
            if not self.aseco.server.players.get_player(login):
                continue
            for _ in range(30):
                await self.aseco.client.query_ignore_result("ChatSendServerMessageToLogin", "", login)

    async def customui_refresh(self):
        now = time.time()
        for login, expires in list(self.chat_ignored.items()):
            player = self.aseco.server.players.get_player(login)
            if expires > 0 and expires <= now:
                self.chat_ignored.pop(login, None)
                await _set_chat_visible(self.aseco, login, True)
                if player:
                    message = format_text(
                        "{#server}>> {#admin}Chat was enabled for {1}$z$s{#admin} !",
                        _strip_nick(player.nickname),
                    )
                    await _send_global(self.aseco, message)
                continue
            if player:
                await _set_chat_visible(self.aseco, login, False)

    def return_gamelog(self, options: list[str] | tuple[str, ...] | None = None):
        options = list(options or ["default"])
        show_chat = True
        keep_formatting = False
        keep_colors = False
        include_commands = False
        for option in options:
            if option == "default":
                show_chat = True
                keep_formatting = False
                keep_colors = False
                include_commands = False
            elif option == "-chat":
                show_chat = False
            elif option == "+formating":
                keep_formatting = True
            elif option == "+colors":
                keep_colors = True
            elif option in {"+coms", "+commands"}:
                include_commands = True
            else:
                return False

        out = []
        for item in self.gamelog:
            kind, ((login, nick), text), stamp = item
            if kind == 1 and not show_chat:
                continue
            if text.startswith("/") and not include_commands:
                continue

            if keep_formatting:
                out.append(item)
                continue

            clean_nick = nick
            clean_text = text
            if keep_colors:
                clean_nick = re.sub(r"\$(?:i|s|t|w|n|m|g|z|h|o|l)", "", strip_sizes(clean_nick), flags=re.I)
                clean_text = re.sub(r"\$(?:i|s|t|w|n|m|g|z|h|o|l)", "", strip_sizes(clean_text), flags=re.I)
            else:
                clean_nick = strip_colors(clean_nick, for_tm=False)
                clean_text = strip_colors(clean_text, for_tm=False)
            out.append((kind, ((login, clean_nick), clean_text), stamp))
        return out

    async def poll_vote(self):
        now = time.monotonic()
        if now < self.nextvote_check:
            return
        self.nextvote_check = now + self.check_vote_every

        try:
            result = await self.aseco.client.query("GetCurrentCallVote")
        except Exception as exc:
            logger.debug("[StalkerTools] GetCurrentCallVote failed: %s", exc)
            return

        flat = _flatten_vote_response(result)
        vote_type = str(flat[1] if len(flat) > 1 else "" or "")

        if not vote_type:
            if self.vote_released_event:
                self.vote_released_event = False
                await st_check_custom_vote_fail(self.aseco)
            return

        if not self.vote_released_event:
            await st_protect_admins(self.aseco, flat)
            self.vote_released_event = True

    async def run_custom_vote(
        self,
        text: str,
        handler: str = "",
        caller: str = "",
        timeout: int = 0,
        ratio: float = -1,
        voters: int = 1,
    ) -> bool:
        try:
            ok = await self.aseco.client.query(
                "CallVoteEx",
                _vote_xml(text),
                float(ratio),
                int(timeout),
                int(voters),
            )
        except Exception as exc:
            logger.debug("[StalkerTools] CallVoteEx failed: %s", exc)
            ok = False

        if not ok:
            player = self.aseco.server.players.get_player(caller)
            if player:
                await _send_login(self.aseco, caller, "{#server}> {#error}Unable to start vote!")
            return False

        self.custom_vote.running = True
        self.custom_vote.caller = caller
        self.custom_vote.callback = handler
        self.custom_vote.passed = False
        return True


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", st_startup)
    aseco.register_event("onStartup", init_st)
    aseco.register_event("onPlayerConnect", st_clean_manialinks)
    aseco.register_event("onPlayerConnect", st_newplayer_init)
    aseco.register_event("onPlayerDisconnect", st_player_disconnect)
    aseco.register_event("onPlayerInfoChanged", st_playerinfochanged)
    aseco.register_event("onChat", st_log_all)
    aseco.register_event("onChat", st_fwdpms)
    aseco.register_event("onNewChallenge", st_close_manialinks)
    aseco.register_event("onShutdown", st_clean_chat)
    aseco.register_event("onShutdown", st_clean_manialinks)
    aseco.register_event("onShutdown", st_clean_music)
    aseco.register_event("onStartup", st_customui_refresh)
    aseco.register_event("onEverySecond", st_customui_refresh)
    aseco.register_event("onNewChallenge", st_customui_refresh)
    aseco.register_event("onEndRace", st_customui_refresh)
    aseco.register_event("onBeginRound", st_customui_refresh)
    aseco.register_event("onPlayerFinish1", st_customui_refresh)
    aseco.register_event("onMenuLoaded", st_init_menu)
    aseco.register_event("onMainLoop", st_check_vote)
    aseco.register_event("onEcho", st_check_custom_vote)

    aseco.add_chat_command("chatall", "Displays full chat history")
    aseco.add_chat_command("st", "STALKER's Tools commands (see: /st help)", is_admin=True)
    aseco.register_event("onChat_chatall", chat_chatall)
    aseco.register_event("onChat_st", chat_st)


async def st_startup(aseco: "Aseco", _command=None):
    global _st_state
    if getattr(aseco.server, "get_game", lambda: "")() != "TMF":
        logger.warning("[%s] Unsupported TM version", PLUGIN_NAME)
    _st_state = _StalkerToolsState(aseco)
    setattr(aseco.server, "stalker_tools", _st_state)


async def init_st(aseco: "Aseco", _command=None):
    await _send_global(
        aseco,
        "$z$s>> $w$s$f00S$f80T$ff0A$0F0L$0FFK$00FE$009R$z$fff$s's tools $z$s1.$s1b$fff $sloaded$z$s.",
    )
    aseco.console_text("[STALKER's Tools] Starting...")
    aseco.console_text("[STALKER's Tools] Running...")


async def st_newplayer_init(aseco: "Aseco", player: "Player"):
    global _st_state
    if _st_state is None:
        return
    saved = dict(_st_state.player_data.get(player.login, {}))
    state = _ensure_player_state(player)
    state.update(saved)
    state.setdefault("spectarget", "")
    state["fstate"] = int(_st_state.fstates.get(player.login, state.get("fstate", 0)) or 0)
    state.setdefault("fwdpms", False)
    _st_state.player_data[player.login] = dict(state)


async def st_player_disconnect(aseco: "Aseco", player: "Player"):
    global _st_state
    if _st_state is None:
        return
    pdata = _st_state.player_data.get(player.login, {})
    if not pdata:
        _st_state.player_data.pop(player.login, None)


async def st_playerinfochanged(aseco: "Aseco", player: "Player"):
    global _st_state
    if _st_state is None or not player:
        return
    state = _ensure_player_state(player)
    if not getattr(player, "isspectator", False):
        state["spectarget"] = ""

    forced = int(state.get("fstate", 0) or 0)
    if forced == 0:
        return
    desired_spec = forced == 1
    if bool(getattr(player, "isspectator", False)) == desired_spec:
        return
    await aseco.client.query_ignore_result("ForceSpectator", player.login, forced)


async def st_log_all(aseco: "Aseco", chat: list):
    global _st_state
    if _st_state is not None:
        _st_state.log_chat(chat)


async def st_close_manialinks(aseco: "Aseco", _data=None):
    try:
        xml = f'<manialink id="{ML_ID_MAIN}"></manialink>'
        await aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)
    except Exception:
        pass


async def st_clean_chat(aseco: "Aseco", _data=None):
    global _st_state
    if _st_state is not None:
        await _st_state.clean_chat()


async def st_clean_manialinks(aseco: "Aseco", data=None):
    if data is None:
        await aseco.client.query_ignore_result("SendHideManialinkPage")
        return
    login = getattr(data, "login", getattr(data, "player", ""))
    if login:
        xml = f'<manialink id="{ML_ID_MAIN}"></manialink>'
        await aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)


async def st_clean_music(aseco: "Aseco", _data=None):
    await aseco.client.query_ignore_result("SetForcedMusic", False, "")


async def st_customui_refresh(aseco: "Aseco", _data=None):
    global _st_state
    if _st_state is not None:
        await _st_state.customui_refresh()


def return_gamelog(options: list[str] | tuple[str, ...] | None = None):
    global _st_state
    if _st_state is None:
        return []
    return _st_state.return_gamelog(options)


async def st_init_menu(aseco: "Aseco", menu):
    try:
        menu.addEntry("", "", True, "STALKER Tools", "stalkertools", "", "", "stalkertools")
        menu.addEntry("stalkertools", "", True, "Show full chat history", "st_chatall", "/chatall")
        menu.addEntry("stalkertools", "", True, "Clear chatlog", "st_clear_chatall", "/st cc all")
        menu.addEntry("stalkertools", "", True, "List chat-disabled players", "st_listignores", "/st listignores")
        menu.addEntry("stalkertools", "", True, "Clear chat-disabled players", "st_cleanignores", "/st cleanignores")
        menu.addEntry("stalkertools", "", True, "Show fstated players", "st_fstates", "/st fstated")
        menu.addEntry("stalkertools", "", True, "Forward PMs to you", "st_toggle_fwdpms", "/st fwdpms toggle", "", "", "st_get_fwdpms_indicator")
        menu.addSeparator("stalkertools", "", True, "st_help_separator")
        menu.addEntry("stalkertools", "", True, "Help", "st_help", "/st help", "", "", "", "", "help")
    except Exception as exc:
        logger.debug("[StalkerTools] FuFi menu integration failed: %s", exc)


def st_get_fwdpms_indicator(aseco: "Aseco", login: str):
    global _st_state
    player = aseco.server.players.get_player(login)
    if not player or _st_state is None:
        return -1
    state = _ensure_player_state(player)
    if not state.get("fwdpms", False):
        return 0
    if bool(_st_state.player_data.get(login, {}).get("fwdpms", False)):
        return 1
    return 2


async def st_check_vote(aseco: "Aseco", _data=None):
    global _st_state
    if _st_state is not None:
        await _st_state.poll_vote()


async def st_check_custom_vote(aseco: "Aseco", echo: list):
    global _st_state
    if _st_state is None:
        return
    if "st_custom_vote" not in [str(item) for item in (echo or [])]:
        return
    if _st_state.custom_vote.callback == "st_custom_user_vote":
        await st_custom_user_vote(aseco, True, _st_state.custom_vote.caller)
    _st_state.custom_vote.callback = ""
    _st_state.custom_vote.passed = True
    _st_state.custom_vote.running = False
    _st_state.custom_vote.caller = ""


async def st_check_custom_vote_fail(aseco: "Aseco"):
    global _st_state
    if _st_state is None:
        return
    if _st_state.custom_vote.passed:
        _st_state.custom_vote.passed = False
        return
    if not _st_state.custom_vote.running:
        return
    if _st_state.custom_vote.callback == "st_custom_user_vote":
        await st_custom_user_vote(aseco, False, _st_state.custom_vote.caller)
    _st_state.custom_vote.callback = ""
    _st_state.custom_vote.running = False
    _st_state.custom_vote.passed = False
    _st_state.custom_vote.caller = ""


async def chat_ui_send(aseco: "Aseco", login: str, state: bool = True):
    await _set_chat_visible(aseco, login, state)


async def st_protect_admins(aseco: "Aseco", vote: list):
    vote_type = str(vote[1] if len(vote) > 1 else "" or "")
    if vote_type not in {"Kick", "Ban"}:
        return

    target_login = str(vote[2] if len(vote) > 2 else "" or "")
    caller_login = str(vote[0] if len(vote) > 0 else "" or "")
    target = aseco.server.players.get_player(target_login)
    if not target:
        return
    if not (aseco.allow_ability(target, "stalkertools") or aseco.allow_ability(target, "st_vote_protect")):
        return

    caller = aseco.server.players.get_player(caller_login)
    do_kick = True
    if caller and aseco.allow_ability(caller, "stalkertools"):
        do_kick = False

    message = format_text(
        "{#server}>> {#admin}{1}$z$s{#admin} tried to {2} {3}$z$s{#admin}!{4}",
        _strip_nick(caller.nickname) if caller else caller_login,
        vote_type.lower(),
        _strip_nick(target.nickname),
        " {#error}[Kicked]" if do_kick and caller else "",
    )
    await aseco.client.query_ignore_result("CancelVote")
    await _send_global(aseco, message)
    if caller and not do_kick:
        warn = format_text(
            "{#server}> {#admin}Don't be silly, {1}$z$s{#admin} ! ;)",
            _strip_nick(caller.nickname),
        )
        await _send_login(aseco, caller.login, warn)
    if caller and do_kick:
        await aseco.client.query_ignore_result("Kick", caller.login)


async def st_fwdpms(aseco: "Aseco", chat: list):
    global _st_state
    if _st_state is None or len(chat) < 3:
        return

    uid, login, text = chat[0], chat[1], str(chat[2] or "")
    if uid == aseco.server.id or not text:
        return
    if not text.strip().lower().startswith("/pm "):
        return

    parts = text.strip()[4:].split(" ", 1)
    if len(parts) < 2:
        return

    sender = aseco.server.players.get_player(login)
    receiver = aseco.server.players.get_player(parts[0])
    if not sender or not receiver:
        return

    msg = aseco.format_colors(
        "$f00-PM- "
        + _strip_nick(sender.nickname)
        + " $z$s$0F0=>"
        + _strip_nick(receiver.nickname)
        + "$z$s$f00:$fff "
        + parts[1]
    )

    for player in aseco.server.players.all():
        state = _ensure_player_state(player)
        if not state.get("fwdpms", False):
            continue
        if player.login in {sender.login, receiver.login}:
            continue
        await aseco.client.query_ignore_result("ChatSendServerMessageToLogin", msg, player.login)


async def st_custom_user_vote(aseco: "Aseco", passed: bool, caller_login: str):
    global _st_state
    if _st_state is None:
        return
    caller = aseco.server.players.get_player(caller_login)
    commands = _st_state.uservote_command if passed else _st_state.uservote_fail_command
    if caller:
        await _send_login(
            aseco,
            caller.login,
            "{#server}> $0f0Vote passed!" if passed else "{#server}> $f00Vote failed!",
        )
    await fake_server_chat(aseco, caller_login, commands)
    _st_state.uservote_command = ""
    _st_state.uservote_fail_command = ""


async def fake_server_chat(aseco: "Aseco", caller_login: str, command: list[str] | str):
    if isinstance(command, list):
        for item in command:
            await fake_server_chat(aseco, caller_login, item)
        return
    cmd = str(command or "").strip()
    if not cmd:
        return
    await aseco.dispatch_chat_command(caller_login, cmd)


async def chat_chatall(aseco: "Aseco", command: dict):
    global _st_state
    if _st_state is None:
        return
    player = command["author"]
    params = (command.get("params") or "").strip().split(" ", 1)[0]

    if params == "help":
        await _send_login(aseco, player.login, "{#server}> {#error}Usage: /chatall [page]")
        return

    if not (
        aseco.allow_ability(player, "stalkertools")
        or aseco.allow_ability(player, "st_chatall")
        or aseco.is_any_admin(player)
    ):
        aseco.console(f"{player.login} tried to use STALKER Tools (no permission!): {command.get('params','')}")
        await aseco.client.query_ignore_result("ChatSendToLogin", "$f00You don't have the required admin rights to do that!", player.login)
        return

    st_log = _st_state.return_gamelog(["+coms", "+colors", "+formating"])
    if params and not params.isdigit():
        await _send_login(aseco, player.login, f"{{#server}}> {{#error}}{{#highlite}}$i{params}{{#error}} is not a number!")
        return

    if not st_log:
        await _send_login(aseco, player.login, "{#server}> {#error}No chat history found!")
        return

    player.msgs = [[1 if not params else int(params), "Full chat history:", [1.2], ["Icons64x64_1", "Outbox"]]]
    page_rows: list[list[str]] = []
    page_line_count = 0
    show_times = bool(getattr(aseco.settings, "chatpmlog_times", False))
    for _, ((_, nick), text), stamp in st_log:
        wrapped = textwrap.wrap(str(text), CHATALL_WRAP) or [""]
        for idx, line in enumerate(wrapped):
            prefix = f"<{{#server}}{time.strftime('%H:%M:%S', time.localtime(stamp))}$z> " if show_times else ""
            label = f"[{{#black}}{nick}$z] " if idx == 0 else "..."
            page_rows.append([f"$z{prefix}{label}{line[:CHATALL_WRAP + 16]}"])
            page_line_count += 1
            if page_line_count > 14:
                player.msgs.append(page_rows)
                page_rows = []
                page_line_count = 0
    if page_rows:
        player.msgs.append(page_rows)
    display_manialink_multi(aseco, player)


async def chat_st(aseco: "Aseco", command: dict):
    global _st_state
    if _st_state is None:
        return

    player = command["author"]
    params_raw = str(command.get("params") or "").strip()
    if not (aseco.allow_ability(player, "stalkertools") or aseco.is_any_admin(player)):
        aseco.console(f"{player.login} tried to use STALKER Tools (no permission!): {params_raw}")
        await aseco.client.query_ignore_result("ChatSendToLogin", "$f00You don't have the required admin rights to do that!", player.login)
        return

    arglist = params_raw.split(" ", 1)
    sub = arglist[0].lower() if arglist and arglist[0] else ""
    rest = arglist[1] if len(arglist) > 1 else ""
    pstate = _ensure_player_state(player)

    if sub in {"help", "about"}:
        await _send_login(aseco, player.login, "$w$s$f00S$f80T$ff0A$0F0L$0FFK$00FE$009R$z$s's tools:")
        await _send_login(aseco, player.login, "$z$s$ifwdpms, chatall, cc, ce, ignore, unignore, listignores, cleanignores, fstate, fstates, specme, vote")
        return

    if sub == "fwdpms":
        option = rest.strip().lower()
        if option == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st fwdpms <ON|OFF|permanent|toggle>")
            return
        if option == "on":
            _st_state.set_st_playerinfo(player, {"fwdpms": False})
            pstate["fwdpms"] = True
        elif option == "off":
            _st_state.set_st_playerinfo(player, {"fwdpms": False})
            pstate["fwdpms"] = False
        elif option == "permanent":
            _st_state.set_st_playerinfo(player, {"fwdpms": True})
            pstate["fwdpms"] = True
        elif option == "toggle":
            if pstate.get("fwdpms", False):
                _st_state.set_st_playerinfo(player, {"fwdpms": False})
                pstate["fwdpms"] = False
            else:
                pstate["fwdpms"] = True

        permanent = bool(_st_state.player_data.get(player.login, {}).get("fwdpms", False))
        message = (
            "{#server}> {#message}Forwading private messages for you is: "
            "{#highlite}"
            + ("ON" if pstate.get("fwdpms", False) else "OFF")
            + (" (permanent)" if permanent else "")
            + "$z$s{#message}."
        )
        await _send_login(aseco, player.login, message)
        return

    if sub == "chatall":
        await chat_chatall(aseco, {"author": player, "params": rest.strip()})
        return

    if sub == "cc":
        if rest.strip() == "all":
            if not _is_masteradmin(aseco, player):
                aseco.console(f"{player.login} tried to use STALKER Tools (no permission!): {params_raw}")
                await aseco.client.query_ignore_result("ChatSendToLogin", "$f00You don't have the required admin rights to do that!", player.login)
                return
            try:
                chatlog_mod = _plugin_module("plugin_chatlog")
                if hasattr(chatlog_mod, "_chatbuf"):
                    chatlog_mod._chatbuf.clear()
            except Exception:
                pass
            _st_state.gamelog.clear()
            await _send_login(aseco, player.login, "{#server}> $0f0Public chatlog cleared!")
            await _send_login(aseco, player.login, "{#server}> $0f0Full chatlog cleared!")
            return
        if not rest.strip():
            try:
                chatlog_mod = _plugin_module("plugin_chatlog")
                if hasattr(chatlog_mod, "_chatbuf"):
                    chatlog_mod._chatbuf.clear()
            except Exception:
                pass
            await _send_login(aseco, player.login, "{#server}> $0f0Public chatlog cleared!")
            return
        await _send_login(aseco, player.login, '{#server}> {#error}Usage: "/st cc" or "/st cc all"')
        return

    if sub == "ce":
        parts = rest.split(" ", 1)
        filename = _safe_export_name(parts[0] if parts else "")
        if not filename:
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st ce <file> [options]")
            await _send_login(aseco, player.login, "{#server}> {#error}Available options are: {#highlite}$iall$i $fc0(chatlog + commands), {#highlite}$i+coms$i $fc0(add commands), {#highlite}$i+colors$i $fc0(add color codes), {#highlite}$i+formating$i $fc0(add formatting codes)")
            return
        opts_raw = parts[1] if len(parts) > 1 else ""
        valid = {"+coms", "+commands", "+colors", "+formating", "all"}
        opts = [o for o in opts_raw.split(" ") if o]
        for opt in opts:
            if opt not in valid:
                await _send_login(aseco, player.login, f"{{#server}}> {{#error}}Unkown parameter {{#highlite}}$i{opt}{{#error}} !")
                return
        export_path = Path(getattr(aseco, "_base_dir", ".")) / filename
        if export_path.exists():
            await _send_login(aseco, player.login, f"{{#server}}> {{#error}}File {{#highlite}}$i{filename}{{#error}} already exists!")
            return
        oparams = []
        if "all" in opts or "+coms" in opts or "+commands" in opts:
            oparams.append("+coms")
        if "+colors" in opts:
            oparams.append("+colors")
        if "+formating" in opts:
            oparams.append("+formating")
        log_rows = _st_state.return_gamelog(oparams)
        try:
            with export_path.open("w", encoding="utf-8", newline="") as fh:
                for _, ((login, _nick), text), stamp in log_rows:
                    line = f"[{time.strftime('%Y/%m/%d %H:%M:%S', time.localtime(stamp))}] {login} : {text}\r\n"
                    fh.write(line)
        except Exception:
            await _send_login(aseco, player.login, f"{{#server}}> {{#error}}Can't open file {{#highlite}}$i{filename}{{#error}} !")
            return
        await _send_login(aseco, player.login, f"{{#server}}> $0f0Log exported to file {{#highlite}}{filename} $0f0!")
        return

    if sub == "ignore":
        parts = rest.split(" ", 1)
        target_param = parts[0] if parts else ""
        duration_raw = parts[1] if len(parts) > 1 else ""
        if not target_param or target_param == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st ignore <login> [time_in_minutes]")
            return
        target = aseco.server.players.get_player(target_param)
        if not target:
            return
        if aseco.allow_ability(target, "stalkertools") or aseco.allow_ability(target, "st_vote_protect"):
            await _send_login(aseco, player.login, "{#server}> {#error}Can't ignore!")
            return
        if target.login in _st_state.chat_ignored:
            await _send_login(aseco, player.login, "{#server}> {#error}Already on ignore list!")
            return
        expires = 0.0
        if duration_raw:
            duration_raw = duration_raw.replace(",", ".")
            if not re.fullmatch(r"\d+(?:\.\d+)?", duration_raw):
                await _send_login(aseco, player.login, f"{{#server}}> {{#error}}{{#highlite}}$i{duration_raw}{{#error}} is not a number!")
                return
            mins = float(duration_raw)
            if mins > 0:
                expires = time.time() + mins * 60.0
        _st_state.chat_ignored[target.login] = expires
        await chat_ui_send(aseco, target.login, False)
        if expires <= 0:
            message = format_text(
                "{#server}>> {#admin}{1}$z$s{#admin} disables chat for {2}$z$s{#admin} !",
                _strip_nick(player.nickname),
                _strip_nick(target.nickname),
            )
        else:
            message = format_text(
                "{#server}>> {#admin}{1}$z$s{#admin} disables chat for {2}$z$s{#admin} [{3} minute{4}] !",
                _strip_nick(player.nickname),
                _strip_nick(target.nickname),
                str(float(duration_raw)),
                "" if float(duration_raw) == 1.0 else "s",
            )
        await _send_global(aseco, message)
        return

    if sub == "unignore":
        target_param = rest.strip()
        if not target_param or target_param == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st unignore <login>")
            return
        target = None
        if target_param.isdigit():
            idx = int(target_param)
            visible = []
            for login in _st_state.chat_ignored:
                if aseco.server.players.get_player(login):
                    visible.append(login)
            if idx < 1 or idx > len(visible):
                await _send_login(aseco, player.login, "{#server}> {#error}Invalid Player_ID (use /st listignores first) !")
                return
            target = aseco.server.players.get_player(visible[idx - 1])
        else:
            target = aseco.server.players.get_player(target_param)
        if not target or target.login not in _st_state.chat_ignored:
            await _send_login(aseco, player.login, "{#server}> {#error}Not on ignore list!")
            return
        _st_state.chat_ignored.pop(target.login, None)
        await chat_ui_send(aseco, target.login, True)
        message = format_text(
            "{#server}>> {#admin}{1}$z$s{#admin} enables chat for {2}$z$s{#admin} !",
            _strip_nick(player.nickname),
            _strip_nick(target.nickname),
        )
        await _send_global(aseco, message)
        return

    if sub == "listignores":
        show_all = rest.strip().lower() == "all"
        if rest.strip().lower() == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st listignores [all]")
            return
        found = False
        idx = 0
        for login, expires in _st_state.chat_ignored.items():
            target = aseco.server.players.get_player(login)
            if not target:
                if not show_all:
                    continue
                target_nick = login
            else:
                target_nick = _strip_nick(target.nickname)
            found = True
            idx += 1
            suffix = ""
            if expires > 0:
                left = abs(round((expires - time.time()) / 60.0, 1))
                suffix = f", {left} minute{'' if left == 1.0 else 's'} left"
            message = f"{{#server}}> [{idx}] $i{target_nick}$z{{#server}}$s$fc0$i ({login}{suffix})"
            await _send_login(aseco, player.login, message)
        if not found:
            await _send_login(aseco, player.login, "{#server}> {#error}No ignored player found!")
        return

    if sub == "cleanignores":
        if rest.strip().lower() == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st cleanignores")
            return
        found = False
        for login in list(_st_state.chat_ignored.keys()):
            found = True
            _st_state.chat_ignored.pop(login, None)
            if aseco.server.players.get_player(login):
                await chat_ui_send(aseco, login, True)
        if not found:
            await _send_login(aseco, player.login, "{#server}> {#error}No ignored players found!")
            return
        message = format_text(
            "{#server}>> {#admin}{1}$z$s{#admin} cleans chat-disabled players list!",
            _strip_nick(player.nickname),
        )
        await _send_global(aseco, message)
        return

    if sub == "fstate":
        parts = rest.split(" ", 3)
        if len(parts) < 2:
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st fstate <login> <state> [target [camera]]")
            await _send_login(aseco, player.login, "{#server}> {#error}State can be: user (0), spec (1), player (2)")
            await _send_login(aseco, player.login, "{#server}> {#error}Camera mode can be: unchange (-1), replay (0), follow (1), free (2)")
            return
        target = aseco.server.players.get_player(parts[0])
        if not target:
            return
        state_map = {"user": 0, "0": 0, "spec": 1, "spectator": 1, "1": 1, "player": 2, "2": 2}
        if parts[1] not in state_map:
            await _send_login(aseco, player.login, f"{{#server}}> {{#error}}Unkown parameter {{#highlite}}$i{parts[1]}{{#error}} for state !")
            return
        state_value = state_map[parts[1]]
        target_login = ""
        camera = -1
        extra = parts[2].split(" ", 1) if len(parts) > 2 and parts[2] else []
        if state_value == 2 and extra:
            await _send_login(aseco, player.login, "{#server}> {#error}Can't use target while forcing player mode!")
            return
        if extra:
            target_spec = aseco.server.players.get_player(extra[0])
            if not target_spec:
                return
            target_login = target_spec.login
            camera_map = {"unchange": -1, "unchanged": -1, "default": -1, "-1": -1, "replay": 0, "0": 0, "follow": 1, "1": 1, "free": 2, "2": 2}
            camera_token = extra[1].strip() if len(extra) > 1 else ""
            if camera_token:
                if camera_token not in camera_map:
                    await _send_login(aseco, player.login, f"{{#server}}> {{#error}}Unkown parameter {{#highlite}}$i{camera_token}{{#error}} for camera mode !")
                    return
                camera = camera_map[camera_token]
        if target_login:
            await aseco.client.query_ignore_result("ForceSpectator", target.login, 1)
            if state_value == 0:
                await aseco.client.query_ignore_result("ForceSpectator", target.login, 0)
            await aseco.client.query_ignore_result("ForceSpectatorTarget", target.login, target_login, camera)
            if state_value == 1 or state_value == 0:
                await aseco.client.query_ignore_result("SpectatorReleasePlayerSlot", target.login)
        else:
            await aseco.client.query_ignore_result("ForceSpectator", target.login, state_value)
            if state_value == 1:
                await aseco.client.query_ignore_result("ForceSpectatorTarget", target.login, "", 2)
        tstate = _ensure_player_state(target)
        tstate["fstate"] = state_value
        if state_value != 0:
            _st_state.fstates[target.login] = state_value
        else:
            _st_state.fstates.pop(target.login, None)
        return

    if sub in {"fstates", "fstated"}:
        if rest.strip().lower() == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st fstates [all]")
            return
        show_all = rest.strip().lower() == "all"
        found = False
        idx = 0
        for login, state_value in _st_state.fstates.items():
            target = aseco.server.players.get_player(login)
            if not target and not show_all:
                continue
            target_nick = _strip_nick(target.nickname) if target else login
            idx += 1
            found = True
            await _send_login(aseco, player.login, f"{{#server}}> [{idx}] $i{target_nick}$z{{#server}}$s$fc0$i ({login})$z{{#server}}$s => {{#highlite}}{state_value}")
        if not found:
            await _send_login(aseco, player.login, "{#server}> {#error}No fstated player found!")
        return

    if sub == "specme":
        target_login = rest.strip().split(" ", 1)[0]
        if not target_login or target_login == "help":
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st specme <login>")
            return
        await chat_st(aseco, {"author": player, "params": f"fstate {target_login} 0 {player.login} 1"})
        return

    if sub == "vote":
        try:
            tokens = _parse_vote_tokens(rest)
        except ValueError as exc:
            await _send_login(aseco, player.login, f"{{#server}}> {{#error}}{exc}")
            return
        if not tokens:
            await _send_login(aseco, player.login, "{#server}> {#error}Usage: /st vote \"message[:pass cmd[:fail cmd]]\" [timeout [ratio]]")
            await _send_login(aseco, player.login, "{#server}> {#error}Special values: a timeout of '0' means default, '1' means indefinite")
            return

        vote_spec = tokens[0]
        params = [_restore_vote_token(tok) for tok in tokens]
        param_parts = [part.replace("\\c", ":") for part in vote_spec.split(":")]
        message = params[0].split(":", 1)[0]
        pass_cmds = param_parts[1].replace("\\s", ";").split(";") if len(param_parts) > 1 and param_parts[1] else ""
        fail_cmds = param_parts[2].replace("\\s", ";").split(";") if len(param_parts) > 2 and param_parts[2] else ""

        message = re.sub(r"\?+\s*$", "", message.replace("\\s", ";")).strip()
        replacements = {aseco.server.serverlogin: _strip_nick(aseco.server.name) + "$z"}
        for pl in aseco.server.players.all():
            replacements[pl.login] = _strip_nick(pl.nickname) + "$z"
        for src, dst in replacements.items():
            message = message.replace(src, dst)
        message = message[:1].upper() + message[1:] if message else ""
        if not message:
            await _send_login(aseco, player.login, "{#server}> {#error}No message!")
            return
        message += "$z"

        timeout = 0
        if len(params) > 1:
            try:
                timeout = int(float(params[1]))
            except Exception:
                await _send_login(aseco, player.login, f"{{#server}}> {{#error}}{{#highlite}}$i{params[1]}{{#error}} is not a number!")
                return
        if timeout != 1:
            timeout *= 1000
        ratio = -1.0
        if len(params) > 2:
            try:
                ratio = float(params[2].replace(",", "."))
            except Exception:
                await _send_login(aseco, player.login, f"{{#server}}> {{#error}}{{#highlite}}$i{params[2]}{{#error}} is not a number!")
                return
            if ratio > 1:
                ratio = ratio / 100.0

        _st_state.uservote_command = pass_cmds
        _st_state.uservote_fail_command = fail_cmds
        await _st_state.run_custom_vote(message, "st_custom_user_vote", player.login, timeout, ratio)
        return

    if sub == "":
        await _send_login(aseco, player.login, "{#server}> {#error}Use /st help for help!")
        return

    await _send_login(aseco, player.login, f"{{#server}}> {{#error}}Unknown command : {{#highlite}}$i {sub} {rest}")


def _parse_vote_tokens(rest: str) -> list[str]:
    text = rest.replace("\\'", "\\a")
    text = text.replace("\\;", "\\s").replace("\\:", "\\c").replace('\\"', "\\q")
    text = re.sub(r"(?<!\\)'", '"', text)
    return shlex.split(text)


def _restore_vote_token(token: str) -> str:
    return token.replace("\\q", '"').replace("\\a", "'")
