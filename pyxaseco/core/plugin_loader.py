"""
Plugin loader for PyXaseco.

Mirrors Aseco::loadPlugins() from aseco.php.

PHP plugins used module-level calls at include time:
    Aseco::registerEvent('onChat', 'log_chat');
    Aseco::addChatCommand('chatlog', 'Displays log of recent chat messages');

In Python, each plugin module must expose a register(aseco) function that
performs those registrations.  The loader calls register(aseco) immediately
after importing the module.

Plugin file naming: PHP 'chat.chatlog.php' -> Python 'chat_chatlog.py'
(dots in the base name other than the extension are replaced with underscores)
"""

from __future__ import annotations
import importlib
import importlib.util
import sys
import logging
import re
import types
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


LEGACY_PLUGIN_ALIASES: dict[str, tuple[str, ...]] = {
    'core_localdb': ('plugin_localdatabase',),
    'core_rounds': ('plugin_rounds',),
    'core_track': ('plugin_track',),
    'feature_rasp': ('plugin_rasp',),
    'feature_rasp_jukebox': ('plugin_rasp_jukebox',),
    'feature_rasp_chat': ('plugin_rasp_chat',),
    'feature_rasp_nextmap': ('plugin_rasp_nextmap',),
    'feature_rasp_nextrank': ('plugin_rasp_nextrank',),
    'feature_rasp_votes': ('plugin_rasp_votes',),
    'service_tmx': ('plugin_tmxinfo',),
    'service_dedimania': ('plugin_dedimania',),
    'service_trial_records': ('plugin_trial_records',),
    'service_records_rpg': ('plugin_records_rpg',),
    'feature_jfreu': ('jfreu_plugin',),
    'ui_banner': ('plugin_banner',),
    'feature_cplive': ('plugin_cplive_v3',),
    'ui_records_eyepiece': ('plugin_records_eyepiece',),
    'ui_style': ('plugin_style',),
    'ui_panels': ('plugin_panels',),
    'bridge_public_stats': ('plugin_public_stats',),
    'bridge_server_admin_bridge': ('plugin_server_admin_bridge',),
}

ENTRY_REDIRECTS: dict[str, str] = {
    'core/rasp': 'feature/rasp',
    'chat_admin': 'chat/admin',
    'chat_help': 'chat/help',
    'chat_records': 'chat/records',
    'chat_records2': 'chat/records2',
    'chat_recrels': 'chat/recrels',
    'chat_dedimania': 'chat/dedimania',
    'chat_players': 'chat/players',
    'chat_players2': 'chat/players2',
    'chat_wins': 'chat/wins',
    'chat_laston': 'chat/laston',
    'chat_lastwin': 'chat/lastwin',
    'chat_stats': 'chat/stats',
    'chat_server': 'chat/server',
    'chat_songmod': 'chat/songmod',
    'chat_me': 'chat/me',
    'plugin_server_admin_bridge': 'bridge/server_admin_bridge',
    'plugin_style': 'ui/style',
    'plugin_panels': 'ui/panels',
    'plugin_rasp_jukebox': 'feature/rasp_jukebox',
    'plugin_rasp_chat': 'feature/rasp_chat',
    'plugin_rasp_nextmap': 'feature/rasp_nextmap',
    'plugin_rasp_nextrank': 'feature/rasp_nextrank',
    'plugin_rasp_votes': 'feature/rasp_votes',
    'ui/cplive': 'feature/cplive',
}


