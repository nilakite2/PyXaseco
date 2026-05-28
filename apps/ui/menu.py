from __future__ import annotations

"""
menu.py — Port of Fufi Menu for XAseco

Original:
  Fufi Menu Plugin for XASECO by oorf-fuckfish
  Version 0.36

Port notes:
- Loads menu config from apps/ui/app_defaults.toml
- Loads menu ML template from apps/ui/app_defaults.toml
- Sends menu button on connect / new challenge
- Opens nested menu windows
- Executes menu actions by simulating a player chat command
- Allows external plugins to add entries/groups/separators via onMenuLoaded
"""

import logging
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyxaseco.app_config import AppSetting, AppSettingsSchema, bind_app_settings
from pyxaseco.core.config import display_path
from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

_fufi_menu: "FufiMenu | None" = None
_OPTIONAL_FEATURE_DEPENDENCIES = {
    'plugin.rpoints.php': 'feature_rpoints',
    'plugin.msglog.php': 'feature_msglog',
    'plugin.tgj_allbutton.php': 'feature_allbutton',
    'plugin.freezone.php': 'feature_freezone',
    'plugin.stalker_actionids.php': 'feature_stalker_actionids',
    'plugin.stalker_tools.php': 'feature_stalker_tools',
}


def _as_dict(value, default=None):
    return value if isinstance(value, dict) else (default if isinstance(default, dict) else {})


FUFI_MENU_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id="fufi_menu",
    section_name="ui",
    description="FuFi menu configuration",
    settings=(
        AppSetting("config", {}, _as_dict, aliases=("menu",)),
    ),
)

def _resolve_indicator_func(name: str):
    if not name:
        return None

    func = globals().get(name)
    if callable(func):
        return func

    for mod_name, module in list(sys.modules.items()):
        if not module:
            continue
        if not mod_name.startswith("apps."):
            continue
        func = getattr(module, name, None)
        if callable(func):
            return func

    return None


def _resolve_chat_admin_auth_check():
    for mod_name, module in list(sys.modules.items()):
        if not module:
            continue
        if mod_name != "apps.admin.command_router":
            continue
        func = getattr(module, "_auth_check", None)
        if callable(func):
            return func
    return None


def _extract_admin_subcommand(chatcmd: str) -> str:
    parts = (chatcmd or "").strip().split()
    if len(parts) < 2:
        return ""
    return parts[1].strip().lower()


def _allow_menu_entry(aseco: "Aseco", player: "Player", entry: "FufiMenuEntry") -> bool:
    chatcmd = (entry.chatcmd or "").strip()
    chatcmd_l = chatcmd.lower()

    if chatcmd_l.startswith("/") and not chatcmd_l.startswith("/admin") and not chatcmd_l.startswith("/jfreu"):
        parts = chatcmd_l[1:].split(None, 1)
        cmd_name = parts[0].strip() if parts else ""
        if cmd_name and not aseco.get_command(cmd_name):
            return False

    if chatcmd_l.startswith("/admin"):
        sub = _extract_admin_subcommand(chatcmd_l)
        if not sub:
            return False

        auth_check = _resolve_chat_admin_auth_check()
        if callable(auth_check):
            return bool(auth_check(aseco, player, sub)[0])
        return aseco.allow_ability(player, sub)

    if chatcmd_l.startswith("/jfreu"):
        return aseco.is_any_admin(player)

    if entry.ability:
        return aseco.allow_ability(player, entry.ability)

    return True


def register(aseco: "Aseco"):
    aseco.register_event("onPlayerConnect", fufiMenu_playerConnect)
    aseco.register_event("onPlayerManialinkPageAnswer", fufiMenu_handleClick)
    aseco.register_event("onStartup", fufiMenu_startup)
    aseco.register_event("onEndRace", fufiMenu_endRace)
    aseco.register_event("onNewChallenge", fufiMenu_newChallenge)


@dataclass
class FufiMenuEntry:
    caption: str = ""
    indicator: str = ""
    params: str = ""
    chatcmd: str = ""
    chatcmdparams: str = ""
    type: str = ""
    ability: str = ""
    unique: str = ""
    rights: bool = False
    id: str = ""
    parentid: str = "0000"
    entries: list["FufiMenuEntry"] = field(default_factory=list)

    def is_group(self) -> bool:
        return bool(self.entries) or self.chatcmd == ""

    def insert_entry(self, entry_point: str, insert_after: bool, entry: "FufiMenuEntry", aseco: "Aseco"):
        inserted = False

        if not entry_point:
            if insert_after:
                self.entries.append(entry)
            else:
                self.entries = [entry] + self.entries
            return

        new_entries: list[FufiMenuEntry] = []
        if insert_after:
            for ent in self.entries:
                new_entries.append(ent)
                if ent.unique == entry_point:
                    new_entries.append(entry)
                    inserted = True
            self.entries = new_entries
        else:
            for ent in self.entries:
                if ent.unique == entry_point:
                    new_entries.append(entry)
                    inserted = True
                new_entries.append(ent)
            self.entries = new_entries

        if not inserted:
            if insert_after:
                self.entries.append(entry)
            else:
                self.entries = [entry] + self.entries


    def get_valid_entries(self, menu: "FufiMenu", login: str) -> list["FufiMenuEntry"]:
        player = menu.aseco.server.players.get_player(login)
        if not player:
            return []

        result: list[FufiMenuEntry] = []
        for entry in self.entries:
            if (entry.rights == getattr(player, "rights", False)) or (not entry.rights):
                if entry.is_group() and not entry.chatcmd:
                    result.append(entry)
                else:
                    if _allow_menu_entry(menu.aseco, player, entry):
                        result.append(entry)

        filtered: list[FufiMenuEntry] = []
        for entry in result:
            if (not entry.is_group()) or (not menu.group_is_empty(entry, login)) or entry.type == "separator":
                filtered.append(entry)
        return filtered


