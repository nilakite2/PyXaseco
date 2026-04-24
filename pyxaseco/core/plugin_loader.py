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
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


class PluginLoader:
    """Loads and initialises plugin modules."""

    def __init__(self, plugins_dir: str | Path = 'plugins'):
        self.plugins_dir = Path(plugins_dir)
        self._plugins_dir_str = str(self.plugins_dir.resolve())
        self._loaded: list[str] = []

    def load_all(self, plugin_filenames: list[str], aseco: 'Aseco'):
        """
        Load each plugin by filename (as listed in plugins.xml).

        Filenames are the PHP filename without the .php extension,
        e.g. 'chat.help' or 'plugin.chatlog'.

        The corresponding Python file is found by replacing dots with
        underscores: 'chat.help' -> 'chat_help.py'.
        """
        for filename in plugin_filenames:
            # Strip trailing .php if present (in case plugins.xml still has it)
            base = filename
            if base.endswith('.php'):
                base = base[:-4]
            # Convert dots to underscores for the Python module name
            module_name = base.replace('.', '_')
            self._load_plugin(module_name, aseco)

    def _load_plugin(self, module_name: str, aseco: 'Aseco'):
        """Import a single plugin module and call its register() function."""
        plugin_path = self.plugins_dir / f'{module_name}.py'

        if not plugin_path.exists():
            logger.error('PluginLoader: plugin file not found: %s', plugin_path)
            return

        if self._plugins_dir_str not in sys.path:
            # Package-backed plugins such as records_eyepiece live under the
            # shared plugins directory and should not need per-plugin sys.path
            # bootstrapping in their wrapper modules.
            sys.path.insert(0, self._plugins_dir_str)

        # Build a unique module name to avoid collisions
        full_module_name = f'pyxaseco_plugins.{module_name}'

        spec = importlib.util.spec_from_file_location(full_module_name, plugin_path)
        if spec is None or spec.loader is None:
            logger.error('PluginLoader: could not create spec for %s', plugin_path)
            return

        module = importlib.util.module_from_spec(spec)
        # Register under both names so any cross-plugin import style works
        sys.modules[full_module_name] = module
        sys.modules[f'pyxaseco.plugins.{module_name}'] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error('PluginLoader: error loading %s: %s', module_name, e, exc_info=True)
            return

        # Call register(aseco) if present
        if hasattr(module, 'register'):
            try:
                module.register(aseco)
                logger.info('PluginLoader: loaded %s', module_name)
                self._loaded.append(module_name)
            except Exception as e:
                logger.error('PluginLoader: register() failed for %s: %s',
                             module_name, e, exc_info=True)
        else:
            logger.warning('PluginLoader: %s has no register() function — skipping', module_name)

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._loaded)
