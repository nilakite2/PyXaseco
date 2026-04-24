"""
Event bus for PyXaseco.

Port of Aseco::registerEvent() / Aseco::releaseEvent() from aseco.php.

In the PHP original, handlers were bare function names (strings) that
were looked up with is_callable() / call_user_func().  In Python we
register actual callables (functions or coroutines).

All handlers receive (aseco, param) — same signature as the PHP originals.
Handlers may be plain functions or async coroutines; both are supported.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Awaitable, Union

logger = logging.getLogger(__name__)

Handler = Union[Callable[..., None], Callable[..., Awaitable[None]]]


class EventBus:
    """
    Simple publish/subscribe event bus.

    Usage:
        bus = EventBus()

        # Register a handler:
        bus.register('onChat', my_handler)

        # Fire an event (awaitable):
        await bus.fire('onChat', aseco, chat_params)
    """

    def __init__(self):
        self._handlers: dict[str, list[Handler]] = {}

    def register(self, event_type: str, handler: Handler):
        """Register a handler for event_type."""
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug('EventBus: registered %s → %s', event_type, handler)

    def unregister(self, event_type: str, handler: Handler) -> bool:
        """Remove a previously registered handler. Returns True if found."""
        handlers = self._handlers.get(event_type, [])
        try:
            handlers.remove(handler)
            return True
        except ValueError:
            return False

    async def fire(self, event_type: str, aseco: Any, param: Any = None):
        """
        Call all handlers registered for event_type.
        Both sync and async handlers are supported.
        Exceptions in individual handlers are logged but do not abort others.
        """
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                result = handler(aseco, param)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error('EventBus: handler %s raised for event %s: %s',
                             handler, event_type, e, exc_info=True)

    def has_handlers(self, event_type: str) -> bool:
        return bool(self._handlers.get(event_type))

    def registered_events(self) -> list[str]:
        return list(self._handlers.keys())