class FufiMenu:
    def __init__(self, config_root: dict[str, Any], config_path: str | Path | None = None):
        self.manialink_id = "383"
        self.unique_id = 1001
        self.id = "0000"
        self.first_challenge = True

        self.config_path = Path(config_path) if config_path else None
        self.config_root = config_root if isinstance(config_root, dict) else {}

        self.posx = 0.0
        self.posy = 0.0
        self.width = 8.0
        self.height = 2.0
        self.separatorheight = 0.5
        self.menutimeout = 0
        self.horientation = 0
        self.vorientation = 0
        self.caption = "Menu"

        self.styles: dict[str, dict[str, str]] = {}
        self.blocks: dict[str, str] = {}
        self.entries: list[FufiMenuEntry] = []
        self.entries_list: list[FufiMenuEntry] = []

        self.app_list = ""
        self.aseco: Aseco | None = None
        self.gameinfo: dict[str, Any] = {}
        self.gameinfonext: dict[str, Any] = {}
        
        self.referee_mode: int | None = None
        self.challenge_download_allowed: int | None = None

    def init(self):
        self._load_app_list()
        self.load_settings()
        self.load_styles()
        self.load_entries()

    def _load_app_list(self):
        plugins_toml = Path("apps.toml")
        if plugins_toml.exists():
            try:
                with plugins_toml.open("rb") as fh:
                    data = tomllib.load(fh)
                enabled = data.get("loadout", {}).get("enabled", [])
                vals: list[str] = []
                aliases = {
                    "app/admin": ["chat.admin.php"],
                    "app/help": ["chat.help.php"],
                    "app/platform_core": [
                        "plugin.localdb.php",
                        "plugin.rounds.php",
                        "plugin.track.php",
                        "plugin.rasp_nextmap.php",
                        "plugin.chatlog.php",
                        "plugin.checkpoints.php",
                        "plugin.donate.php",
                        "chat.songmod.php",
                    ],
                    "app/platform_ui": [
                        "plugin.style.php",
                        "plugin.panels.php",
                        "chat.lastwin.php",
                    ],
                    "app/server_info": ["bridge.public_stats.php"],
                    "app/discord": ["bridge.discord.php", "plugin.discord_webhook.php"],
                    "app/jukebox": [
                        "plugin.rasp_jukebox.php",
                    ],
                    "app/voting": [
                        "plugin.rasp_votes.php",
                    ],
                    "app/ui": [
                        "records_eyepiece.app.php",
                        "plugin.rasp_karma.php",
                        "plugin.fufi_menu.php",
                        "plugin.banner.php",
                    ],
                    "app/records_local": [
                        "chat.records.php",
                        "chat.records2.php",
                        "chat.recrels.php",
                        "plugin.rasp.php",
                    ],
                    "app/records_dedimania": ["plugin.dedimania.php", "chat.dedimania.php"],
                    "app/players": [
                        "chat.players.php",
                        "chat.players2.php",
                        "chat.wins.php",
                        "chat.laston.php",
                        "chat.stats.php",
                        "plugin.rasp.php",
                        "plugin.rasp_nextrank.php",
                    ],
                    "app/server_info": ["chat.server.php", "plugin.uptodate.php"],
                    "app/social_chat": ["chat.me.php", "plugin.rasp_chat.php"],
                    "app/tmx": ["plugin.tmxinfo.php", "plugin.tmxvideo.php"],
                    "app/records_trial": ["plugin.trial_records.php"],
                    "app/records_rpg": ["plugin.records_rpg.php"],
                    "app/jfreu": ["jfreu.plugin.php", "jfreu.chat.php"],
                    "app/checkpoint_tools": ["plugin.cplive.php", "plugin.cpll.php"],
                    "app/best_cp_times": ["plugin.best_cp_times_v2.php"],
                    "app/bestfinishes": ["plugin.bestfinishes.php"],
                    "app/ztrack": ["plugin.ztrack.php"],
                    "chat/admin": ["chat.admin.php"],
                    "chat/help": ["chat.help.php"],
                    "chat/records": ["chat.records.php"],
                    "chat/records2": ["chat.records2.php"],
                    "chat/recrels": ["chat.recrels.php"],
                    "chat/dedimania": ["chat.dedimania.php"],
                    "chat/players": ["chat.players.php"],
                    "chat/players2": ["chat.players2.php"],
                    "chat/wins": ["chat.wins.php"],
                    "chat/laston": ["chat.laston.php"],
                    "chat/lastwin": ["chat.lastwin.php"],
                    "chat/stats": ["chat.stats.php"],
                    "chat/server": ["chat.server.php"],
                    "chat/songmod": ["chat.songmod.php"],
                    "core/checkpoints": ["plugin.checkpoints.php"],
                    "core/donate": ["plugin.donate.php"],
                    "core/track": ["plugin.track.php"],
                    "service/records_dedimania": ["plugin.dedimania.php"],
                    "service/tmx": ["plugin.tmxinfo.php"],
                    "service/mania_karma": ["plugin.rasp_karma.php"],
                    "feature/rasp": ["plugin.rasp.php"],
                    "feature/rasp_chat": ["plugin.rasp_chat.php"],
                    "feature/rasp_jukebox": ["plugin.rasp_jukebox.php"],
                    "feature/rasp_nextmap": ["plugin.rasp_nextmap.php"],
                    "feature/rasp_nextrank": ["plugin.rasp_nextrank.php"],
                    "feature/rasp_votes": ["plugin.rasp_votes.php"],
                    "feature/jfreu": ["jfreu.plugin.php", "jfreu.chat.php"],
                    "ui/style": ["plugin.style.php"],
                    "ui/panels": ["plugin.panels.php"],
                }
                if isinstance(enabled, list):
                    for name in enabled:
                        if not isinstance(name, str):
                            continue
                        vals.append(name)
                        vals.append(name.replace("/", "_"))
                        vals.append(name.replace("/", ".") + ".php")
                        vals.extend(aliases.get(name, []))
                self.app_list = "|".join(dict.fromkeys(vals)) + ("|" if vals else "")
                return
            except Exception as e:
                logger.warning("[FufiMenu] Could not parse apps.toml: %s", e)

    def get_shared_attr(self, *names: str, default=None):
        """
        Look up shared state from common places instead of only this module's globals.
        Search order:
          1) aseco.server.<name>
          2) aseco.<name>
          3) this module globals()
        """
        if not self.aseco:
            for name in names:
                if name in globals():
                    return globals()[name]
            return default

        for name in names:
            try:
                if hasattr(self.aseco.server, name):
                    return getattr(self.aseco.server, name)
            except Exception:
                pass

            try:
                if hasattr(self.aseco, name):
                    return getattr(self.aseco, name)
            except Exception:
                pass

            if name in globals():
                return globals()[name]

        return default

    def get_app_state(self, app_name: str, default=None):
        """
        Best-effort app/module state lookup.
        """
        if not self.aseco:
            return globals().get(app_name, default)

        try:
            plugins = getattr(self.aseco.server, "plugins", None)
            if isinstance(plugins, dict) and app_name in plugins:
                return plugins[app_name]
        except Exception:
            pass

        try:
            if hasattr(self.aseco.server, app_name):
                return getattr(self.aseco.server, app_name)
        except Exception:
            pass

        try:
            if hasattr(self.aseco, app_name):
                return getattr(self.aseco, app_name)
        except Exception:
            pass

        return globals().get(app_name, default)

    def get_unique_id(self) -> str:
        uid = str(self.unique_id)
        self.unique_id += 1
        return uid

    def load_settings(self):
        position = str(self.config_root.get("position", "0 0")).split()
        size = str(self.config_root.get("size", "8 2")).split()

        self.separatorheight = float(self.config_root.get("separatorheight", "0.5"))
        self.posx = float(position[0])
        self.posy = float(position[1])
        self.width = float(size[0])
        self.height = float(size[1])
        self.horientation = int(self.config_root.get("horizontalorientation", "0"))
        self.vorientation = int(self.config_root.get("verticalorientation", "0"))
        self.caption = str(self.config_root.get("menu_caption", "Menu") or "Menu")
        self.menutimeout = int(self.config_root.get("menutimeout", "0"))

        self.blocks = {}
        template_xml = str(self.config_root.get("template_xml", "") or "")
        if template_xml:
            try:
                blocks = self.get_xml_template_blocks(template_xml)
            except Exception as e:
                logger.warning("[FufiMenu] Could not parse template_xml from app_defaults.toml: %s", e)
                blocks = {}
            if {"header", "footer", "menubutton", "icon"}.issubset(blocks):
                self.blocks = blocks
            else:
                logger.warning("[FufiMenu] template_xml in app_defaults.toml is missing required blocks")
        if not self.blocks:
            logger.warning("[FufiMenu] No valid template_xml found in app_defaults.toml, menu rendering disabled")

    def load_styles(self):
        self.styles = {}
        styles_node = self.config_root.get("styles", {})
        elements = [
            "menubutton",
            "menubackground",
            "menuentry",
            "menuentryactive",
            "menugroupicon",
            "menuicon",
            "menuactionicon",
            "menuhelpicon",
            "separator",
            "indicatorfalse",
            "indicatortrue",
            "indicatoronhold",
        ]

        for element in elements:
            self.styles[element] = {"style": "", "substyle": ""}
            if not isinstance(styles_node, dict):
                continue
            node = styles_node.get(element, {})
            if isinstance(node, dict):
                self.styles[element]["style"] = str(node.get("style", ""))
                self.styles[element]["substyle"] = str(node.get("substyle", ""))

    def load_entries(self):
        entries_data = self._load_entries_data()
        if not entries_data:
            return

        for entry_node in entries_data:
            if not isinstance(entry_node, dict):
                continue
            deps = str(entry_node.get("dependencies", ""))
            glob = str(entry_node.get("globalvariable", ""))
            if self.dependencies_met(deps, glob):
                entry = self._entry_from_mapping(entry_node, self.id)
                self.entries.append(entry)
                self.entries_list.append(entry)

    def _load_entries_data(self) -> list[dict[str, Any]]:
        entries_value = self.config_root.get("entries")
        if isinstance(entries_value, list):
            return [entry for entry in entries_value if isinstance(entry, dict)]
        if isinstance(entries_value, dict):
            raw_items = entries_value.get("items")
            if isinstance(raw_items, list):
                return [entry for entry in raw_items if isinstance(entry, dict)]
            raw_json = entries_value.get("json")
            if isinstance(raw_json, str) and raw_json.strip():
                try:
                    parsed = json.loads(raw_json)
                    if isinstance(parsed, list):
                        return [entry for entry in parsed if isinstance(entry, dict)]
                except Exception as e:
                    logger.warning("[FufiMenu] Could not parse entries JSON from nested section: %s", e)
        raw_json = self.config_root.get("entries_json")
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, list):
                    return [entry for entry in parsed if isinstance(entry, dict)]
            except Exception as e:
                logger.warning("[FufiMenu] Could not parse entries JSON: %s", e)
        return []

    def _entry_from_mapping(self, entry_data: dict[str, Any], parentid: str) -> FufiMenuEntry:
        entry = FufiMenuEntry(
            caption=str(entry_data.get("caption", "")),
            indicator=str(entry_data.get("indicator", "")),
            params=str(entry_data.get("params", "")),
            chatcmd=str(entry_data.get("chatcmd", "")),
            chatcmdparams=str(entry_data.get("chatcmdparams", "")),
            type=str(entry_data.get("type", "")),
            ability=str(entry_data.get("ability", "")),
            unique=str(entry_data.get("unique", "")),
            rights=(str(entry_data.get("rights", "")).lower() == "tmuf"),
            id=self.get_unique_id(),
            parentid=parentid,
        )

        for sub in entry_data.get("entries", []):
            if not isinstance(sub, dict):
                continue
            deps = str(sub.get("dependencies", ""))
            glob = str(sub.get("globalvariable", ""))
            if self.dependencies_met(deps, glob):
                child = self._entry_from_mapping(sub, entry.id)
                entry.entries.append(child)
                self.entries_list.append(child)
        return entry

    def addEntry(
        self,
        insertInGroup: str,
        entryPoint: str,
        insertAfter: bool = True,
        caption: str = "",
        unique: str = "",
        chatcmd: str = "",
        chatcmdparams: str = "",
        ability: str = "",
        indicator: str = "",
        params: str = "",
        type: str = "",
        rights: str = "",
    ):
        attrib: dict[str, str] = {}
        if caption:
            attrib["caption"] = caption
        if unique:
            attrib["unique"] = unique
        if chatcmd:
            attrib["chatcmd"] = chatcmd
        if chatcmdparams:
            attrib["chatcmdparams"] = chatcmdparams
        if ability:
            attrib["ability"] = ability
        if indicator:
            attrib["indicator"] = indicator
        if params:
            attrib["params"] = params
        if type:
            attrib["type"] = type
        if rights:
            attrib["rights"] = rights

        parent = self.get_entry_by_unique_key(insertInGroup)
        if not parent:
            if self.aseco:
                self.aseco.console(
                    'FufiMenu: External plugin tried to add an entry to non-existing group "{1}"',
                    insertInGroup,
                )
            return

        entry = self._entry_from_mapping(attrib, parent.id)
        if isinstance(parent, FufiMenu):
            self.insert_entry(entryPoint, insertAfter, entry)
        else:
            parent.insert_entry(entryPoint, insertAfter, entry, self.aseco)
        self.entries_list.append(entry)

    def addSeparator(self, insertInGroup: str, entryPoint: str, insertAfter: bool, unique: str):
        self.addEntry(insertInGroup, entryPoint, insertAfter, "", unique, "", "", "", "", "", "separator")

    def insert_entry(self, entryPoint: str, insertAfter: bool, entry: FufiMenuEntry):
        inserted = False

        if not entryPoint:
            if insertAfter:
                self.entries.append(entry)
            else:
                self.entries = [entry] + self.entries
            return

        new_entries: list[FufiMenuEntry] = []
        if insertAfter:
            for ent in self.entries:
                new_entries.append(ent)
                if ent.unique == entryPoint:
                    new_entries.append(entry)
                    inserted = True
            self.entries = new_entries
        else:
            for ent in self.entries:
                if ent.unique == entryPoint:
                    new_entries.append(entry)
                    inserted = True
                new_entries.append(ent)
            self.entries = new_entries

        if not inserted and self.aseco:
            if insertAfter:
                self.entries.append(entry)
                pos = "beginning"
            else:
                self.entries = [entry] + self.entries
                pos = "end"
            self.aseco.console(
                'FufiMenu: External plugin tried to insert after an invalid key "{1}", entry was inserted at the {2}.',
                entryPoint,
                pos,
            )

    def dependencies_met(self, dependencies: str, globalvariable: str) -> bool:
        if not dependencies and not globalvariable:
            return True

        result = True

        for dep in [d.strip() for d in dependencies.split(",") if d.strip()]:
            feature_flag = _OPTIONAL_FEATURE_DEPENDENCIES.get(dep)
            if feature_flag:
                result = result and bool(self.get_shared_attr(feature_flag, default=False))
            else:
                result = result and (f"{dep}|" in self.app_list or dep in self.app_list)

        if globalvariable:
            try:
                active = self.get_shared_attr(globalvariable, default=False)
                result = result and bool(active)
            except Exception:
                result = False

        return result

    def get_xml_template_blocks(self, xml: str) -> dict[str, str]:
        result: dict[str, str] = {}
        xml_ = xml
        while "<!--start_" in xml_:
            xml_ = xml_[xml_.find("<!--start_") + 10 :]
            title = xml_[: xml_.find("-->")]
            result[title] = self.get_xml_block(xml, title).strip()
        return result

    def get_xml_block(self, haystack: str, caption: str) -> str:
        start_str = f"<!--start_{caption}-->"
        end_str = f"<!--end_{caption}-->"
        if start_str not in haystack or end_str not in haystack:
            return ""
        block = haystack[haystack.find(start_str) + len(start_str) :]
        block = block[: block.find(end_str)]
        return block

    async def send_menu_button_to_login(self, login: str):
        if not {"header", "footer", "menubutton", "icon"}.issubset(self.blocks):
            logger.warning("[FufiMenu] Menu template blocks missing, skipping menu button render")
            return
        header = self.blocks["header"].replace("%menuid%", self.manialink_id + "0000").replace("%framepos%", "0 0 1")
        footer = self.blocks["footer"]
        content = (
            self.blocks["menubutton"]
            .replace("%size%", f"{self.width} {self.height}")
            .replace("%pos%", f"{self.posx} {self.posy} 1")
            .replace("%poslabel%", f"{self.posx + self.width / 2} {self.posy - (self.height / 2 - 0.1)} 1")
            .replace("%style%", self.styles["menubutton"]["style"])
            .replace("%substyle%", self.styles["menubutton"]["substyle"])
            .replace("%action%", self.manialink_id + "0000")
            .replace("%text%", self.caption)
        )
        icon = (
            self.blocks["icon"]
            .replace("%x%", str(self.posx + 1))
            .replace("%y%", str(self.posy - 0.2))
            .replace("%style%", self.styles["menuicon"]["style"])
            .replace("%substyle%", self.styles["menuicon"]["substyle"])
        )
        xml = header + content + icon + footer

        if login == "":
            if self.first_challenge:
                self.first_challenge = False
            if getattr(self.aseco, "debug", False):
                self.aseco.console("[FufiMenu] sending menu button to all")
            await self.aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)
        else:
            if getattr(self.aseco, "debug", False):
                self.aseco.console("[FufiMenu] sending menu button to login: {1}", login)
            await self.aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)

    async def handle_click(self, playerid: int, login: str, action: str):
        if not self.blocks:
            return
        action = str(action)
    
        if not action.startswith(self.manialink_id):
            return
        logger.debug("[FufiMenu] click login=%s action=%s", login, action)
        suffix = action[len(self.manialink_id):]
    
        # Only allow:
        # - main open button
        # - close button
        # - known menu entry ids
        if suffix not in ("0000", "0001") and not self.get_entry_by_id(suffix):
            return
        logger.debug("[FufiMenu] suffix=%s known=%s", suffix, bool(self.get_entry_by_id(suffix)))
        await self.execute_action(playerid, login, suffix)


    async def dispatch_chat_command(self, playerid: int, login: str, full_cmd: str):
        """
        Try to dispatch through the normal chat pipeline first.
        Fallback to onChat_<command> if no central parser exists.
        """
        full_cmd = (full_cmd or "").strip()
        if not full_cmd:
            return

        if full_cmd.startswith("/"):
            full_cmd = full_cmd[1:]

        player = self.aseco.server.players.get_player(login)
        if not player:
            return

        # Preferred: central chat handler if available
        for meth_name in ("playerChat", "player_chat", "handle_chat", "handleChat"):
            meth = getattr(self.aseco, meth_name, None)
            if callable(meth):
                chat_packet = [playerid, login, "/" + full_cmd, True]
                result = meth(chat_packet)
                if hasattr(result, "__await__"):
                    await result
                return

        # Fallback: direct command event dispatch
        parts = full_cmd.split(None, 1)
        command_name = parts[0].lower() if parts else ""
        command_params = parts[1] if len(parts) > 1 else ""
        if command_name:
            await self.aseco.release_event(
                f"onChat_{command_name}",
                {
                    "author": player,
                    "command": command_name,
                    "params": command_params,
                },
            )


    async def execute_action(self, playerid: int, login: str, action: str):
        if action == "0000":
            await self.display_menu(login, "0000")
            return
        if action == "0001":
            await self.close_menu(login)
            return
    
        entry = self.get_entry_by_id(action)
        if not entry:
            return
    
        if entry.is_group():
            await self.display_menu(login, action)
            return
    
        param = ""
        if entry.chatcmdparams:
            chatparams = entry.chatcmdparams.split("/")
            if entry.indicator:
                func = _resolve_indicator_func(entry.indicator)
                if callable(func):
                    params: list[Any] = []
                    if entry.params:
                        params = entry.params.split(",") if "," in entry.params else [entry.params]
                    args = [self.aseco, login] + params
                    indicator = func(*args)
                    idx = 1 if indicator else 0
                    if idx < len(chatparams):
                        param = " " + chatparams[idx]
    
        full_cmd = (entry.chatcmd + param).strip()
        if full_cmd:
            await self.dispatch_chat_command(playerid, login, full_cmd)
    
        if entry.indicator == "":
            await self.close_menu(login)
        else:
            await self.update_menu(login, action)

    def get_entry_by_id(self, id_: str) -> FufiMenu | FufiMenuEntry | None:
        if id_ == "0000":
            return self
        for entry in self.entries_list:
            if entry.id == id_:
                return entry
        return None

    def get_entry_by_unique_key(self, unique: str) -> FufiMenu | FufiMenuEntry | None:
        if unique == "":
            return self
        for entry in self.entries_list:
            if entry.unique == unique:
                return entry
        return None

    def get_valid_entries(self, login: str) -> list[FufiMenuEntry]:
        player = self.aseco.server.players.get_player(login)
        if not player:
            return []

        result: list[FufiMenuEntry] = []
        for entry in self.entries:
            if (entry.rights == getattr(player, "rights", False)) or (not entry.rights):
                if entry.is_group() and not entry.chatcmd:
                    result.append(entry)
                else:
                    if _allow_menu_entry(self.aseco, player, entry):
                        result.append(entry)

        filtered: list[FufiMenuEntry] = []
        for entry in result:
            if (not entry.is_group()) or (not self.group_is_empty(entry, login)) or entry.type == "separator":
                filtered.append(entry)
        return filtered

    async def close_menu(self, login: str):
        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialinks><manialink id="{self.manialink_id}0001"></manialink></manialinks>'
        await self.aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)

    async def hide_menu_everywhere(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><manialinks>'
            f'<manialink id="{self.manialink_id}0000"></manialink>'
            f'<manialink id="{self.manialink_id}0001"></manialink>'
            '</manialinks>'
        )
        await self.aseco.client.query_ignore_result("SendDisplayManialinkPage", xml, 0, False)

    async def update_menu(self, login: str, id_: str):
        ids = self.get_window_ids(id_)
        if len(ids) >= 2:
            await self.display_menu(login, ids[-2])

    async def display_menu(self, login: str, id_: str):
        try:
            self.gameinfo = await self.aseco.client.query("GetCurrentGameInfo", 1) or {}
        except Exception:
            self.gameinfo = {}
        try:
            self.gameinfonext = await self.aseco.client.query("GetNextGameInfo", 1) or {}
        except Exception:
            self.gameinfonext = {}
        try:
            self.referee_mode = await self.aseco.client.query("GetRefereeMode")
        except Exception:
            self.referee_mode = None
        try:
            self.challenge_download_allowed = await self.aseco.client.query("IsChallengeDownloadAllowed")
        except Exception:
            self.challenge_download_allowed = None

        ids = self.get_window_ids(id_)

        posx = self.posx + self.width if self.horientation == 1 else self.posx
        posy = self.posy
        content = ""
        oldId = None
        entries: list[FufiMenuEntry] = []

        for wid in ids:
            itemoffset = 0
            closeaction = self.manialink_id + ("0001" if oldId is None else oldId)

            if entries:
                itemoffset = self.get_item_offset(entries, wid)

            if wid == "0000":
                entries = self.get_valid_entries(login)
                caption = self.caption
            else:
                entry = self.get_entry_by_id(wid)
                entries = entry.get_valid_entries(self, login) if isinstance(entry, FufiMenuEntry) else []
                caption = entry.caption if isinstance(entry, FufiMenuEntry) else self.caption

            windowwidth = self.get_window_width(entries)
            windowx = (posx + 0.5) if self.horientation == 1 else (posx - windowwidth - 0.5)

            windowheight = self.get_window_height(entries)
            windowy = posy + itemoffset
            if self.vorientation == 1:
                if windowy > self.posy:
                    windowy = self.posy
            else:
                if windowy - windowheight < (self.posy - self.height):
                    windowy = self.posy - self.height + windowheight

            content += (
                self.blocks["menuwindow"]
                .replace("%size%", f"{windowwidth} {windowheight}")
                .replace("%pos%", f"{windowx} {windowy} 23")
                .replace("%style%", self.styles["menubackground"]["style"])
                .replace("%substyle%", self.styles["menubackground"]["substyle"])
            )

            frame = self.get_menu_window(login, entries, ids, caption)
            frame = frame.replace("%width%", str(windowwidth - 1)).replace("%lblwidth%", str(windowwidth - 5)).replace("%indx%", str(windowwidth - 3))
            content += f'<frame posn="{windowx + 0.5} {windowy - 0.5}">{frame}</frame>'

            content += (
                self.blocks["close"]
                .replace("%pos%", f"{windowx + windowwidth - 1.6} {windowy - 1.4}")
                .replace("%action%", closeaction)
            )

            posx = windowx + windowwidth if self.horientation == 1 else windowx
            posy = windowy
            oldId = wid

        header = self.blocks["header"].replace("%menuid%", self.manialink_id + "0001").replace("%framepos%", "0 0 1")
        footer = self.blocks["footer"]
        xml = header + content + footer

        await self.aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, self.menutimeout, False)

    def get_item_offset(self, entries: list[FufiMenuEntry], id_: str) -> float:
        result = 0.0
        for entry in entries:
            if entry.id == id_:
                return result
            result -= self.separatorheight if entry.type == "separator" else 2.0
        return result

    def get_window_ids(self, id_: str) -> list[str]:
        result = [id_]
        while id_ != "0000":
            entry = self.get_entry_by_id(id_)
            if not isinstance(entry, FufiMenuEntry):
                break
            id_ = entry.parentid
            result.append(id_)
        return list(reversed(result))

    def get_window_height(self, entries: list[FufiMenuEntry]) -> float:
        result = 0.0
        for entry in entries:
            result += self.separatorheight if entry.type == "separator" else 2.0
        return result + 3.0

    def get_window_width(self, entries: list[FufiMenuEntry]) -> float:
        longest = 0
        for entry in entries:
            longest = max(longest, len(entry.caption))
        return max(10.0, float(int((longest + 1) / 2) + 7))

    def get_menu_window(self, login: str, entries: list[FufiMenuEntry], ids: list[str], caption: str) -> str:
        menuentry = self.blocks["menuentry"]
        menucaption = self.blocks["menuwindowcaption"]
        groupicon = self.blocks["icon"]
        indicatoricon = self.blocks["indicator"]

        y = -2.0
        result = menucaption.replace("%height%", "1.9").replace("%labely%", "-0.7").replace("%caption%", caption.strip())

        for entry in entries:
            if entry.id in ids:
                style = self.styles["menuentryactive"]["style"]
                substyle = self.styles["menuentryactive"]["substyle"]
                prefix = "$000"
            else:
                style = self.styles["menuentry"]["style"]
                substyle = self.styles["menuentry"]["substyle"]
                prefix = "$fff"

            if entry.type != "separator":
                xml = (
                    menuentry
                    .replace("%height%", "1.9")
                    .replace("%y%", str(y))
                    .replace("%labely%", str(y - 0.9))
                    .replace("%style%", style)
                    .replace("%substyle%", substyle)
                    .replace("%action%", self.manialink_id + entry.id)
                    .replace("%caption%", prefix + entry.caption)
                )

                if entry.is_group() and entry.type != "help":
                    xml += (
                        groupicon
                        .replace("%x%", "0.1")
                        .replace("%y%", str(y))
                        .replace("%style%", self.styles["menugroupicon"]["style"])
                        .replace("%substyle%", self.styles["menugroupicon"]["substyle"])
                    )
                else:
                    if entry.type == "help":
                        xml += (
                            groupicon
                            .replace("%x%", "0.1")
                            .replace("%y%", str(y))
                            .replace("%style%", self.styles["menuhelpicon"]["style"])
                            .replace("%substyle%", self.styles["menuhelpicon"]["substyle"])
                        )
                    elif not entry.caption.startswith("..."):
                        xml += (
                            groupicon
                            .replace("%x%", "0.3")
                            .replace("%y%", str(y - 0.1))
                            .replace("%style%", self.styles["menuactionicon"]["style"])
                            .replace("%substyle%", self.styles["menuactionicon"]["substyle"])
                        )

                if entry.indicator:
                    func = _resolve_indicator_func(entry.indicator)
                    if callable(func):
                        params: list[Any] = []
                        if entry.params:
                            params = entry.params.split(",") if "," in entry.params else [entry.params]
                        args = [self.aseco, login] + params
                        indicator = func(*args)

                        if indicator == 0:
                            xml += (
                                indicatoricon
                                .replace("%y%", str(y))
                                .replace("%style%", self.styles["indicatorfalse"]["style"])
                                .replace("%substyle%", self.styles["indicatorfalse"]["substyle"])
                            )
                        elif indicator == 1:
                            xml += (
                                indicatoricon
                                .replace("%y%", str(y))
                                .replace("%style%", self.styles["indicatortrue"]["style"])
                                .replace("%substyle%", self.styles["indicatortrue"]["substyle"])
                            )
                        elif indicator == 2:
                            xml += (
                                indicatoricon
                                .replace("%y%", str(y))
                                .replace("%style%", self.styles["indicatoronhold"]["style"])
                                .replace("%substyle%", self.styles["indicatoronhold"]["substyle"])
                            )
                    elif self.aseco:
                        self.aseco.console('FufiMenu: Indicator function "{1}" does not exist.', entry.indicator)

                result += xml
                y -= 2.0
            else:
                y -= self.separatorheight

        return result

    def group_is_empty(self, entry: FufiMenuEntry, login: str) -> bool:
        for ent in entry.get_valid_entries(self, login):
            if ent.type != "separator":
                return False
        return True


