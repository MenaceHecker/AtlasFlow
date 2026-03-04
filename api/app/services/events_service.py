from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import ddb_resource, sqs_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch_seconds(minutes: int = 60) -> int:
    return int(time.time()) + minutes * 60


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _idem_table():
    return ddb_resource().Table(settings.idem_table)


def _get_queue_url() -> str:
    sqs = sqs_client()
    resp = sqs.get_queue_url(QueueName=settings.events_queue_name)
    return resp["QueueUrl"]


def create_event(event_type: str, payload: Dict[str, Any], idempotency_key: Optional[str]) -> Tuple[str, bool]:
    """
    Returns: (event_id, reused)
    reused=True if idempotency key already existed and we returned existing event_id.
    """
    now = _now_iso()

    # If no idempotency key, always create a new event
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
                "eventId": new_event_id,
                "createdAt": now,
                "ttl": _ttl_epoch_seconds(60),  # 60 min TTL (tune later)
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        _persist_and_enqueue(new_event_id, event_type, payload, now)
        return new_event_id, False

    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise

        # If key existseturn original eventId
        existing = idem.get_item(Key={"pk": idem_pk}).get("Item")
        if not existing or "eventId" not in existing:
            # Edge case can be existed but missing eventId so treating as new
            _persist_and_enqueue(new_event_id, event_type, payload, now)
            return new_event_id, False

        return existing["eventId"], True


def _persist_and_enqueue(event_id: str, event_type: str, payload: Dict[str, Any], now_iso: str) -> None:
    events = _events_table()
    sqs = sqs_client()

    pk = f"EVENT#{event_id}"
    item = {
        "pk": pk,
        "eventId": event_id,
        "type": event_type,
        "status": "CREATED",
        "createdAt": now_iso,
        "updatedAt": now_iso,
        "attempts": 0,
        "payloadInline": payload,
    }

    events.put_item(Item=item)

    queue_url = _get_queue_url()
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"event_id": event_id}),
        MessageAttributes={
            "event_type": {"StringValue": event_type, "DataType": "String"},
        },
    )


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
            # skipping complex LEK and just return first page for now
            pass

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