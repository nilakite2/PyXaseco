from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedBridgeCommand:
    server_id: int
    message: str


def parse_tm_command(text: str, prefix: str = "-tm") -> ParsedBridgeCommand | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    base = str(prefix or "-tm").strip()
    if not raw.lower().startswith(base.lower()):
        return None

    rest = raw[len(base):].strip()
    if not rest:
        return None

    parts = rest.split(None, 1)
    server_token = parts[0].strip()
    if not server_token.isdigit():
        return None

    if len(parts) < 2:
        return None

    message = parts[1].strip()
    if not message:
        return None

    return ParsedBridgeCommand(server_id=int(server_token), message=message)
