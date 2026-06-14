from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import ddb_resource, sqs_client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch_seconds(minutes: int = 60) -> int:
    return int(time.time()) + minutes * 60


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _idem_table():
    return ddb_resource().Table(settings.idem_table)


@lru_cache(maxsize=1)
def _get_queue_url() -> str:
    sqs = sqs_client()
    resp = sqs.get_queue_url(QueueName=settings.events_queue_name)
    return resp["QueueUrl"]


def create_event(event_type: str, payload: Dict[str, Any], idempotency_key: Optional[str]) -> Tuple[str, bool]:
    """
    Returns: (event_id, reused)
    If reused == True if idempotency key already existed and we returned existing event_id.
    """
    now = _now_iso()

    # If no idempotency key, then attempt to create a new event
    if not idempotency_key:
        event_id = str(uuid.uuid4())
        _persist_and_enqueue(event_id, event_type, payload, now)
        return event_id, False

    idem_pk = f"IDEMP#{idempotency_key}"
    idem = _idem_table()

    # Put-if-not-exists for idempotency key
    new_event_id = str(uuid.uuid4())
    try:
        idem.put_item(
            Item={
                "pk": idem_pk,
                "event_id": new_event_id,
                "created_at": now,
                "ttl": _ttl_epoch_seconds(60),  # 60 min TTL (tune later)
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        try:
            _persist_and_enqueue(new_event_id, event_type, payload, now)
        except Exception:
            try:
                idem.delete_item(
                    Key={"pk": idem_pk},
                    ConditionExpression="event_id = :event_id",
                    ExpressionAttributeValues={":event_id": new_event_id},
                )
            except Exception:
                logger.exception(
                    "Failed to release idempotency key after enqueue failure: %s",
                    idem_pk,
                )
            raise
        return new_event_id, False

    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise

        # If key exists, return original eventId
        existing = idem.get_item(Key={"pk": idem_pk}).get("Item")
        if not existing or "event_id" not in existing:
            # Edge case can be existed but missing eventId so treating as new
            _persist_and_enqueue(new_event_id, event_type, payload, now)
            return new_event_id, False

        return existing["event_id"], True


def _persist_and_enqueue(event_id: str, event_type: str, payload: Dict[str, Any], now_iso: str) -> None:
    events = _events_table()
    sqs = sqs_client()

    pk = f"EVENT#{event_id}"
    item = {
        "pk": pk,
        "event_id": event_id,
        "type": event_type,
        "status": "CREATED",
        "created_at": now_iso,
        "updated_at": now_iso,
        "attempts": 0,
        "payload_inline": payload,
    }

    events.put_item(Item=item)

    try:
        queue_url = _get_queue_url()
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"event_id": event_id}),
            MessageAttributes={
                "event_type": {"StringValue": event_type, "DataType": "String"},
            },
        )
    except Exception:
        try:
            events.delete_item(Key={"pk": pk})
        except Exception:
            logger.exception(
                "Failed to remove event after enqueue failure: event_id=%s",
                event_id,
            )
        raise


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    events = _events_table()
    pk = f"EVENT#{event_id}"
    resp = events.get_item(Key={"pk": pk})
    return resp.get("Item")


def list_events(status: Optional[str], limit: int, last_pk: Optional[str]) -> Dict[str, Any]:
    """
    Simple listing:
    - If status provided: query GSI by status (best-effort, LocalStack supports it)
    - Else: scan with limit 
    Pagination token is last evaluated key pk
    """
    events = _events_table()

    if status:
        kwargs: Dict[str, Any] = {
            "IndexName": "gsi_status",
            "KeyConditionExpression": "#s = :v",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":v": status},
            "Limit": limit,
        }
        if last_pk:
            # For GSI, LEK must match index keys as LocalStack can be picky
            kwargs["ExclusiveStartKey"] = {
                "status": status,
                "pk": last_pk
            }

        resp = events.query(**kwargs)
    else:
        kwargs2: Dict[str, Any] = {"Limit": limit}
        if last_pk:
            kwargs2["ExclusiveStartKey"] = {"pk": last_pk}
        resp = events.scan(**kwargs2)

    items = resp.get("Items", [])
    lek = resp.get("LastEvaluatedKey", {})
    next_token = lek.get("pk")
    return {"items": items, "next_token": next_token}
