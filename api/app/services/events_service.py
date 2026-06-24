from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import ddb_resource, s3_client, sqs_client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ttl_epoch_seconds(minutes: int = 60) -> int:
    return int(time.time()) + minutes * 60


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _idem_table():
    return ddb_resource().Table(settings.idem_table)


def _should_offload(payload: dict[str, Any]) -> bool:
    """Return True if the payload exceeds the configured byte threshold.

    Only offloads when PAYLOAD_BUCKET is configured — if the bucket is not
    set, payloads are always stored inline regardless of size.
    """
    if not settings.payload_bucket:
        return False
    payload_bytes = len(json.dumps(payload).encode())
    return payload_bytes > settings.payload_offload_threshold_bytes


@lru_cache(maxsize=1)
def _get_queue_url() -> str:
    sqs = sqs_client()
    resp = sqs.get_queue_url(QueueName=settings.events_queue_name)
    return resp["QueueUrl"]


def create_event(
    event_type: str, payload: dict[str, Any], idempotency_key: str | None
) -> tuple[str, bool]:
    """
    Returns: (event_id, reused)
    If reused == True if idempotency key already existed and we returned existing event_id.
    """
    now = _now_iso()

    # If no idempotency key, then attempt to create a new event
    if not idempotency_key:
        event_id = str(uuid.uuid4())
        logger.info(
            "Creating event",
            extra={"event_id": event_id, "event_type": event_type},
        )
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
            logger.info(
                "Creating event with idempotency key",
                extra={
                    "event_id": new_event_id,
                    "event_type": event_type,
                    "idempotency_key": idempotency_key,
                },
            )
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
                    "Failed to release idempotency key after enqueue failure",
                    extra={"event_id": new_event_id, "idempotency_key": idempotency_key},
                )
            raise
        return new_event_id, False

    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise

        # If key exists, return original eventId
        existing = idem.get_item(Key={"pk": idem_pk}).get("Item")
        if not existing or "event_id" not in existing:
            # Edge case: key existed but event_id missing — treat as new
            logger.warning(
                "Idempotency key exists but event_id missing; creating new event",
                extra={"idempotency_key": idempotency_key, "event_type": event_type},
            )
            _persist_and_enqueue(new_event_id, event_type, payload, now)
            return new_event_id, False

        existing_id = existing["event_id"]
        logger.info(
            "Idempotency key already used; returning existing event",
            extra={"event_id": existing_id, "idempotency_key": idempotency_key},
        )
        return existing_id, True


def _persist_and_enqueue(
    event_id: str, event_type: str, payload: dict[str, Any], now_iso: str
) -> None:
    events = _events_table()
    sqs = sqs_client()

    pk = f"EVENT#{event_id}"
    item: dict[str, Any] = {
        "pk": pk,
        "event_id": event_id,
        "type": event_type,
        "status": "CREATED",
        "created_at": now_iso,
        "updated_at": now_iso,
        "attempts": 0,
    }

    if _should_offload(payload):
        # Upload the payload to S3; store only the key in DynamoDB.
        s3_key = f"payloads/{event_id}.json"
        s3_client().put_object(
            Bucket=settings.payload_bucket,
            Key=s3_key,
            Body=json.dumps(payload).encode(),
            ContentType="application/json",
        )
        item["s3_key"] = s3_key
        logger.info(
            "Payload offloaded to S3",
            extra={"event_id": event_id, "s3_key": s3_key, "bucket": settings.payload_bucket},
        )
    else:
        item["payload_inline"] = payload

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
            # Clean up the S3 object if we uploaded one
            if "s3_key" in item:
                try:
                    s3_client().delete_object(
                        Bucket=settings.payload_bucket, Key=item["s3_key"]
                    )
                except Exception:
                    logger.exception(
                        "Failed to remove S3 payload after SQS enqueue failure",
                        extra={"event_id": event_id, "s3_key": item["s3_key"]},
                    )
        except Exception:
            logger.exception(
                "Failed to remove event after SQS enqueue failure",
                extra={"event_id": event_id, "event_type": event_type},
            )
        raise


def get_event(event_id: str) -> dict[str, Any] | None:
    events = _events_table()
    pk = f"EVENT#{event_id}"
    resp = events.get_item(Key={"pk": pk})
    return resp.get("Item")


def _encode_cursor(last_evaluated_key: dict[str, Any]) -> str:
    """
    Encode a DynamoDB LastEvaluatedKey into an opaque, URL-safe cursor string.

    We JSON-serialize the full key dict (which may contain 'pk', 'status', or
    other GSI attributes) and base64-encode it so callers never see raw DynamoDB
    key values. This also makes it safe to change the underlying key schema
    without a breaking API change.
    """
    return base64.urlsafe_b64encode(json.dumps(last_evaluated_key).encode()).decode()


def _decode_cursor(cursor: str) -> dict[str, Any]:
    """Reverse of _encode_cursor. Raises ValueError on malformed input."""
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc


def list_events(status: str | None, limit: int, last_pk: str | None) -> dict[str, Any]:
    """
    List events with optional status filtering and cursor-based pagination.

    - If status is provided, queries the gsi_status GSI.
    - Otherwise, scans the full table.
    - Pagination cursors are opaque base64 strings encoding the full
      DynamoDB LastEvaluatedKey, so callers never see internal key values.
    """
    events = _events_table()

    exclusive_start_key: dict[str, Any] | None = None
    if last_pk:
        exclusive_start_key = _decode_cursor(last_pk)

    if status:
        kwargs: dict[str, Any] = {
            "IndexName": "gsi_status",
            "KeyConditionExpression": "#s = :v",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":v": status},
            "Limit": limit,
        }
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        resp = events.query(**kwargs)
    else:
        kwargs2: dict[str, Any] = {"Limit": limit}
        if exclusive_start_key:
            kwargs2["ExclusiveStartKey"] = exclusive_start_key
        resp = events.scan(**kwargs2)

    items = resp.get("Items", [])
    lek = resp.get("LastEvaluatedKey")
    next_token = _encode_cursor(lek) if lek else None
    return {"items": items, "next_token": next_token}
