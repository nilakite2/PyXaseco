from __future__ import annotations

import asyncio
from collections import deque
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from pyxaseco.helpers import strip_colors

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Challenge, Player

logger = logging.getLogger(__name__)


@dataclass
class DiscordWebhookConfig:
    enabled: bool = False
    admin_webhook_url: str = ""
    chat_webhook_url: str = ""
    admin_webhook_name: str = "PyXaseco Admin"
    chat_webhook_name: str = "PyXaseco Chat"
    mirror_player_chat: bool = True
    mirror_server_chat: bool = False
    mirror_admin_commands: bool = True
    mirror_joins_leaves: bool = True
    mirror_new_challenge: bool = True
    mirror_warnings_errors: bool = True
    strip_tm_colors: bool = True
    request_timeout: int = 10
    chat_throttle_player_threshold: int = 10
    chat_batch_window_ms: int = 1200
    chat_batch_max_lines: int = 8


class _DiscordLogHandler(logging.Handler):
    def __init__(self, state: "DiscordWebhookState"):
        super().__init__(level=logging.WARNING)
        self._state = state

    def emit(self, record: logging.LogRecord):
        if not self._state.cfg.mirror_warnings_errors:
            return
        if record.name.startswith(__name__):
            return
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        self._state.enqueue_sync("admin", f"[{record.levelname}] {message}")


class DiscordWebhookState:
    def __init__(self, aseco: "Aseco", cfg: DiscordWebhookConfig):
        self.aseco = aseco
        self.cfg = cfg
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.pending: deque[tuple[str, str]] = deque()
        self.session: aiohttp.ClientSession | None = None
        self.worker_task: asyncio.Task | None = None
        self.log_handler: _DiscordLogHandler | None = None

    def enabled_for(self, channel: str) -> bool:
        if not self.cfg.enabled:
            return False
        if channel == "admin":
            return bool(self.cfg.admin_webhook_url.strip())
        if channel == "chat":
            return bool(self.cfg.chat_webhook_url.strip())
        return False

    def enqueue_sync(self, channel: str, content: str):
        if not self.enabled_for(channel):
            return
        try:
            self.queue.put_nowait((channel, content))
        except Exception:
            logger.debug("[DiscordWebhook] Failed to queue sync message", exc_info=True)

    async def enqueue(self, channel: str, content: str):
        if not self.enabled_for(channel):
            return
        await self.queue.put((channel, content))

    async def start(self):
        timeout = aiohttp.ClientTimeout(total=max(1, int(self.cfg.request_timeout or 10)))
        self.session = aiohttp.ClientSession(timeout=timeout)
        self.worker_task = asyncio.create_task(self._worker(), name="discord-webhook-worker")

        if self.cfg.mirror_warnings_errors and self.enabled_for("admin"):
            handler = _DiscordLogHandler(self)
            handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
            logging.getLogger().addHandler(handler)
            self.log_handler = handler

    def _active_player_count(self) -> int:
        players = getattr(getattr(self.aseco, "server", None), "players", None)
        if players is None:
            return 0
        server_login = str(getattr(getattr(self.aseco, "server", None), "serverlogin", "") or "")
        try:
            return sum(
                1 for player in players.all()
                if getattr(player, "login", "")
                and getattr(player, "login", "") != server_login
                and not getattr(player, "isspectator", False)
            )
        except Exception:
            return 0

    def _should_throttle_chat(self) -> bool:
        return self._active_player_count() > max(0, int(self.cfg.chat_throttle_player_threshold or 10))

    async def _next_item(self) -> tuple[tuple[str, str], bool]:
        if self.pending:
            return self.pending.popleft(), False
        return await self.queue.get(), True

    async def _try_next_item(self, timeout_s: float) -> tuple[tuple[str, str], bool] | None:
        if self.pending:
            return self.pending.popleft(), False
        try:
            item = await asyncio.wait_for(self.queue.get(), timeout=max(0.0, timeout_s))
        except asyncio.TimeoutError:
            return None
        return item, True

    async def stop(self):
        if self.log_handler is not None:
            logging.getLogger().removeHandler(self.log_handler)
            self.log_handler = None

        if self.worker_task is not None:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None

        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _worker(self):
        while True:
            (channel, content), from_queue = await self._next_item()
            queue_items = 1 if from_queue else 0
            try:
                if channel == "chat" and self._should_throttle_chat():
                    lines = [content]
                    deadline = asyncio.get_running_loop().time() + (max(100, int(self.cfg.chat_batch_window_ms or 1200)) / 1000.0)
                    max_lines = max(1, int(self.cfg.chat_batch_max_lines or 8))
                    while len(lines) < max_lines:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            break
                        next_item = await self._try_next_item(remaining)
                        if next_item is None:
                            break
                        (next_channel, next_content), next_from_queue = next_item
                        if next_from_queue:
                            queue_items += 1
                        if next_channel == "chat" and self._should_throttle_chat():
                            lines.append(next_content)
                        else:
                            self.pending.appendleft((next_channel, next_content))
                            break
                    await self._send(channel, "\n".join(lines))
                else:
                    await self._send(channel, content)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("[DiscordWebhook] Send failed", exc_info=True)
            finally:
                for _ in range(queue_items):
                    self.queue.task_done()

    async def _send(self, channel: str, content: str):
        if not self.session:
            return

        url = self.cfg.admin_webhook_url if channel == "admin" else self.cfg.chat_webhook_url
        if not url:
            return

        body = {
            "content": _truncate_discord_content(content),
            "username": self.cfg.admin_webhook_name if channel == "admin" else self.cfg.chat_webhook_name,
        }
        async with self.session.post(url, json=body) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.warning(
                    "[DiscordWebhook] POST to %s webhook failed: %s %s",
                    channel,
                    resp.status,
                    text[:300],
                )