async def fufiMenu_playerConnect(aseco: "Aseco", player: "Player"):
    global _fufi_menu
    if not _fufi_menu:
        return
    if not _fufi_menu.aseco:
        _fufi_menu.aseco = aseco
    if getattr(getattr(aseco.server, "gameinfo", None), "mode", -1) == getattr(Gameinfo, "SCOR", 7):
        await _fufi_menu.close_menu(player.login)
        return
    await _fufi_menu.send_menu_button_to_login(player.login)


async def fufiMenu_handleClick(aseco: "Aseco", command: list):
    global _fufi_menu
    if not _fufi_menu or len(command) < 3:
        return
    await _fufi_menu.handle_click(command[0], command[1], str(command[2]))


async def fufiMenu_startup(aseco: "Aseco", _param=None):
    global _fufi_menu
    if not _fufi_menu:
        bound = bind_app_settings(FUFI_MENU_SETTINGS_SCHEMA, getattr(aseco, "_base_dir", None))
        config = bound.values["config"] if isinstance(bound.values["config"], dict) else {}
        if not isinstance(config, dict) or not config:
            logger.warning("[FufiMenu] No TOML configuration found in app_defaults.toml, menu disabled")
            return
        logger.info("[FufiMenu] Config loaded from %s", display_path(bound.source_path))
        _fufi_menu = FufiMenu(config, bound.source_path)
        _fufi_menu.aseco = aseco
        _fufi_menu.init()
    elif not _fufi_menu.aseco:
        _fufi_menu.aseco = aseco

    await aseco.release_event("onMenuLoaded", _fufi_menu)


