from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import requests
import websockets

if __package__:
    from .bridge import send_chat_to_instance
    from .commands import parse_tm_command
    from .config import DiscordBotConfig, load_config
else:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bridge import send_chat_to_instance
    from commands import parse_tm_command
    from config import DiscordBotConfig, load_config


logger = logging.getLogger("discord_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_BOT = f"{DISCORD_API_BASE}/gateway/bot"
MESSAGE_INTENTS = 1 | 512 | 32768
TM_COLOR_RE = re.compile(r"\$[0-9a-fA-F]{3}|\$.")


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _sanitize_message(cfg: DiscordBotConfig, message: str) -> str:
    text = str(message or "").strip()
    if cfg.settings.strip_tm_colors:
        text = TM_COLOR_RE.sub("", text)
    text = " ".join(text.split())
    if len(text) > cfg.settings.max_message_length:
        text = text[: cfg.settings.max_message_length].rstrip()
    return text


def _discord_display_name(data: dict) -> str:
    member = data.get("member") or {}
    user = data.get("author") or {}

    for value in (
        member.get("nick"),
        user.get("global_name"),
        user.get("username"),
    ):
        text = " ".join(str(value or "").split()).strip()
        if text:
            return text
    return "Discord"


class DiscordTmBridgeBot:
    def __init__(self, cfg: DiscordBotConfig):
        self.cfg = cfg
        self.token = cfg.token()
        self.sequence: int | None = None
        self.heartbeat_interval = 0.0
        self.heartbeat_task: asyncio.Task | None = None
        self.ws = None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bot {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "TM-Discord-Bridge (standalone, 1.0)",
            }
        )

    def gateway_url(self) -> str:
        resp = self.session.get(DISCORD_GATEWAY_BOT, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return f"{data['url']}?v=10&encoding=json"

    async def run_forever(self):
        while True:
            try:
                await self.run_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.warning("Gateway loop failed: %s", exc, exc_info=True)
                await asyncio.sleep(5)

    async def run_once(self):
        gateway = self.gateway_url()
        logger.info("Connecting to Discord gateway...")
        async with websockets.connect(gateway, max_size=4 * 1024 * 1024) as ws:
            self.ws = ws
            hello = json.loads(await ws.recv())
            if hello.get("op") != 10:
                raise RuntimeError(f"Expected HELLO, got: {hello}")

            self.heartbeat_interval = float(hello["d"]["heartbeat_interval"]) / 1000.0
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            await self._identify()

            try:
                async for raw in ws:
                    payload = json.loads(raw)
                    await self._handle_gateway_payload(payload)
            finally:
                if self.heartbeat_task is not None:
                    self.heartbeat_task.cancel()
                    try:
                        await self.heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    self.heartbeat_task = None
                self.ws = None

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            if self.ws is None:
                return
            await self.ws.send(json.dumps({"op": 1, "d": self.sequence}))

    async def _identify(self):
        if self.ws is None:
            return
        await self.ws.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": self.token,
                        "intents": MESSAGE_INTENTS,
                        "properties": {
                            "os": os.name,
                            "browser": "tm-discord-bridge",
                            "device": "tm-discord-bridge",
                        },
                        "presence": {
                            "status": "online",
                            "activities": [{"name": self.cfg.settings.status_text, "type": 0}],
                            "afk": False,
                        },
                    },
                }
            )
        )

    async def _handle_gateway_payload(self, payload: dict):
        op = payload.get("op")
        t = payload.get("t")
        d = payload.get("d")
        s = payload.get("s")
        if s is not None:
            self.sequence = s

        if op == 11:
            return
        if op == 7:
            raise RuntimeError("Discord requested reconnect")
        if op == 9:
            raise RuntimeError("Discord invalid session")
        if op == 1 and self.ws is not None:
            await self.ws.send(json.dumps({"op": 1, "d": self.sequence}))
            return

        if op != 0:
            return

        if t == "READY":
            user = (d or {}).get("user", {})
            logger.info("Logged in as %s (%s)", user.get("username"), user.get("id"))
            return

        if t == "MESSAGE_CREATE":
            await self._handle_message_create(d or {})

    async def _handle_message_create(self, data: dict):
        author = data.get("author") or {}
        if author.get("bot"):
            return

        guild_id = str(data.get("guild_id") or "").strip()
        channel_id = str(data.get("channel_id") or "").strip()
        content = str(data.get("content") or "")

        route = self.cfg.route_for(guild_id, channel_id)
        if route is None:
            return

        parsed = parse_tm_command(content, self.cfg.settings.command_prefix)
        if parsed is None:
            return

        if parsed.server_id not in route.allowed_server_ids:
            await self._send_feedback(channel_id, f"Server id {parsed.server_id} is not allowed in this channel.")
            return

        instance = self.cfg.instance_by_id(parsed.server_id)
        if instance is None:
            await self._send_feedback(channel_id, f"Unknown server id {parsed.server_id}.")
            return

        message = _sanitize_message(self.cfg, parsed.message)
        if not message:
            await self._send_feedback(channel_id, "Empty message after sanitizing.")
            return
        if message.startswith("/"):
            outbound = message
        else:
            sender = _discord_display_name(data)
            outbound = _sanitize_message(self.cfg, f"> {sender}: {message}")
        if not outbound:
            await self._send_feedback(channel_id, "Message became empty after formatting.")
            return

        try:
            await asyncio.to_thread(send_chat_to_instance, instance, outbound)
        except Exception as exc:
            logger.warning("Failed to send chat to %s: %s", instance.name, exc, exc_info=True)
            await self._send_feedback(channel_id, f"Failed to send to {instance.name}: {exc}")
            return

        logger.info("Relayed Discord message to %s: %s", instance.name, outbound)
        await self._send_feedback(channel_id, f"Sent to {instance.name}: {outbound}")

    async def _send_feedback(self, channel_id: str, text: str):
        if not self.cfg.settings.send_feedback_message:
            return
        await asyncio.to_thread(self._post_message, channel_id, text)

    def _post_message(self, channel_id: str, text: str):
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        resp = self.session.post(url, json={"content": text[:1900]}, timeout=15)
        if resp.status_code >= 400:
            logger.warning("Failed to post feedback to Discord: %s %s", resp.status_code, resp.text[:300])


def main():
    _load_local_env()
    cfg = load_config()
    if not cfg.settings.enabled:
        raise SystemExit(f"Discord bot disabled in {cfg.path.name} (settings.discord_bot.enabled=false).")
    if not cfg.token():
        raise SystemExit(f"Discord bot token missing in environment variable {cfg.settings.token_env!r}.")

    bot = DiscordTmBridgeBot(cfg)
    asyncio.run(bot.run_forever())


if __name__ == "__main__":
    main()
