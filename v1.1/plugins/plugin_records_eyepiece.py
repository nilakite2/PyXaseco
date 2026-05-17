from __future__ import annotations

import sys
from pathlib import Path

_plugins_dir = Path(__file__).resolve().parent
if str(_plugins_dir) not in sys.path:
    sys.path.insert(0, str(_plugins_dir))

from records_eyepiece.plugin import register