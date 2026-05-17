"""
v1.2 wrapper for plugin_records_eyepiece package
Category: ui
"""

import importlib
import sys

from pyxaseco.plugins._v12_alias import expose_impl_module, register_alias
from pyxaseco.plugins.ui.records_eyepiece import plugin as _impl

_package = importlib.import_module("ui.records_eyepiece")
sys.modules.setdefault("records_eyepiece", _package)
sys.modules.setdefault("pyxaseco.plugins.records_eyepiece", _package)
sys.modules.setdefault("pyxaseco_plugins.records_eyepiece", _package)

expose_impl_module("plugin_records_eyepiece", _impl)


def register(aseco):
    register_alias(aseco, "plugin_records_eyepiece")
    _impl.register(aseco)
