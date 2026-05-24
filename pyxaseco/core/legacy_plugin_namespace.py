from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import types
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_DISABLED_ROOT = _ROOT / "not_required" / "apps" / "00disabled"


CONTAINER_PACKAGES = {
    "pyxaseco.plugins.bridge",
    "pyxaseco.plugins.chat",
    "pyxaseco.plugins.core",
    "pyxaseco.plugins.feature",
    "pyxaseco.plugins.service",
    "pyxaseco.plugins.skip",
    "pyxaseco.plugins.ui",
}


MODULE_ALIASES = {
    "pyxaseco.plugins.helpers": "pyxaseco.helpers",
    "pyxaseco.plugins.bridge.discord": "apps.discord.bridge",
    "pyxaseco.plugins.bridge.public_stats": "apps.public_stats.bridge",
    "pyxaseco.plugins.bridge.server_admin_bridge": "apps.admin.bridge",
    "pyxaseco.plugins.chat.admin": "apps.admin.chat",
    "pyxaseco.plugins.chat.dedimania": "apps.dedimania.chat",
    "pyxaseco.plugins.chat.help": "apps.help.commands",
    "pyxaseco.plugins.chat.laston": "apps.players.laston",
    "pyxaseco.plugins.chat.lastwin": "apps.platform_core.lastwin",
    "pyxaseco.plugins.chat.me": "apps.social_chat.commands",
    "pyxaseco.plugins.chat.players": "apps.players.players",
    "pyxaseco.plugins.chat.players2": "apps.players.players2",
    "pyxaseco.plugins.chat.records": "apps.records_local.chat_records",
    "pyxaseco.plugins.chat.records2": "apps.records_local.chat_records2",
    "pyxaseco.plugins.chat.recrels": "apps.records_local.chat_recrels",
    "pyxaseco.plugins.chat.server": "apps.server_info.commands",
    "pyxaseco.plugins.chat.songmod": "apps.track.commands",
    "pyxaseco.plugins.chat.stats": "apps.player_stats.commands",
    "pyxaseco.plugins.chat.wins": "apps.players.wins",
    "pyxaseco.plugins.core.chatlog": "apps.platform_core.chatlog",
    "pyxaseco.plugins.core.checkpoints": "apps.platform_core.checkpoints",
    "pyxaseco.plugins.core.donate": "apps.platform_core.donate",
    "pyxaseco.plugins.core.localdb": "apps.platform_core.localdb",
    "pyxaseco.plugins.core.rounds": "apps.platform_core.rounds",
    "pyxaseco.plugins.core.track": "apps.platform_core.track",
    "pyxaseco.plugins.core.uptodate": "apps.platform_core.uptodate",
    "pyxaseco.plugins.feature.best_cp_times_v2": "apps.best_cp_times.best_cp_times_v2",
    "pyxaseco.plugins.feature.bestcps": "apps.bestcps.feature",
    "pyxaseco.plugins.feature.bestfinishes": "apps.bestfinishes.feature",
    "pyxaseco.plugins.feature.bestruns": "apps.bestruns.feature",
    "pyxaseco.plugins.feature.bestsecs": "apps.bestsecs.feature",
    "pyxaseco.plugins.feature.cplive": "apps.cplive.feature",
    "pyxaseco.plugins.feature.cpll": "apps.cpll.feature",
    "pyxaseco.plugins.feature.jfreu": "apps.jfreu.feature",
    "pyxaseco.plugins.feature.mania_karma": "apps.mania_karma.service",
    "pyxaseco.plugins.feature.rasp": "apps.rasp.rasp",
    "pyxaseco.plugins.feature.rasp_chat": "apps.rasp.rasp_chat",
    "pyxaseco.plugins.feature.rasp_jukebox": "apps.rasp.rasp_jukebox",
    "pyxaseco.plugins.feature.rasp_nextmap": "apps.rasp.rasp_nextmap",
    "pyxaseco.plugins.feature.rasp_nextrank": "apps.rasp.rasp_nextrank",
    "pyxaseco.plugins.feature.rasp_votes": "apps.rasp.rasp_votes",
    "pyxaseco.plugins.feature.tmxvideo": "apps.tmxvideo.feature",
    "pyxaseco.plugins.feature.ztrack": "apps.ztrack.feature",
    "pyxaseco.plugins.service.dedimania": "apps.dedimania.service",
    "pyxaseco.plugins.service.discord_webhook": "apps.discord.service",
    "pyxaseco.plugins.service.mania_karma": "apps.mania_karma.service",
    "pyxaseco.plugins.service.records_rpg": "apps.records_rpg.service",
    "pyxaseco.plugins.service.tmx": "apps.tmx.service",
    "pyxaseco.plugins.service.trial_records": "apps.trial_records.service",
    "pyxaseco.plugins.ui.banner": "apps.platform_ui.banner",
    "pyxaseco.plugins.ui.fufi_menu": "apps.fufi_menu.ui",
    "pyxaseco.plugins.ui.panels": "apps.platform_ui.panels",
    "pyxaseco.plugins.ui.records_eyepiece": "apps.records_eyepiece",
    "pyxaseco.plugins.ui.records_eyepiece.app": "apps.records_eyepiece.app",
    "pyxaseco.plugins.ui.records_eyepiece.config": "apps.records_eyepiece.config",
    "pyxaseco.plugins.ui.records_eyepiece.handlers": "apps.records_eyepiece.handlers",
    "pyxaseco.plugins.ui.records_eyepiece.handlers.actions": "apps.records_eyepiece.handlers.actions",
    "pyxaseco.plugins.ui.records_eyepiece.handlers.chat": "apps.records_eyepiece.handlers.chat",
    "pyxaseco.plugins.ui.records_eyepiece.handlers.events": "apps.records_eyepiece.handlers.events",
    "pyxaseco.plugins.ui.records_eyepiece.helpers": "apps.records_eyepiece.helpers",
    "pyxaseco.plugins.ui.records_eyepiece.helpwin": "apps.records_eyepiece.helpwin",
    "pyxaseco.plugins.ui.records_eyepiece.plugin": "apps.records_eyepiece.plugin",
    "pyxaseco.plugins.ui.records_eyepiece.state": "apps.records_eyepiece.state",
    "pyxaseco.plugins.ui.records_eyepiece.toml_loader": "apps.records_eyepiece.toml_loader",
    "pyxaseco.plugins.ui.records_eyepiece.toplists": "apps.records_eyepiece.toplists",
    "pyxaseco.plugins.ui.records_eyepiece.tracklist": "apps.tmx.tracklist",
    "pyxaseco.plugins.ui.records_eyepiece.ui": "apps.records_eyepiece.ui",
    "pyxaseco.plugins.ui.records_eyepiece.utils": "apps.records_eyepiece.utils",
    "pyxaseco.plugins.ui.records_eyepiece.widgets": "apps.records_eyepiece.widgets",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.bar_widgets": "apps.records_eyepiece.widgets.bar_widgets",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.challenge": "apps.records_eyepiece.challenge_widget",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.checkpoint": "apps.records_eyepiece.widgets.checkpoint",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.clock_tz": "apps.records_eyepiece.widgets.clock_tz",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.common": "apps.records_eyepiece.widgets.common",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.live": "apps.records_eyepiece.widgets.live",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.records_common": "apps.records_eyepiece.widgets.records_common",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.records_dedi": "apps.dedimania.records_widget",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.records_local": "apps.records_local.records_widget",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.records_rpg": "apps.records_rpg.records_widget",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.score_widgets": "apps.records_eyepiece.widgets.score_widgets",
    "pyxaseco.plugins.ui.records_eyepiece.widgets.trial_records": "apps.trial_records.records_widget",
    "pyxaseco.plugins.ui.style": "apps.platform_ui.style",
}


