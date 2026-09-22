from __future__ import annotations

import asyncio
from collections import deque
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from pyxaseco.helpers import strip_colors
from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_bool, as_int, bind_app_settings
from pyxaseco.core.config import _load_dotenv, _env, display_path

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Challenge, Player

logger = logging.getLogger(__name__)


DISCORD_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id="discord",
    section_name="discord_webhook",
    description="Discord webhook settings",
    settings=(
        AppSetting("config/discord_webhook/enabled", False, as_bool),
        AppSetting("config/discord_webhook/mirror_player_chat", True, as_bool),
        AppSetting("config/discord_webhook/mirror_server_chat", False, as_bool),
        AppSetting("config/discord_webhook/mirror_admin_commands", True, as_bool),
        AppSetting("config/discord_webhook/mirror_joins_leaves", True, as_bool),
        AppSetting("config/discord_webhook/mirror_new_challenge", True, as_bool),
        AppSetting("config/discord_webhook/mirror_warnings_errors", True, as_bool),
        AppSetting("config/discord_webhook/strip_tm_colors", True, as_bool),
        AppSetting("config/discord_webhook/request_timeout", 10, as_int),
        AppSetting("config/discord_webhook/chat_throttle_player_threshold", 10, as_int),
        AppSetting("config/discord_webhook/chat_batch_window_ms", 1200, as_int),
        AppSetting("config/discord_webhook/chat_batch_max_lines", 8, as_int),
    ),
)


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


def _load_env_config(base_dir: Path | None) -> dict[str, str]:
    if base_dir is not None:
        _load_dotenv(base_dir / ".env")
    _load_dotenv(".env")
    return {
        "admin_webhook_url": _env("DISCORD_ADMIN_WEBHOOK_URL", "").strip(),
        "chat_webhook_url": _env("DISCORD_CHAT_WEBHOOK_URL", "").strip(),
        "admin_webhook_name": _env("DISCORD_ADMIN_WEBHOOK_NAME", "PyXaseco Admin").strip() or "PyXaseco Admin",
        "chat_webhook_name": _env("DISCORD_CHAT_WEBHOOK_NAME", "PyXaseco Chat").strip() or "PyXaseco Chat",
    }


def _load_config(aseco: "Aseco") -> DiscordWebhookConfig:
    cfg = DiscordWebhookConfig()
    bound = bind_app_settings(DISCORD_SETTINGS_SCHEMA, getattr(aseco, "_base_dir", None))
    if bound.source_path is None:
        logger.info("[DiscordWebhook] app_defaults.toml missing; using defaults")
        return cfg

    cfg.enabled = bound.values["config/discord_webhook/enabled"]
    cfg.mirror_player_chat = bound.values["config/discord_webhook/mirror_player_chat"]
    cfg.mirror_server_chat = bound.values["config/discord_webhook/mirror_server_chat"]
    cfg.mirror_admin_commands = bound.values["config/discord_webhook/mirror_admin_commands"]
    cfg.mirror_joins_leaves = bound.values["config/discord_webhook/mirror_joins_leaves"]
    cfg.mirror_new_challenge = bound.values["config/discord_webhook/mirror_new_challenge"]
    cfg.mirror_warnings_errors = bound.values["config/discord_webhook/mirror_warnings_errors"]
    cfg.strip_tm_colors = bound.values["config/discord_webhook/strip_tm_colors"]
    cfg.request_timeout = bound.values["config/discord_webhook/request_timeout"]
    cfg.chat_throttle_player_threshold = bound.values["config/discord_webhook/chat_throttle_player_threshold"]
    cfg.chat_batch_window_ms = bound.values["config/discord_webhook/chat_batch_window_ms"]
    cfg.chat_batch_max_lines = bound.values["config/discord_webhook/chat_batch_max_lines"]
    env_cfg = _load_env_config(getattr(aseco, "_base_dir", None))
    cfg.admin_webhook_url = env_cfg["admin_webhook_url"]
    cfg.chat_webhook_url = env_cfg["chat_webhook_url"]
    cfg.admin_webhook_name = env_cfg["admin_webhook_name"]
    cfg.chat_webhook_name = env_cfg["chat_webhook_name"]
    logger.info("[DiscordWebhook] Config loaded from %s", display_path(bound.source_path))
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
        logger.info("[DiscordWebhook] Disabled in app_defaults.toml")
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
