from __future__ import annotations

"""
plugin_fufi_menu.py — Port of Fufi Menu Plugin for XAseco

Original:
  Fufi Menu Plugin for XASECO by oorf-fuckfish
  Version 0.36

Port notes:
- Loads menu config from fufi_menu_config.xml
- Loads menu ML template from plugins/fufi/fufi_menu.xml
- Sends menu button on connect / new challenge
- Opens nested menu windows
- Executes menu actions by simulating a player chat command
- Allows external plugins to add entries/groups/separators via onMenuLoaded
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
import xml.etree.ElementTree as ET

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)

_fufi_menu: "FufiMenu | None" = None


def _resolve_indicator_func(name: str):
    if not name:
        return None

    func = globals().get(name)
    if callable(func):
        return func

    for mod_name, module in list(sys.modules.items()):
        if not module:
            continue
        if not (mod_name.startswith("pyxaseco_plugins.") or mod_name.startswith("pyxaseco.plugins.")):
            continue
        func = getattr(module, name, None)
        if callable(func):
            return func

    return None


def register(aseco: "Aseco"):
    aseco.register_event("onPlayerConnect", fufiMenu_playerConnect)
    aseco.register_event("onPlayerManialinkPageAnswer", fufiMenu_handleClick)
    aseco.register_event("onStartup", fufiMenu_startup)
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
                elif "/admin" in entry.chatcmd:
                    parts = entry.chatcmd.split()
                    cmd = parts[1] if len(parts) > 1 else ""
                    if menu.aseco.allow_ability(player, cmd):
                        result.append(entry)
                elif "/jfreu" in entry.chatcmd:
                    if menu.aseco.is_any_admin(player):
                        result.append(entry)
                else:
                    if entry.ability:
                        if menu.aseco.allow_ability(player, entry.ability):
                            result.append(entry)
                    else:
                        result.append(entry)

        filtered: list[FufiMenuEntry] = []
        for entry in result:
            if (not entry.is_group()) or (not menu.group_is_empty(entry, login)) or entry.type == "separator":
                filtered.append(entry)
        return filtered


class FufiMenu:
    def __init__(self, xmlpath: str | Path):
        self.manialink_id = "383"
        self.unique_id = 1001
        self.id = "0000"
        self.first_challenge = True

        self.xml_path = Path(xmlpath)
        self.xml_root = ET.parse(self.xml_path).getroot()

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

        self.plugin_list = ""
        self.aseco: Aseco | None = None
        self.gameinfo: dict[str, Any] = {}
        self.gameinfonext: dict[str, Any] = {}
        
        self.referee_mode: int | None = None
        self.challenge_download_allowed: int | None = None

    def init(self):
        self._load_plugin_list()
        self.load_settings()
        self.load_styles()
        self.load_entries()

    def _load_plugin_list(self):
        plugins_xml = Path("plugins.xml")
        if not plugins_xml.exists():
            return
        try:
            root = ET.parse(plugins_xml).getroot()
            vals = []
            for node in root.findall(".//plugin"):
                if not node.text:
                    continue
                name = node.text.strip()
                vals.append(name)
                # Store both the dotted form and the underscore stem so
                # that fufi_menu_config.xml dependency strings match regardless of
                # which naming convention plugins.xml uses.
                #
                # Dotted name ("chat.records.php") -> also add underscore stem ("chat_records")
                # Stem       ("chat_records")      -> also add dotted name      ("chat.records.php")
                # .py file   ("chat_records.py")   -> also add bare stem        ("chat_records")
                if name.endswith(".php"):
                    # Dotted name -> underscore stem: "chat.records.php" -> "chat_records"
                    alt = name[:-4].replace(".", "_")
                elif name.endswith(".py"):
                    # .py -> stem: "chat_records.py" -> "chat_records"
                    alt = name[:-3]
                else:
                    # Stem -> dotted name: "chat_records" -> "chat.records.php"
                    alt = name.replace("_", ".") + ".php"
                if alt != name:
                    vals.append(alt)
            self.plugin_list = "|".join(vals) + ("|" if vals else "")
        except Exception as e:
            logger.warning("[FufiMenu] Could not parse plugins.xml: %s", e)

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

    def get_plugin_state(self, plugin_name: str, default=None):
        """
        Best-effort plugin/module state lookup.
        """
        if not self.aseco:
            return globals().get(plugin_name, default)

        try:
            plugins = getattr(self.aseco.server, "plugins", None)
            if isinstance(plugins, dict) and plugin_name in plugins:
                return plugins[plugin_name]
        except Exception:
            pass

        try:
            if hasattr(self.aseco.server, plugin_name):
                return getattr(self.aseco.server, plugin_name)
        except Exception:
            pass

        try:
            if hasattr(self.aseco, plugin_name):
                return getattr(self.aseco, plugin_name)
        except Exception:
            pass

        return globals().get(plugin_name, default)

    def get_unique_id(self) -> str:
        uid = str(self.unique_id)
        self.unique_id += 1
        return uid

    def load_settings(self):
        position = (self.xml_root.findtext("position", "0 0")).split()
        size = (self.xml_root.findtext("size", "8 2")).split()

        self.separatorheight = float(self.xml_root.findtext("separatorheight", "0.5"))
        self.posx = float(position[0])
        self.posy = float(position[1])
        self.width = float(size[0])
        self.height = float(size[1])
        self.horientation = int(self.xml_root.findtext("horizontalorientation", "0"))
        self.vorientation = int(self.xml_root.findtext("verticalorientation", "0"))
        self.caption = self.xml_root.findtext("menu_caption", "Menu") or "Menu"
        self.menutimeout = int(self.xml_root.findtext("menutimeout", "0"))

        template_path = Path("./plugins/fufi/fufi_menu.xml")
        self.blocks = self.get_xml_template_blocks(template_path.read_text(encoding="utf-8", errors="ignore"))

    def load_styles(self):
        self.styles = {}
        styles_node = self.xml_root.find("styles")
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
            if styles_node is None:
                continue
            node = styles_node.find(element)
            if node is not None:
                self.styles[element]["style"] = node.attrib.get("style", "")
                self.styles[element]["substyle"] = node.attrib.get("substyle", "")

    def load_entries(self):
        entries_node = self.xml_root.find("entries")
        if entries_node is None:
            return

        for entry_node in entries_node.findall("entry"):
            deps = entry_node.attrib.get("dependencies", "")
            glob = entry_node.attrib.get("globalvariable", "")
            if self.dependencies_met(deps, glob):
                entry = self._entry_from_xml(entry_node, self.id)
                self.entries.append(entry)
                self.entries_list.append(entry)

    def _entry_from_xml(self, xml_node: ET.Element, parentid: str) -> FufiMenuEntry:
        entry = FufiMenuEntry(
            caption=xml_node.attrib.get("caption", ""),
            indicator=xml_node.attrib.get("indicator", ""),
            params=xml_node.attrib.get("params", ""),
            chatcmd=xml_node.attrib.get("chatcmd", ""),
            chatcmdparams=xml_node.attrib.get("chatcmdparams", ""),
            type=xml_node.attrib.get("type", ""),
            ability=xml_node.attrib.get("ability", ""),
            unique=xml_node.attrib.get("unique", ""),
            rights=(xml_node.attrib.get("rights", "").lower() == "tmuf"),
            id=self.get_unique_id(),
            parentid=parentid,
        )

        for sub in xml_node.findall("entry"):
            deps = sub.attrib.get("dependencies", "")
            glob = sub.attrib.get("globalvariable", "")
            if self.dependencies_met(deps, glob):
                child = self._entry_from_xml(sub, entry.id)
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

        entry = self._entry_from_xml(ET.Element("entry", attrib=attrib), parent.id)
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
            result = result and (f"{dep}|" in self.plugin_list or dep in self.plugin_list)

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
            if not self.first_challenge:
                if getattr(self.aseco, "debug", False):
                    self.aseco.console("[FufiMenu] sending menu button to login: {1}", login)
                await self.aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)

    async def handle_click(self, playerid: int, login: str, action: str):
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
                elif "/admin" in entry.chatcmd:
                    parts = entry.chatcmd.split()
                    cmd = parts[1] if len(parts) > 1 else ""
                    if self.aseco.allow_ability(player, cmd):
                        result.append(entry)
                elif "/jfreu" in entry.chatcmd:
                    if self.aseco.is_any_admin(player):
                        result.append(entry)
                else:
                    if entry.ability:
                        if self.aseco.allow_ability(player, entry.ability):
                            result.append(entry)
                    else:
                        result.append(entry)

        filtered: list[FufiMenuEntry] = []
        for entry in result:
            if (not entry.is_group()) or (not self.group_is_empty(entry, login)) or entry.type == "separator":
                filtered.append(entry)
        return filtered

    async def close_menu(self, login: str):
        xml = f'<?xml version="1.0" encoding="UTF-8"?><manialinks><manialink id="{self.manialink_id}0001"></manialink></manialinks>'
        await self.aseco.client.query_ignore_result("SendDisplayManialinkPageToLogin", login, xml, 0, False)

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
    await _fufi_menu.send_menu_button_to_login(player.login)


async def fufiMenu_handleClick(aseco: "Aseco", command: list):
    global _fufi_menu
    if not _fufi_menu or len(command) < 3:
        return
    await _fufi_menu.handle_click(command[0], command[1], str(command[2]))


async def fufiMenu_startup(aseco: "Aseco", _param=None):
    global _fufi_menu
    if not _fufi_menu:
        cfg_path = Path("fufi_menu_config.xml")
        if not cfg_path.exists():
            cfg_path = Path(getattr(aseco, "_base_dir", ".")) / "fufi_menu_config.xml"
        _fufi_menu = FufiMenu(cfg_path)
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