async def fufiMenu_newChallenge(aseco: "Aseco", _param=None):
    global _fufi_menu
    if not _fufi_menu:
        return
    await _fufi_menu.send_menu_button_to_login("")


async def fufiMenu_endRace(aseco: "Aseco", _param=None):
    global _fufi_menu
    if not _fufi_menu:
        return
    await _fufi_menu.hide_menu_everywhere()


# ------------------------------------------------------------
# Indicator functions
# Return:
#   0 = red
#   1 = green
#   2 = yellow
#  -1 = none
# ------------------------------------------------------------

def _get_jfreu_state():
    global _fufi_menu
    if not _fufi_menu:
        return None
    return _fufi_menu.get_shared_attr("jfreu", default=None)

def fufi_getCPSIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    checkpoints = _fufi_menu.get_shared_attr("checkpoints", default={}) if _fufi_menu else {}
    try:
        return int(login in checkpoints and getattr(checkpoints[login], "loclrec", -1) != -1)
    except Exception:
        return 0

def fufi_getDediCPSIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    checkpoints = _fufi_menu.get_shared_attr("checkpoints", default={}) if _fufi_menu else {}
    try:
        return int(
            login in checkpoints
            and getattr(checkpoints[login], "loclrec", 1) != 1
            and getattr(checkpoints[login], "dedirec", -1) != -1
        )
    except Exception:
        return 0

