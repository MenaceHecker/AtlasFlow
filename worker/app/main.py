from __future__ import annotations

from app.core.logging_config import configure_logging

configure_logging()  # must be first — sets up JSON formatter before any other import

import logging  # noqa: E402
import time  # noqa: E402

from botocore.exceptions import ClientError  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.aws_clients import sqs_client  # noqa: E402
from app.services.processor import process_message  # noqa: E402

logger = logging.getLogger(__name__)


def get_queue_url() -> str:
    sqs = sqs_client()
    return sqs.get_queue_url(QueueName=settings.events_queue_name)["QueueUrl"]


def run_forever() -> None:
    sqs = sqs_client()
    queue_url = get_queue_url()

    logger.info(
        "Worker started polling",
        extra={"queue_url": queue_url, "endpoint": settings.localstack_endpoint},
    )

    while True:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=settings.max_messages,
            WaitTimeSeconds=settings.poll_wait_seconds,
            VisibilityTimeout=settings.visibility_timeout,
        )

        msgs = resp.get("Messages", [])
        if not msgs:
            continue

        for m in msgs:
            receipt = m["ReceiptHandle"]
            body = m["Body"]

            try:
                process_message(body)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
            except Exception:
                # Leave un-deleted so SQS retries; DLQ handles maxReceiveCount.
                logger.exception(
                    "Failed to process message; leaving on queue for retry",
                    extra={"receipt_handle": receipt[:16] + "…"},
                )


if __name__ == "__main__":
    # Small startup delay to let LocalStack settle.
    time.sleep(1.0)
    run_forever()