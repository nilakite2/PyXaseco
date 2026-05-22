"""Legacy plugin namespace backed by app aliases instead of `/plugins` files."""

from __future__ import annotations

from pyxaseco.core.legacy_plugin_namespace import install_legacy_plugin_finder

install_legacy_plugin_finder()

# Keep `pyxaseco.plugins` as a package namespace while resolution happens
# through the legacy alias finder rather than the top-level `/plugins` tree.
__path__: list[str] = []
