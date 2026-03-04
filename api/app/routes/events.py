from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional

from app.models.schemas import EventIn, EventOut
from app.services.events_service import create_event, get_event, list_events

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("", response_model=EventOut)
def post_event(
    body: EventIn,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    event_id, reused = create_event(body.type, body.payload, idempotency_key)
    # status always CREATED at ingestion, reused just means we returned the previous event_id
    return EventOut(event_id=event_id, status="CREATED")


@router.get("/{event_id}")
def get_event_by_id(event_id: str):
    item = get_event(event_id)
    if not item:
        raise HTTPException(status_code=404, detail="Event not found")
    return item


@router.get("")
def get_events(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    next_token: Optional[str] = Query(default=None),
):
    return list_events(status=status, limit=limit, last_pk=next_token)