_state: DiscordWebhookState | None = None


def register(aseco: "Aseco"):
    aseco.register_event("onStartup", _dw_startup)
    aseco.register_event("onShutdown", _dw_shutdown)
    aseco.register_event("onChat", _dw_on_chat)
    aseco.register_event("onChat_admin", _dw_on_admin)
    aseco.register_event("onChat_ad", _dw_on_admin)
    aseco.register_event("onChat_a", _dw_on_admin)
    aseco.register_event("onPlayerConnect", _dw_on_player_connect)
    aseco.register_event("onPlayerDisconnect", _dw_on_player_disconnect)
    aseco.register_event("onNewChallenge", _dw_on_new_challenge)


def _parse_bool(text: str | None, default: bool) -> bool:
    if text is None:
        return default
    value = str(text).strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


def _load_config(aseco: "Aseco") -> DiscordWebhookConfig:
    cfg = DiscordWebhookConfig()
    path = Path(getattr(aseco, "_base_dir", Path.cwd())) / "discord_webhook.xml"
    if not path.exists():
        logger.info("[DiscordWebhook] Config file missing: %s", path)
        return cfg

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        logger.warning("[DiscordWebhook] Could not parse %s: %s", path, exc)
        return cfg

    section = root.find("discord_webhook")
    if section is None:
        section = root

    def _text(name: str, default: str = "") -> str:
        node = section.find(name)
        return str(node.text if node is not None and node.text is not None else default).strip()

    cfg.enabled = _parse_bool(_text("enabled", str(cfg.enabled)), cfg.enabled)
    cfg.admin_webhook_url = _text("admin_webhook_url", cfg.admin_webhook_url)
    cfg.chat_webhook_url = _text("chat_webhook_url", cfg.chat_webhook_url)
    cfg.admin_webhook_name = _text("admin_webhook_name", cfg.admin_webhook_name) or cfg.admin_webhook_name
    cfg.chat_webhook_name = _text("chat_webhook_name", cfg.chat_webhook_name) or cfg.chat_webhook_name
    cfg.mirror_player_chat = _parse_bool(_text("mirror_player_chat", str(cfg.mirror_player_chat)), cfg.mirror_player_chat)
    cfg.mirror_server_chat = _parse_bool(_text("mirror_server_chat", str(cfg.mirror_server_chat)), cfg.mirror_server_chat)
    cfg.mirror_admin_commands = _parse_bool(_text("mirror_admin_commands", str(cfg.mirror_admin_commands)), cfg.mirror_admin_commands)
    cfg.mirror_joins_leaves = _parse_bool(_text("mirror_joins_leaves", str(cfg.mirror_joins_leaves)), cfg.mirror_joins_leaves)
    cfg.mirror_new_challenge = _parse_bool(_text("mirror_new_challenge", str(cfg.mirror_new_challenge)), cfg.mirror_new_challenge)
    cfg.mirror_warnings_errors = _parse_bool(_text("mirror_warnings_errors", str(cfg.mirror_warnings_errors)), cfg.mirror_warnings_errors)
    cfg.strip_tm_colors = _parse_bool(_text("strip_tm_colors", str(cfg.strip_tm_colors)), cfg.strip_tm_colors)
    try:
        cfg.request_timeout = int(_text("request_timeout", str(cfg.request_timeout)) or cfg.request_timeout)
    except Exception:
        pass
    try:
        cfg.chat_throttle_player_threshold = int(_text("chat_throttle_player_threshold", str(cfg.chat_throttle_player_threshold)) or cfg.chat_throttle_player_threshold)
    except Exception:
        pass
    try:
        cfg.chat_batch_window_ms = int(_text("chat_batch_window_ms", str(cfg.chat_batch_window_ms)) or cfg.chat_batch_window_ms)
    except Exception:
        pass
    try:
        cfg.chat_batch_max_lines = int(_text("chat_batch_max_lines", str(cfg.chat_batch_max_lines)) or cfg.chat_batch_max_lines)
    except Exception:
        pass
    return cfg


