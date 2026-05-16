from __future__ import annotations

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, model_validator
from typing import Any, Dict, List, Optional, Literal


EventStatus = Literal["CREATED", "PROCESSING", "COMPLETED", "FAILED"]


class EventIn(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)


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
    payload: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _remap_ddb_item(cls, data: Any) -> Any:
        """
        DynamoDB stores the payload as 'payload_inline' and timestamps
        under 'updated_at' / 'updatedAt' depending on which code path wrote
        the record. Normalise everything before Pydantic validates.
        """
        if not isinstance(data, dict):
            return data

        out = dict(data)

        # payload_inline -> payload
        if "payload_inline" in out and "payload" not in out:
            out["payload"] = out.pop("payload_inline")

        # updatedAt (camelCase from worker) -> updated_at
        if "updatedAt" in out and "updated_at" not in out:
            out["updated_at"] = out.pop("updatedAt")

        return out


class EventListResponse(BaseModel):
    """Returned by GET /v1/events."""
    items: List[EventDetail]
    next_token: Optional[str] = None