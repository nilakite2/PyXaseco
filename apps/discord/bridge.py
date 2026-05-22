from __future__ import annotations

"""
bridge/discord.py

Category bridge placeholder for the Discord integration family.

The actual outbound delivery logic lives in service/discord_webhook.py.
We keep this bridge entry loadable so the curated 1.2 loadout can express
that Discord is part of the active stack without double-registering the
service plugin.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def register(aseco: "Aseco"):
    aseco.console("[Discord] Bridge loaded; outbound webhook handling is owned by service/discord_webhook")
