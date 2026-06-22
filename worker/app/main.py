from __future__ import annotations

from app.core.logging_config import configure_logging

configure_logging()  # must be first — sets up JSON formatter before any other import

import logging  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.aws_clients import sqs_client  # noqa: E402
from app.services.processor import process_message  # noqa: E402

logger = logging.getLogger(__name__)

# Set by the signal handler. The poll loop checks this flag after each batch
# so it can exit cleanly without interrupting a message mid-processing.
_shutdown = threading.Event()


def _handle_shutdown(signum: int, _frame: object) -> None:
    sig_name = signal.Signals(signum).name
    logger.info(
        "Shutdown signal received; draining current batch before exit",
        extra={"signal": sig_name},
    )
    _shutdown.set()


def get_queue_url() -> str:
    sqs = sqs_client()
    return sqs.get_queue_url(QueueName=settings.events_queue_name)["QueueUrl"]


def run_forever() -> None:
    # Register handlers for the two signals container orchestrators send.
    # SIGTERM is sent by Docker / ECS / Kubernetes before killing the process.
    # SIGINT is Ctrl-C from a developer's terminal.
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    sqs = sqs_client()
    queue_url = get_queue_url()

    logger.info(
        "Worker started polling",
        extra={"queue_url": queue_url, "endpoint": settings.localstack_endpoint},
    )

    while not _shutdown.is_set():
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

    logger.info("Shutdown complete — worker exiting cleanly")


if __name__ == "__main__":
    # Small startup delay to let LocalStack settle.
    time.sleep(1.0)
    run_forever()