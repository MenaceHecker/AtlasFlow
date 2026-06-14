from __future__ import annotations

import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from typing import Dict, Any

from botocore.exceptions import ClientError

from app.core.dependencies import require_admin_key
from app.core.config import settings
from app.services.aws_clients import ddb_resource, sqs_client

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_key)],  # applied to every route in this router
)

DLQ_NAME = f"{settings.project_name}-dlq"
MAIN_QUEUE_NAME = f"{settings.project_name}-events"


def _queue_url(queue_name: str) -> str:
    sqs = sqs_client()
    return sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]


def _set_replay_status(event_id: str, from_status: str, to_status: str) -> bool:
    table = ddb_resource().Table(settings.events_table)
    try:
        table.update_item(
            Key={"pk": f"EVENT#{event_id}"},
            UpdateExpression="SET #s = :to, updatedAt = :updated",
            ConditionExpression="#s = :from",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":from": from_status,
                ":to": to_status,
                ":updated": datetime.now(timezone.utc).isoformat(),
            },
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


@router.post("/dlq/replay")
def replay_dlq(max_messages: int = 10) -> Dict[str, Any]:
    sqs = sqs_client()

    dlq_url = _queue_url(DLQ_NAME)
    main_url = _queue_url(MAIN_QUEUE_NAME)

    resp = sqs.receive_message(
        QueueUrl=dlq_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=1,
        VisibilityTimeout=30,
        MessageAttributeNames=["All"],
    )

    messages = resp.get("Messages", [])
    replayed = 0
    skipped = 0

    for msg in messages:
        body = msg["Body"]
        receipt_handle = msg["ReceiptHandle"]
        message_attributes = msg.get("MessageAttributes", {})

        try:
            event_id = json.loads(body)["event_id"]
        except (json.JSONDecodeError, KeyError, TypeError):
            skipped += 1
            continue

        if not _set_replay_status(event_id, "FAILED", "CREATED"):
            skipped += 1
            continue

        try:
            sqs.send_message(
                QueueUrl=main_url,
                MessageBody=body,
                MessageAttributes=message_attributes,
            )
        except Exception:
            _set_replay_status(event_id, "CREATED", "FAILED")
            raise

        sqs.delete_message(
            QueueUrl=dlq_url,
            ReceiptHandle=receipt_handle,
        )

        replayed += 1

    return {
        "replayed": replayed,
        "skipped": skipped,
        "source_queue": DLQ_NAME,
        "destination_queue": MAIN_QUEUE_NAME,
    }
