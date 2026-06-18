from __future__ import annotations

from typing import Any, Literal

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, model_validator

EventStatus = Literal["CREATED", "PROCESSING", "COMPLETED", "FAILED"]


class EventIn(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventOut(BaseModel):
    """Returned immediately after ingestion."""
    event_id: str
    status: EventStatus


class EventDetail(BaseModel):
    """
    Full event record returned by GET /v1/events/{event_id}.
    Strips internal storage fields (pk) and normalises naming.
    """
    event_id: str
    type: str
    status: EventStatus
    created_at: str
    updated_at: str
    attempts: int = 0
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _remap_ddb_item(cls, data: Any) -> Any:
        """
        DynamoDB stores the payload as 'payload_inline'. Older records may
        contain the legacy 'updatedAt' timestamp, so normalise those records
        before Pydantic validates them.
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
    items: list[EventDetail]
    next_token: str | None = None
