from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register_alias(aseco: "Aseco", alias: str) -> None:
    """
    Preserve old loaded-plugin names for dependency checks during the v1.2
    transition. This lets renamed wrappers satisfy plugins that still validate
    against the historical module names.
    """
    loader = getattr(aseco, "_plugin_loader", None)
    if not loader:
        return
    loaded = getattr(loader, "_loaded", None)
    if isinstance(loaded, list) and alias not in loaded:
        loaded.append(alias)


def expose_impl_module(alias: str, module) -> None:
    """
    Ensure both historical plugin import paths resolve to the exact same
    implementation module instance during the v1.2 transition.
    """
    sys.modules[f'pyxaseco.plugins.{alias}'] = module
    sys.modules[f'pyxaseco_plugins.{alias}'] = module