def fufi_getCPSSpecIndicator(aseco: "Aseco", login: str):
    player = aseco.server.players.get_player(login)
    return int(bool(player and getattr(player, "speclogin", "")))


def fufi_getGameModeIndicator(aseco: "Aseco", login: str, gamemode):
    global _fufi_menu
    if not _fufi_menu:
        return -1
    currentgamemode = _fufi_menu.gameinfo.get("GameMode")
    nextgamemode = _fufi_menu.gameinfonext.get("GameMode")
    try:
        gm = int(gamemode)
    except Exception:
        return -1
    if gm == currentgamemode:
        return 1
    if gm == nextgamemode:
        return 2
    return -1


def fufi_getRefModeIndicator(aseco: "Aseco", login: str, refmode):
    global _fufi_menu
    if not _fufi_menu:
        return -1
    try:
        current = _fufi_menu.referee_mode
        if current is None:
            return -1
        return 1 if int(current) == int(refmode) else -1
    except Exception:
        return -1

def fufi_getChallengeDownloadIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    if not _fufi_menu:
        return -1
    try:
        allowed = _fufi_menu.challenge_download_allowed
        if allowed is None:
            return -1
        return int(bool(allowed))
    except Exception:
        return -1

def fufi_getRespawnDisabledIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    if not _fufi_menu:
        return -1
    return int(bool(_fufi_menu.gameinfonext.get("DisableRespawn", False)))


