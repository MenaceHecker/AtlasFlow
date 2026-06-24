"""
Shared event type registry for AtlasFlow.

This module is the single source of truth for which event types are valid
and what payload each type expects. Both the API (ingestion validation) and
the worker (handler dispatch) derive their understanding of the event schema
from here.

To add a new event type:
  1. Add its string name to REGISTERED_EVENT_TYPES.
  2. Add a Pydantic model for its payload to EVENT_PAYLOAD_SCHEMAS.
  3. Register a handler in worker/app/services/handlers/builtin.py.

The set must stay in sync with the handler registry in the worker.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Per-type payload schemas
# ---------------------------------------------------------------------------


class PingPayload(BaseModel):
    """ping — no required fields; any payload is accepted."""

    model_config = {"extra": "allow"}


class DataTransformPayload(BaseModel):
    """data.transform — apply an operation to a set of string fields."""

    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value pairs to transform.",
    )
    operation: str = Field(
        default="uppercase",
        description="Transformation to apply. One of: uppercase, lowercase, reverse.",
    )


class NotifyPayload(BaseModel):
    """notify — send an outbound notification via a channel."""

    channel: str = Field(
        description="Delivery channel. One of: email, sms, push.",
    )
    recipient: str = Field(
        description="Destination address or token for the chosen channel.",
    )
    message: str = Field(
        description="Notification body text.",
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Maps event type string → Pydantic model for its payload.
#: Used by the API to validate incoming payloads and by the worker for docs.
EVENT_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "ping": PingPayload,
    "data.transform": DataTransformPayload,
    "notify": NotifyPayload,
}

#: Ordered set of accepted event type strings.
REGISTERED_EVENT_TYPES: frozenset[str] = frozenset(EVENT_PAYLOAD_SCHEMAS)