FILE_ALIASES = {
    "pyxaseco.plugins.feature.rpoints": _DISABLED_ROOT / "skip" / "rpoints.py",
    "pyxaseco.plugins.plugin_access": _DISABLED_ROOT / "skip" / "access.py",
    "pyxaseco.plugins.plugin_autotime": _DISABLED_ROOT / "skip" / "autotime.py",
    "pyxaseco.plugins.plugin_flexitime": _DISABLED_ROOT / "skip" / "flexitime.py",
    "pyxaseco.plugins.plugin_msglog": _DISABLED_ROOT / "skip" / "msglog.py",
    "pyxaseco.plugins.plugin_muting": _DISABLED_ROOT / "skip" / "muting.py",
    "pyxaseco.plugins.plugin_rasp_karma": _DISABLED_ROOT / "skip" / "rasp_karma.py",
    "pyxaseco.plugins.plugin_rpoints": _DISABLED_ROOT / "skip" / "rpoints.py",
    "pyxaseco.plugins.service.freezone": _DISABLED_ROOT / "service" / "freezone.py",
    "pyxaseco.plugins.skip.access": _DISABLED_ROOT / "skip" / "access.py",
    "pyxaseco.plugins.skip.autotime": _DISABLED_ROOT / "skip" / "autotime.py",
    "pyxaseco.plugins.skip.flexitime": _DISABLED_ROOT / "skip" / "flexitime.py",
    "pyxaseco.plugins.skip.mistral_idlekick": _DISABLED_ROOT / "skip" / "mistral_idlekick.py",
    "pyxaseco.plugins.skip.msglog": _DISABLED_ROOT / "skip" / "msglog.py",
    "pyxaseco.plugins.skip.muting": _DISABLED_ROOT / "skip" / "muting.py",
    "pyxaseco.plugins.skip.old_version.best_checkpoint_times": _DISABLED_ROOT / "skip" / "old_version" / "best_checkpoint_times.py",
    "pyxaseco.plugins.skip.rasp_karma": _DISABLED_ROOT / "skip" / "rasp_karma.py",
    "pyxaseco.plugins.skip.rpoints": _DISABLED_ROOT / "skip" / "rpoints.py",
    "pyxaseco.plugins.ui.stalker_actionids": _DISABLED_ROOT / "ui" / "stalker_actionids.py",
    "pyxaseco.plugins.ui.stalker_tools": _DISABLED_ROOT / "ui" / "stalker_tools.py",
    "pyxaseco.plugins.ui.tgj_allbutton": _DISABLED_ROOT / "ui" / "tgj_allbutton.py",
}


