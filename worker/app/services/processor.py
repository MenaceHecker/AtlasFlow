"""
Core message processor for the AtlasFlow worker.

Flow for each SQS message:
  1. Parse message body -> extract event_id
  2. Fetch the full event record from DynamoDB (type + payload live there)
  3. Transition status: CREATED -> PROCESSING (conditional, prevents double-claim)
  4. Dispatch to the correct handler via the type registry
  5. Write result + COMPLETED status back to DynamoDB
  6. Any exception propagates to the caller (worker loop) so SQS retries

Importing this module does NOT load handlers. Handlers are loaded lazily when
process_message is first called, so tests can monkeypatch the registry before
the import side-effects run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import ddb_resource

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _pk(event_id: str) -> str:
    return f"EVENT#{event_id}"


def transition_to_processing(event_id: str) -> bool:
    """
    Claim a new event or retry a previously failed event.

    The conditional update prevents concurrent processing under at-least-once
    delivery. Completed events and events already being processed are skipped.
    """
    table = _events_table()
    try:
        table.update_item(
            Key={"pk": _pk(event_id)},
            UpdateExpression="SET #s = :p, updatedAt = :u ADD attempts :one",
            ConditionExpression="#s IN (:created, :failed)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":p": "PROCESSING",
                ":u": _now_iso(),
                ":created": "CREATED",
                ":failed": "FAILED",
                ":one": 1,
            },
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def mark_completed(event_id: str, result: dict[str, Any]) -> None:
    table = _events_table()
    table.update_item(
        Key={"pk": _pk(event_id)},
        UpdateExpression="SET #s = :c, updatedAt = :u, #r = :r REMOVE #e",
        ExpressionAttributeNames={"#s": "status", "#r": "result", "#e": "error"},
        ExpressionAttributeValues={":c": "COMPLETED", ":u": _now_iso(), ":r": result},
    )


def mark_failed(event_id: str, err: str) -> None:
    table = _events_table()
    table.update_item(
        Key={"pk": _pk(event_id)},
        UpdateExpression="SET #s = :f, updatedAt = :u, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":f": "FAILED", ":u": _now_iso(), ":e": err},
    )


def _fetch_event(event_id: str) -> dict[str, Any] | None:
    """Return the full DynamoDB item for event_id, or None if not found."""
    resp = _events_table().get_item(Key={"pk": _pk(event_id)})
    return resp.get("Item")


def process_message(body: str) -> None:
    """
    Entry point called by the worker loop for each SQS message.

    The message body only carries event_id. The event type and payload are
    fetched from DynamoDB so the SQS message stays small regardless of
    payload size.
    """
    # Lazy import keeps the module importable without side-effects in tests.
    import app.services.handlers.builtin  # noqa: F401 — triggers @registry.register calls
    from app.services.handlers.registry import registry

    msg = json.loads(body)
    event_id = msg["event_id"]

    item = _fetch_event(event_id)
    if item is None:
        logger.error("process_message: event_id=%s not found in DynamoDB; skipping", event_id)
        return

    event_type: str = item.get("type", "")
    payload: dict = item.get("payload_inline", {})

    claimed = transition_to_processing(event_id)
    if not claimed:
        logger.info("process_message: event_id=%s already claimed; skipping", event_id)
        return

    try:
        result = registry.dispatch(event_type, event_id, payload)
        mark_completed(event_id, result)
    except Exception as exc:
        mark_failed(event_id, str(exc))
        raise
