"""
Handler registry for AtlasFlow.

Usage — registering a handler:

    from app.services.handlers.registry import registry

    @registry.register("my.event.type")
    class MyHandler(BaseHandler):
        def handle(self, event_id, payload):
            ...
            return {"summary": "done"}

Usage — dispatching (done automatically by processor.py):

    result = registry.dispatch(event_type, event_id, payload)
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.handlers.base import BaseHandler

logger = logging.getLogger(__name__)


class HandlerRegistry:
    """Maps event-type strings to handler classes."""

    def __init__(self) -> None:
        self._handlers: dict[str, type[BaseHandler]] = {}

    def register(self, event_type: str):
        """
        Class decorator that registers a handler for the given event type.

        Example:
            @registry.register("ping")
            class PingHandler(BaseHandler): ...
        """
        def decorator(cls):
            if event_type in self._handlers:
                logger.warning(
                    "Handler for event_type=%r already registered; overwriting with %s",
                    event_type,
                    cls.__name__,
                )
            self._handlers[event_type] = cls
            return cls
        return decorator

    def dispatch(self, event_type: str, event_id: str, payload: dict) -> dict:
        """
        Look up the handler for event_type and run it.

        Falls back to FallbackHandler if the type is unknown.
        """
        from app.services.handlers.builtin import FallbackHandler

        handler_cls = self._handlers.get(event_type, FallbackHandler)
        handler = handler_cls()
        logger.info(
            "Dispatching event to handler",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "handler": handler_cls.__name__,
            },
        )
        t0 = time.perf_counter()
        result = handler.handle(event_id, payload)
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            "Handler finished",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "handler": handler_cls.__name__,
                "duration_ms": duration_ms,
            },
        )
        return result

    @property
    def registered_types(self) -> list[str]:
        """Returns the list of registered event type strings."""
        return list(self._handlers.keys())


# Module-level singleton — import and use this everywhere.
registry = HandlerRegistry()
