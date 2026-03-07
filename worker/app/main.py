from __future__ import annotations

import time
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import sqs_client
from app.services.processor import process_message


def get_queue_url() -> str:
    sqs = sqs_client()
    return sqs.get_queue_url(QueueName=settings.events_queue_name)["QueueUrl"]


def run_forever() -> None:
    sqs = sqs_client()
    queue_url = get_queue_url()

    print(f"[worker] polling queue={queue_url} endpoint={settings.localstack_endpoint}")

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
            except Exception as e:
                # Leave it un-deleted so SQS retries DLQ will handle maxReceiveCount
                print(f"[worker] error: {e}")


if __name__ == "__main__":
    # small startup delay to let LocalStack settle
    time.sleep(1.0)
    run_forever()