class PluginLoader:
    """Loads and initialises plugin modules."""

    def __init__(self, plugins_dir: str | Path = 'plugins'):
        self.plugins_dir = Path(plugins_dir)
        self._plugins_dir_str = str(self.plugins_dir.resolve())
        self._loaded: list[str] = []
        self._ensure_plugin_packages()

    def _ensure_plugin_packages(self):
        """
        Expose the shared plugins folder as importable package roots.

        This preserves historical cross-plugin imports such as:
        - ``from pyxaseco.plugins.plugin_localdatabase import ...``
        - ``from pyxaseco_plugins.plugin_tmxinfo import ...``

        without requiring every plugin to know whether it was loaded through
        the legacy flat loader or the v1.2 category wrappers.
        """
        if self._plugins_dir_str not in sys.path:
            sys.path.insert(0, self._plugins_dir_str)

        pyxaseco_pkg = sys.modules.get('pyxaseco.plugins')
        if pyxaseco_pkg is None:
            pyxaseco_pkg = types.ModuleType('pyxaseco.plugins')
            pyxaseco_pkg.__path__ = [self._plugins_dir_str]
            sys.modules['pyxaseco.plugins'] = pyxaseco_pkg
        elif not hasattr(pyxaseco_pkg, '__path__'):
            pyxaseco_pkg.__path__ = [self._plugins_dir_str]
        parent_pkg = sys.modules.get('pyxaseco')
        if parent_pkg is not None and getattr(parent_pkg, 'plugins', None) is None:
            setattr(parent_pkg, 'plugins', pyxaseco_pkg)

        plugin_pkg = sys.modules.get('pyxaseco_plugins')
        if plugin_pkg is None:
            plugin_pkg = types.ModuleType('pyxaseco_plugins')
            plugin_pkg.__path__ = [self._plugins_dir_str]
            sys.modules['pyxaseco_plugins'] = plugin_pkg
        elif not hasattr(plugin_pkg, '__path__'):
            plugin_pkg.__path__ = [self._plugins_dir_str]

    def load_all(self, plugin_filenames: list[str], aseco: 'Aseco'):
        """
        Load each plugin by filename (as listed in plugins.toml).

        Filenames are the PHP filename without the .php extension,
        e.g. 'chat.help' or 'plugin.chatlog'.

        The corresponding Python file is found by replacing dots with
        underscores: 'chat.help' -> 'chat_help.py'.
        """
        for filename in plugin_filenames:
            resolved = self._resolve_plugin(filename)
            if resolved is None:
                logger.error('PluginLoader: plugin file not found for entry: %s', filename)
                continue
            module_name, plugin_path = resolved
            self._load_plugin(module_name, plugin_path, aseco)

    def _resolve_plugin(self, filename: str) -> tuple[str, Path] | None:
        """
        Resolve a plugin entry from plugins.toml to a module name and file path.

        Resolution order:
        1. Legacy flat names such as ``chat.help`` -> ``chat_help.py``
        2. Category-style names such as ``core/localdb`` -> ``core_localdb.py``
        3. Structured file paths such as ``ui/records_eyepiece`` ->
           ``plugins/ui/records_eyepiece.py`` or ``plugins/ui/records_eyepiece/plugin.py``

        This lets v1.2 adopt clearer runtime-facing names immediately without
        forcing every plugin to move into subfolders on day one.
        """
        base = (filename or '').strip()
        if not base:
            return None
        if base.endswith('.php'):
            base = base[:-4]

        normalized = base.replace('\\', '/').strip('/')
        normalized = ENTRY_REDIRECTS.get(normalized, normalized)

        flat_name = normalized.replace('/', '_').replace('.', '_')
        flat_path = self.plugins_dir / f'{flat_name}.py'
        if flat_path.exists():
            return flat_name, flat_path

        parts = [part for part in re.split(r'[/.]+', normalized) if part]
        if not parts:
            return None

        path_root = self.plugins_dir.joinpath(*parts)
        candidates = (
            path_root.with_suffix('.py'),
            path_root / 'plugin.py',
            path_root / '__init__.py',
        )
        for candidate in candidates:
            if candidate.exists():
                module_name = '_'.join(parts)
                return module_name, candidate

        return None

    def _load_plugin(self, module_name: str, plugin_path: Path, aseco: 'Aseco'):
        """Import a single plugin module and call its register() function."""

        self._ensure_plugin_packages()

        # Build a unique module name to avoid collisions
        full_module_name = f'pyxaseco_plugins.{module_name}'

        spec = importlib.util.spec_from_file_location(full_module_name, plugin_path)
        if spec is None or spec.loader is None:
            logger.error('PluginLoader: could not create spec for %s', plugin_path)
            return

        module = importlib.util.module_from_spec(spec)
        # Register under every legacy import name so cross-plugin imports reuse
        # the same live module instance instead of importing the file twice.
        sys.modules[full_module_name] = module
        sys.modules[f'pyxaseco.plugins.{module_name}'] = module
        sys.modules[f'pyxaseco_plugins.{module_name}'] = module
        for alias in LEGACY_PLUGIN_ALIASES.get(module_name, ()):
            sys.modules[f'pyxaseco.plugins.{alias}'] = module
            sys.modules[f'pyxaseco_plugins.{alias}'] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error('PluginLoader: error loading %s: %s', module_name, e, exc_info=True)
            return

        # Call register(aseco) if present
        if hasattr(module, 'register'):
            try:
                module.register(aseco)
                logger.info('PluginLoader: loaded %s from %s', module_name, plugin_path)
                self._loaded.append(module_name)
                for alias in LEGACY_PLUGIN_ALIASES.get(module_name, ()):
                    if alias not in self._loaded:
                        self._loaded.append(alias)
            except Exception as e:
                logger.error('PluginLoader: register() failed for %s: %s',
                             module_name, e, exc_info=True)
        else:
            logger.warning('PluginLoader: %s has no register() function — skipping', module_name)

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._loaded)
