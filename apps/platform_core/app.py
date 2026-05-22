from __future__ import annotations

from typing import TYPE_CHECKING

from pyxaseco.core.base import App

from . import chatlog, checkpoints, donate, lastwin, localdb, rounds, track, uptodate

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


APP_METADATA = {
    "id": "platform_core",
    "display_name": "Platform Core",
    "description": "Controller runtime backbone and low-level server state ownership.",
    "modules": [
        "apps/platform_core/localdb.py",
        "apps/platform_core/rounds.py",
        "apps/platform_core/track.py",
        "apps/platform_core/chatlog.py",
        "apps/platform_core/checkpoints.py",
        "apps/platform_core/donate.py",
        "apps/platform_core/uptodate.py",
        "apps/platform_core/lastwin.py",
    ],
    "entries": [
        "app/platform_core",
    ],
    "provides": [
        "core/localdb",
        "core/rounds",
        "core/track",
        "core/chatlog",
        "core/checkpoints",
        "core/donate",
        "core/uptodate",
        "chat/lastwin",
    ],
}


class PlatformCoreApp(App):
    def __init__(self):
        super().__init__(
            app_id="platform_core",
            display_name="Platform Core",
            description="Controller runtime backbone and low-level server state ownership.",
            entry_modules=("app/platform_core",),
        )


APP_CLASS = PlatformCoreApp


def register(aseco: "Aseco"):
    localdb.register(aseco)
    rounds.register(aseco)
    track.register(aseco)
    chatlog.register(aseco)
    checkpoints.register(aseco)
    donate.register(aseco)
    uptodate.register(aseco)
    lastwin.register(aseco)
