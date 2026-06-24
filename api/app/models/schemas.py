"""
Pydantic schemas for the AtlasFlow public API.

These models define the API contract — what callers send and what they receive.
Internal DynamoDB fields (pk, payload_inline, updatedAt) are intentionally
absent here and are stripped or normalised by the model validators below.
"""
from __future__ import annotations

from typing import Any, Literal

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.event_types import EVENT_PAYLOAD_SCHEMAS, REGISTERED_EVENT_TYPES

EventStatus = Literal["CREATED", "PROCESSING", "COMPLETED", "FAILED"]


class EventIn(BaseModel):
    """Payload for ingesting a new event."""

    type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Registered event type string. "
            f"Accepted values: {sorted(REGISTERED_EVENT_TYPES)}."
        ),
        examples=["ping", "data.transform", "notify"],
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON payload whose shape must match the schema for the chosen event type.",
        examples=[{"amount": 42, "currency": "USD"}],
    )

    @field_validator("type")
    @classmethod
    def _type_must_be_registered(cls, v: str) -> str:
        if v not in REGISTERED_EVENT_TYPES:
            registered = sorted(REGISTERED_EVENT_TYPES)
            raise ValueError(
                f"Unknown event type {v!r}. "
                f"Registered types: {registered}"
            )
        return v

    @model_validator(mode="after")
    def _payload_must_match_schema(self) -> EventIn:
        """Validate payload shape against the per-type Pydantic schema."""
        schema_cls = EVENT_PAYLOAD_SCHEMAS.get(self.type)
        if schema_cls is None:
            # type not in registry — _type_must_be_registered already raised
            return self
        # Re-parse the payload through the per-type schema.
        # ValidationError propagates as a FastAPI 422 with structured detail.
        schema_cls.model_validate(self.payload)
        return self


class EventOut(BaseModel):
    """Returned immediately after a successful POST /v1/events."""

    event_id: str = Field(
        description="UUID of the newly created (or deduplicated) event.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    status: EventStatus = Field(
        description="Always CREATED at ingestion time.",
        examples=["CREATED"],
    )


class EventDetail(BaseModel):
    """
    Full event record returned by GET /v1/events/{event_id}.

    Internal DynamoDB fields (pk, payload_inline, updatedAt) are stripped
    and field names are normalised before this model is populated.
    """

    event_id: str = Field(description="UUID of the event.")
    type: str = Field(description="Event type string, e.g. 'order.placed'.")
    status: EventStatus = Field(
        description="Current lifecycle status of the event.",
    )
    created_at: str = Field(description="ISO-8601 UTC timestamp of when the event was ingested.")
    updated_at: str = Field(description="ISO-8601 UTC timestamp of the most recent status change.")
    attempts: int = Field(
        default=0,
        description="Number of times the worker has attempted to process this event.",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="The original payload submitted at ingestion.",
    )
    result: dict[str, Any] | None = Field(
        default=None,
        description="Handler output written on COMPLETED. Null until the event finishes.",
    )
    error: str | None = Field(
        default=None,
        description="Error message written on FAILED. Null for non-failed events.",
    )

    @model_validator(mode="before")
    @classmethod
    def _remap_ddb_item(cls, data: Any) -> Any:
        """
        Normalise raw DynamoDB items before Pydantic validates them.

        - Renames payload_inline -> payload (internal storage name).
        - Promotes updatedAt -> updated_at (legacy worker field name).
        """
        if not isinstance(data, dict):
            return data

        out = dict(data)

        # payload_inline -> payload
        if "payload_inline" in out and "payload" not in out:
            out["payload"] = out.pop("payload_inline")

        # Legacy worker writes may have both fields; updatedAt is the later value.
        if "updatedAt" in out:
            out["updated_at"] = out.pop("updatedAt")

        return out


class EventListResponse(BaseModel):
    """Returned by GET /v1/events."""

    items: list[EventDetail] = Field(description="Page of event records.")
    next_token: str | None = Field(
        default=None,
        description=(
            "Opaque cursor for the next page. Pass this value as the next_token "
            "query parameter to retrieve the following page. Null when there are "
            "no more results."
        ),
    )


class DlqReplayResponse(BaseModel):
    """Returned by POST /v1/admin/dlq/replay."""

    replayed: int = Field(
        description="Number of messages successfully moved from the DLQ to the main queue.",
    )
    skipped: int = Field(
        description=(
            "Number of messages skipped. A message is skipped if its body cannot "
            "be parsed, or if the corresponding event is no longer in FAILED status."
        ),
    )
    source_queue: str = Field(description="Name of the dead-letter queue messages were read from.")
    destination_queue: str = Field(description="Name of the main queue messages were sent to.")