def fufi_getForceShowAllIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    if not _fufi_menu:
        return -1
    return int(bool(_fufi_menu.gameinfonext.get("ForceShowAllOpponents", False)))


def fufi_getScorePanelIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    value = _fufi_menu.get_shared_attr("auto_scorepanel", default=False) if _fufi_menu else False
    return int(bool(value))

def fufi_getRoundsPanelIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    value = _fufi_menu.get_shared_attr("rounds_finishpanel", default=False) if _fufi_menu else False
    return int(bool(value))

def fufi_getAutoTimeIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    value = _fufi_menu.get_shared_attr("atl_active", default=False) if _fufi_menu else False
    return int(bool(value))

def fufi_getDebugModeIndicator(aseco: "Aseco", login: str):
    return int(bool(getattr(aseco, "debug", False)))


def fufi_getAutoChangeNameIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "autochangename", False)))


def fufi_getRanklimitIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "ranklimit", False)))


def fufi_getAutoRankIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "autorank", False)))


def fufi_getAutoRankVIPIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "autorankvip", False)))


def fufi_getKickHiRankIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "kickhirank", False)))


def fufi_getBadwordsBotIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "badwords", False)))


def fufi_getBadwordsBanIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "badwordsban", False)))


def fufi_getJFreuVotesDisabledIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "novote", False)))


