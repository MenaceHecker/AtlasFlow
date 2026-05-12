"""
Built-in event-type handlers for AtlasFlow.

This module both defines and registers all concrete handlers. Import it
(or let processor.py import it) to make the handlers available to the
registry. Adding a new event type is as simple as adding a new class with
the @registry.register decorator below.

Handler inventory:
    ping            -- health-check / no-op event
    data.transform  -- applies a key-value transformation to the payload
    notify          -- simulates sending an outbound notification
    * (fallback)    -- handles any unrecognised event type gracefully
"""
from __future__ import annotations

import logging

from app.services.handlers.base import BaseHandler
from app.services.handlers.registry import registry

logger = logging.getLogger(__name__)


@registry.register("ping")
class PingHandler(BaseHandler):
    """
    Health-check / smoke-test event.

    Accepts any payload and immediately returns a pong response. Useful for
    verifying the end-to-end pipeline is running without any side-effects.
    """

    def handle(self, event_id: str, payload: dict) -> dict:
        logger.info("PingHandler: event_id=%s", event_id)
        return {
            "handler": "PingHandler",
            "pong": True,
            "echo": payload,
        }


@registry.register("data.transform")
class DataTransformHandler(BaseHandler):
    """
    Applies a key-value transformation to the event payload.

    Expects the payload to contain a `fields` dict and an optional
    `operation` string ("uppercase" | "lowercase" | "reverse").

    Example payload:
        {"fields": {"name": "Alice", "city": "NYC"}, "operation": "uppercase"}

    Returns each field value transformed according to `operation`.
    """

    OPERATIONS = ("uppercase", "lowercase", "reverse")

    def handle(self, event_id: str, payload: dict) -> dict:
        fields: dict = payload.get("fields", {})
        operation: str = payload.get("operation", "uppercase")

        if operation not in self.OPERATIONS:
            raise ValueError(
                f"Unsupported operation {operation!r}. "
                f"Valid options: {self.OPERATIONS}"
            )

        transformed: dict[str, str] = {}
        for key, value in fields.items():
            str_val = str(value)
            if operation == "uppercase":
                transformed[key] = str_val.upper()
            elif operation == "lowercase":
                transformed[key] = str_val.lower()
            elif operation == "reverse":
                transformed[key] = str_val[::-1]

        logger.info(
            "DataTransformHandler: event_id=%s operation=%s fields=%d",
            event_id,
            operation,
            len(fields),
        )
        return {
            "handler": "DataTransformHandler",
            "operation": operation,
            "transformed": transformed,
        }


@registry.register("notify")
class NotifyHandler(BaseHandler):
    """
    Simulates sending an outbound notification.

    In a real system this would call an email/SMS/push service. Here it
    validates the payload shape and returns a delivery receipt so the
    end-to-end flow is realistic without requiring external credentials.

    Expected payload keys:
        channel   -- "email" | "sms" | "push"  (required)
        recipient -- destination address / token (required)
        message   -- text body                  (required)
    """

    SUPPORTED_CHANNELS = ("email", "sms", "push")

    def handle(self, event_id: str, payload: dict) -> dict:
        channel = payload.get("channel")
        recipient = payload.get("recipient")
        message = payload.get("message")

        if not channel:
            raise ValueError("notify payload missing required field: channel")
        if channel not in self.SUPPORTED_CHANNELS:
            raise ValueError(
                f"Unsupported channel {channel!r}. "
                f"Valid channels: {self.SUPPORTED_CHANNELS}"
            )
        if not recipient:
            raise ValueError("notify payload missing required field: recipient")
        if not message:
            raise ValueError("notify payload missing required field: message")

        logger.info(
            "NotifyHandler: event_id=%s channel=%s recipient=%s",
            event_id,
            channel,
            recipient,
        )

        # Simulate delivery — swap this for a real API call later.
        return {
            "handler": "NotifyHandler",
            "channel": channel,
            "recipient": recipient,
            "delivered": True,
            "message_preview": message[:80],
        }


class FallbackHandler(BaseHandler):
    """
    Fallback handler for unrecognised event types.

    Rather than crashing the worker on an unknown type, this handler logs a
    warning and marks the event COMPLETED with a note explaining what happened.
    This keeps the SQS queue moving while giving operators visibility via logs.
    """

    def handle(self, event_id: str, payload: dict) -> dict:
        logger.warning(
            "FallbackHandler: no registered handler for this event_type "
            "(event_id=%s). Marking completed with a warning.",
            event_id,
        )
        return {
            "handler": "FallbackHandler",
            "warning": "No handler registered for this event type. "
                       "Processed with fallback.",
        }
