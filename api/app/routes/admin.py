from __future__ import annotations

from fastapi import APIRouter
from typing import Dict, Any

from app.services.aws_clients import sqs_client

router = APIRouter(prefix="/v1/admin", tags=["admin"])

MAIN_QUEUE_NAME = "atlasflow-events"
DLQ_NAME = "atlasflow-dlq"


def _queue_url(queue_name: str) -> str:
    sqs = sqs_client()
    return sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]


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

    for msg in messages:
        body = msg["Body"]
        receipt_handle = msg["ReceiptHandle"]
        message_attributes = msg.get("MessageAttributes", {})

        sqs.send_message(
            QueueUrl=main_url,
            MessageBody=body,
            MessageAttributes=message_attributes,
        )

        sqs.delete_message(
            QueueUrl=dlq_url,
            ReceiptHandle=receipt_handle,
        )

        replayed += 1

    return {
        "replayed": replayed,
        "source_queue": DLQ_NAME,
        "destination_queue": MAIN_QUEUE_NAME,
    }