def fufi_getJFreuUnspecEnabledIndicator(aseco: "Aseco", login: str):
    jfreu = _get_jfreu_state()
    return int(bool(getattr(jfreu, "unspecvote", False)))


def fufi_getJFreuInfosIndicator(aseco: "Aseco", login: str, info):
    jfreu = _get_jfreu_state()
    try:
        return 1 if int(getattr(jfreu, "infomessages", -1)) == int(info) else -1
    except Exception:
        return -1

def fufi_getMatchEnabledIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    matchsettings = _fufi_menu.get_shared_attr("MatchSettings", default={}) if _fufi_menu else {}
    return int(bool(matchsettings.get("enable", False)))


def fufi_getMatchOthersIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    value = _fufi_menu.get_shared_attr("matchOthersCanScore", default=False) if _fufi_menu else False
    return int(bool(value))


def fufi_getMatchTeamforceIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    matchsettings = _fufi_menu.get_shared_attr("MatchSettings", default={}) if _fufi_menu else {}
    return int(bool(matchsettings.get("teamForceEnabled", False)))


def fufi_getMatchTeamchatIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    matchsettings = _fufi_menu.get_shared_attr("MatchSettings", default={}) if _fufi_menu else {}
    return int(bool(matchsettings.get("teamchatEnabled", False)))


