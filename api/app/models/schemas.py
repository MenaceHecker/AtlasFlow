from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Literal


EventStatus = Literal["CREATED", "PROCESSING", "COMPLETED", "FAILED"]


class EventIn(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventOut(BaseModel):
    event_id: str
    status: EventStatus


class EventRecord(BaseModel):
    pk: str
    event_id: str
    type: str
    status: EventStatus
    created_at: str
    updated_at: str
    attempts: int = 0
    payload_inline: Optional[Dict[str, Any]] = None