def install_legacy_plugin_finder() -> None:
    for finder in sys.meta_path:
        if isinstance(finder, _LegacyPluginAliasFinder):
            return
    sys.meta_path.insert(0, _LegacyPluginAliasFinder())


def alias_for_entry(entry: str) -> str:
    normalized = (entry or "").replace("\\", "/").strip("/")
    return f"pyxaseco.plugins.{normalized.replace('/', '.')}"


class _ContainerLoader(importlib.abc.Loader):
    def create_module(self, spec):
        module = types.ModuleType(spec.name)
        module.__package__ = spec.name
        module.__path__ = []
        return module

    def exec_module(self, module) -> None:
        return None


class _ModuleAliasLoader(importlib.abc.Loader):
    def __init__(self, alias_name: str, target_name: str):
        self.alias_name = alias_name
        self.target_name = target_name

    def create_module(self, spec):
        target_module = importlib.import_module(self.target_name)
        sys.modules[self.alias_name] = target_module
        return target_module

    def exec_module(self, module) -> None:
        return None


class _LegacyPluginAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        if fullname in MODULE_ALIASES:
            loader = _ModuleAliasLoader(fullname, MODULE_ALIASES[fullname])
            target_module_name = MODULE_ALIASES[fullname]
            is_package = target_module_name in {
                "apps.records_eyepiece",
                "apps.records_eyepiece.handlers",
                "apps.records_eyepiece.widgets",
            }
            return importlib.util.spec_from_loader(fullname, loader, is_package=is_package)

        if fullname in FILE_ALIASES:
            file_path = FILE_ALIASES[fullname]
            if file_path.exists():
                return importlib.util.spec_from_file_location(fullname, file_path)
            return None

        if fullname in CONTAINER_PACKAGES:
            return importlib.util.spec_from_loader(fullname, _ContainerLoader(), is_package=True)

        return None
