from __future__ import annotations

import json
from datetime import UTC, datetime

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.dependencies import require_admin_key
from app.models.schemas import DlqReplayResponse
from app.services.aws_clients import ddb_resource, sqs_client

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_key)],  # applied to every route in this router
)

def _dlq_name() -> str:
    return f"{settings.project_name}-dlq"


def _main_queue_name() -> str:
    return f"{settings.project_name}-events"


def _queue_url(queue_name: str) -> str:
    sqs = sqs_client()
    return sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]


def _set_replay_status(event_id: str, from_status: str, to_status: str) -> bool:
    table = ddb_resource().Table(settings.events_table)
    try:
        table.update_item(
            Key={"pk": f"EVENT#{event_id}"},
            UpdateExpression="SET #s = :to, updated_at = :updated",
            ConditionExpression="#s = :from",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":from": from_status,
                ":to": to_status,
                ":updated": datetime.now(UTC).isoformat(),
            },
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


@router.post(
    "/dlq/replay",
    response_model=DlqReplayResponse,
    summary="Replay dead-letter queue messages",
    description=(
        "Reads up to `max_messages` messages from the DLQ and moves them back "
        "to the main event queue for reprocessing. Each event's status is reset "
        "from `FAILED` to `CREATED` atomically before re-enqueueing, so events "
        "already being processed are skipped safely.\n\n"
        "Requires the `X-Admin-Key` header."
    ),
    responses={
        401: {"description": "Missing or invalid X-Admin-Key header"},
        503: {"description": "Admin endpoints are disabled (ADMIN_API_KEY not set)"},
    },
)
def replay_dlq(max_messages: int = 10) -> DlqReplayResponse:
    sqs = sqs_client()

    dlq_url = _queue_url(_dlq_name())
    main_url = _queue_url(_main_queue_name())

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

    return DlqReplayResponse(
        replayed=replayed,
        skipped=skipped,
        source_queue=_dlq_name(),
        destination_queue=_main_queue_name(),
    )
