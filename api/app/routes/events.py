from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from app.models.schemas import EventDetail, EventIn, EventListResponse, EventOut
from app.services.events_service import create_event, get_event, list_events

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("", response_model=EventOut)
def post_event(
    body: EventIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    event_id, reused = create_event(body.type, body.payload, idempotency_key)
    # status is always CREATED at ingestion; reused just means we returned the existing event_id
    return EventOut(event_id=event_id, status="CREATED")


@router.get("/{event_id}", response_model=EventDetail)
def get_event_by_id(event_id: str):
    item = get_event(event_id)
    if not item:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventDetail.model_validate(item)


@router.get("", response_model=EventListResponse)
def get_events(
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    next_token: str | None = Query(default=None),
):
    result = list_events(status=status, limit=limit, last_pk=next_token)
    return EventListResponse(
        items=[EventDetail.model_validate(i) for i in result["items"]],
        next_token=result["next_token"],
    )