def _clean_text(text: Any) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if _state and _state.cfg.strip_tm_colors:
        value = strip_colors(value, for_tm=False)
    return " ".join(value.split())


def _player_label(player: "Player") -> str:
    nick = _clean_text(getattr(player, "nickname", "") or getattr(player, "nick", ""))
    login = str(getattr(player, "login", "") or "").strip()
    if nick and login:
        return f"{nick} ({login})"
    return nick or login or "<unknown>"


def _truncate_discord_content(content: str) -> str:
    value = str(content or "")
    if len(value) <= 1900:
        return value
    return value[:1897] + "..."


async def _dw_startup(aseco: "Aseco", _param):
    global _state
    cfg = _load_config(aseco)
    _state = DiscordWebhookState(aseco, cfg)
    if not cfg.enabled:
        logger.info("[DiscordWebhook] Disabled in discord_webhook.xml")
        return

    await _state.start()
    await _state.enqueue("admin", f"[Startup] PyXaseco started on server: {_clean_text(getattr(aseco.server, 'name', ''))}")


async def _dw_shutdown(aseco: "Aseco", data):
    global _state
    if _state is None:
        return
    try:
        restart = bool((data or {}).get("restart")) if isinstance(data, dict) else False
        label = "Restart" if restart else "Shutdown"
        await _state.enqueue("admin", f"[{label}] PyXaseco is shutting down.")
        await asyncio.sleep(0.1)
    finally:
        await _state.stop()
        _state = None


async def _dw_on_chat(aseco: "Aseco", params: list):
    if _state is None or not _state.cfg.mirror_player_chat:
        return
    if len(params) < 3:
        return

    login = str(params[1] or "").strip()
    text = str(params[2] or "")
    if not text or text.startswith("/"):
        return

    server_login = str(getattr(aseco.server, "serverlogin", "") or "").strip().lower()
    is_server_login = bool(server_login and login.lower() == server_login)
    if is_server_login and not _state.cfg.mirror_server_chat:
        return

    player = aseco.server.players.get_player(login)
    label = _player_label(player) if player else (login or "server")
    await _state.enqueue("chat", f"[Chat] {label}: {_clean_text(text)}")


async def _dw_on_admin(_aseco: "Aseco", command: dict):
    if _state is None or not _state.cfg.mirror_admin_commands:
        return
    if not isinstance(command, dict):
        return
    player = command.get("author")
    params = str(command.get("params", "") or "").strip()
    invoked = str(command.get("command", "") or "").strip().lower()
    prefix_map = {
        "admin": "/admin",
        "ad": "/ad",
        "a": "/a",
    }
    prefix = prefix_map.get(invoked, "/admin")
    text = prefix if not params else f"{prefix} {params}"
    await _state.enqueue("admin", f"[AdminCmd] {_player_label(player)}: {text}")


async def _dw_on_player_connect(_aseco: "Aseco", player: "Player"):
    if _state is None or not _state.cfg.mirror_joins_leaves:
        return
    await _state.enqueue("admin", f"[Join] {_player_label(player)}")


async def _dw_on_player_disconnect(_aseco: "Aseco", player: "Player"):
    if _state is None or not _state.cfg.mirror_joins_leaves:
        return
    await _state.enqueue("admin", f"[Leave] {_player_label(player)}")


async def _dw_on_new_challenge(_aseco: "Aseco", challenge: "Challenge"):
    if _state is None or not _state.cfg.mirror_new_challenge:
        return
    name = _clean_text(getattr(challenge, "name", ""))
    author = _clean_text(getattr(challenge, "author", ""))
    await _state.enqueue("admin", f"[Map] New challenge: {name} | Author: {author}")
