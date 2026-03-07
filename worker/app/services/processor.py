from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import ddb_resource


def _now_iso() -> str:
    return datetime.now(datetime.timezone.utc).isoformat()


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _pk(event_id: str) -> str:
    return f"EVENT#{event_id}"

def transition_to_processing(event_id: str) -> bool:
    """
    Conditional update prevents double-processing under at-least-once delivery.
    Returns True if we successfully claimed it, False if it was already finished.
    """
    table = _events_table()
    try:
        table.update_item(
            Key={"pk": _pk(event_id)},
            UpdateExpression="SET #s = :p, updatedAt = :u ADD attempts :one",
            ConditionExpression="#s = :created",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":p": "PROCESSING",
                ":u": _now_iso(),
                ":created": "CREATED",
                ":one": 1,
            },
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def mark_completed(event_id: str, result: Dict[str, Any]) -> None:
    table = _events_table()
    table.update_item(
        Key={"pk": _pk(event_id)},
        UpdateExpression="SET #s = :c, updatedAt = :u, result = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":c": "COMPLETED", ":u": _now_iso(), ":r": result},
    )

def mark_failed(event_id: str, err: str) -> None:
    table = _events_table()
    table.update_item(
        Key={"pk": _pk(event_id)},
        UpdateExpression="SET #s = :f, updatedAt = :u, error = :e",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":f": "FAILED", ":u": _now_iso(), ":e": err},
    )


def process_message(body: str) -> None:
    payload = json.loads(body)
    event_id = payload["event_id"]

    claimed = transition_to_processing(event_id)
    if not claimed:
        # Another worker already claimed it 
        return

    # Simulated work
    time.sleep(0.2)
    if random.random() < 0.02:
        raise RuntimeError("simulated processing error")

    result = {"summary": "processed", "event_id": event_id}
    mark_completed(event_id, result)
