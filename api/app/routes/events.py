from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from app.models.schemas import EventDetail, EventIn, EventListResponse, EventOut
from app.services.events_service import create_event, get_event, list_events

router = APIRouter(prefix="/v1/events", tags=["Events"])

_404: dict[int | str, dict[str, str]] = {404: {"description": "Event not found"}}
_422: dict[int | str, dict[str, str]] = {
    422: {"description": "Validation error — check your request body or query parameters"}
}


@router.post(
    "",
    response_model=EventOut,
    status_code=200,
    summary="Ingest a new event",
    description=(
        "Creates a new event, persists it to DynamoDB, and enqueues it for "
        "background processing. The event is immediately returned with status "
        "`CREATED`.\n\n"
        "Pass an `Idempotency-Key` header to deduplicate requests. Sending the "
        "same key twice returns the original event ID without creating a duplicate."
    ),
    responses={**_422},
)
def post_event(
    body: EventIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EventOut:
    event_id, _ = create_event(body.type, body.payload, idempotency_key)
    return EventOut(event_id=event_id, status="CREATED")


@router.get(
    "/{event_id}",
    response_model=EventDetail,
    summary="Get a single event",
    description="Returns the full event record for the given ID, including status, payload, and result.",  # noqa: E501
    responses={**_404},
)
def get_event_by_id(event_id: str) -> EventDetail:
    item = get_event(event_id)
    if not item:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventDetail.model_validate(item)


@router.get(
    "",
    response_model=EventListResponse,
    summary="List events",
    description=(
        "Returns a paginated list of events. Filter by `status` to narrow results. "
        "Use `next_token` from the response to fetch the next page."
    ),
    responses={**_422},
)
def get_events(
    status: str | None = Query(
        default=None,
        description="Filter by event status. One of: CREATED, PROCESSING, COMPLETED, FAILED.",
    ),
    limit: int = Query(
        default=25,
        ge=1,
        le=200,
        description="Maximum number of events to return per page (1-200).",
    ),
    next_token: str | None = Query(
        default=None,
        description="Opaque pagination cursor returned by the previous response.",
    ),
) -> EventListResponse:
    result = list_events(status=status, limit=limit, last_pk=next_token)
    return EventListResponse(
        items=[EventDetail.model_validate(i) for i in result["items"]],
        next_token=result["next_token"],
    )