def fufi_getMusicOverrideIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    music_server = _fufi_menu.get_shared_attr("music_server", default=None) if _fufi_menu else None
    return int(bool(getattr(music_server, "override", False))) if music_server else -1


def fufi_getMusicAutonextIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    music_server = _fufi_menu.get_shared_attr("music_server", default=None) if _fufi_menu else None
    return int(bool(getattr(music_server, "autonext", False))) if music_server else -1


def fufi_getMusicAutoshuffleIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    music_server = _fufi_menu.get_shared_attr("music_server", default=None) if _fufi_menu else None
    return int(bool(getattr(music_server, "autoshuffle", False))) if music_server else -1


def fufi_getMusicJukeboxIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    music_server = _fufi_menu.get_shared_attr("music_server", default=None) if _fufi_menu else None
    return int(bool(getattr(music_server, "allowjb", False))) if music_server else -1


def fufi_getMusicStripDirsIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    music_server = _fufi_menu.get_shared_attr("music_server", default=None) if _fufi_menu else None
    return int(bool(getattr(music_server, "stripdirs", False))) if music_server else -1


def fufi_getMusicStripExtsIndicator(aseco: "Aseco", login: str):
    global _fufi_menu
    music_server = _fufi_menu.get_shared_attr("music_server", default=None) if _fufi_menu else None
    return int(bool(getattr(music_server, "stripexts", False))) if music_server else -1
