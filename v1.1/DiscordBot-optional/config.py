from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DiscordRoute:
    guild_id: str
    channel_id: str
    allowed_server_ids: list[int]


@dataclass
class BotInstance:
    bot_id: int
    name: str
    group: str
    type: str
    xmlrpc_host: str
    xmlrpc_port: int
    xmlrpc_login: str
    xmlrpc_password: str
    xmlrpc_path: str
    raw: dict[str, Any]


@dataclass
class DiscordBotSettings:
    enabled: bool
    token_env: str
    command_prefix: str
    status_text: str
    max_message_length: int
    strip_tm_colors: bool
    send_feedback_message: bool
    routes: list[DiscordRoute]


@dataclass
class DiscordBotConfig:
    path: Path
    settings: DiscordBotSettings
    instances: list[BotInstance]

    def instance_by_id(self, bot_id: int) -> BotInstance | None:
        for inst in self.instances:
            if inst.bot_id == bot_id:
                return inst
        return None

    def route_for(self, guild_id: str | int, channel_id: str | int) -> DiscordRoute | None:
        g = str(guild_id)
        c = str(channel_id)
        for route in self.settings.routes:
            if route.guild_id == g and route.channel_id == c:
                return route
        return None

    def token(self) -> str:
        return os.environ.get(self.settings.token_env, "").strip()


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def load_config(path: str | Path | None = None) -> DiscordBotConfig:
    default_path = Path(__file__).resolve().parent / "servers.yaml"
    cfg_path = Path(
        path
        or os.environ.get("DISCORD_BOT_SERVERS_YAML")
        or default_path
    ).resolve()
    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings_raw = raw.get("settings", {}) or {}
    bot_raw = settings_raw.get("discord_bot", {}) or {}

    routes: list[DiscordRoute] = []
    for item in bot_raw.get("routes", []) or []:
        if not isinstance(item, dict):
            continue
        guild_id = str(item.get("guild_id") or "").strip()
        channel_id = str(item.get("channel_id") or "").strip()
        allowed = []
        for sid in item.get("allowed_server_ids", []) or []:
            try:
                allowed.append(int(sid))
            except Exception:
                continue
        if guild_id and channel_id and allowed:
            routes.append(DiscordRoute(guild_id=guild_id, channel_id=channel_id, allowed_server_ids=allowed))

    bot_settings = DiscordBotSettings(
        enabled=_to_bool(bot_raw.get("enabled"), False),
        token_env=str(bot_raw.get("token_env") or "DISCORD_BOT_TOKEN").strip(),
        command_prefix=str(bot_raw.get("command_prefix") or "-tm").strip(),
        status_text=str(bot_raw.get("status_text") or "TrackMania bridge").strip(),
        max_message_length=max(1, int(bot_raw.get("max_message_length") or 220)),
        strip_tm_colors=_to_bool(bot_raw.get("strip_tm_colors"), False),
        send_feedback_message=_to_bool(bot_raw.get("send_feedback_message"), True),
        routes=routes,
    )

    instances: list[BotInstance] = []
    for item in raw.get("instances", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            bot_id = int(item.get("bot_id"))
        except Exception:
            continue
        try:
            xmlrpc_port = int(item.get("xmlrpc_port"))
        except Exception:
            continue
        instances.append(
            BotInstance(
                bot_id=bot_id,
                name=str(item.get("name") or "").strip(),
                group=str(item.get("group") or "").strip(),
                type=str(item.get("type") or "").strip(),
                xmlrpc_host=str(item.get("xmlrpc_host") or "127.0.0.1").strip(),
                xmlrpc_port=xmlrpc_port,
                xmlrpc_login=str(item.get("xmlrpc_login") or "").strip(),
                xmlrpc_password=str(item.get("xmlrpc_password") or "").strip(),
                xmlrpc_path=str(item.get("xmlrpc_path") or "/RPC2").strip(),
                raw=item,
            )
        )

    return DiscordBotConfig(path=cfg_path, settings=bot_settings, instances=instances)
