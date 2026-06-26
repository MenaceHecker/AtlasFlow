"""
Shared helper utilities for integration tests.
These are plain functions, not fixtures — they can be imported freely.
"""
from __future__ import annotations

import json
import time

# Constants — kept here so test files can import them without going through conftest
REGION = "us-east-1"
PROJECT = "atlasflow-inttest"
EVENTS_TABLE = f"{PROJECT}-events"
IDEM_TABLE = f"{PROJECT}-idempotency"
QUEUE_NAME = f"{PROJECT}-events"
DLQ_NAME = f"{PROJECT}-dlq"
PAYLOAD_BUCKET = f"{PROJECT}-payloads"


def process_one(infra: dict, event_id: str) -> None:
    """
    Simulate the worker processing one event by calling process_message()
    directly against the real LocalStack DynamoDB and SQS.

    Both the API (api/app/) and the worker (worker/app/) share the `app`
    package namespace. In the integration test process the API package is
    loaded first, so we must temporarily put the worker directory first on
    sys.path and clear cached `app.*` modules before importing the worker's
    process_message — then restore everything so subsequent API calls work.
    """
    import pathlib
    import sys

    worker_dir = str(pathlib.Path(__file__).parents[3] / "worker")

    # Snapshot current state
    saved_path = sys.path[:]
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith("app")}

    # Put worker first so its `app` package wins
    sys.path = [worker_dir] + [p for p in sys.path if p != worker_dir]
    # Evict any api `app.*` modules from the cache
    for key in list(sys.modules.keys()):
        if key.startswith("app"):
            del sys.modules[key]

    try:
        from app.services.processor import process_message  # noqa: PLC0415

        process_message(json.dumps({"event_id": event_id}))
    finally:
        # Restore path and re-register api app modules
        sys.path = saved_path
        for key in list(sys.modules.keys()):
            if key.startswith("app"):
                del sys.modules[key]
        sys.modules.update(saved_modules)


def wait_for_status(
    infra: dict, event_id: str, expected_status: str, timeout: float = 10.0
) -> dict:
    """Poll DynamoDB until the event reaches the expected status or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = infra["events_table"].get_item(Key={"pk": f"EVENT#{event_id}"})
        item = resp.get("Item")
        if item and item.get("status") == expected_status:
            return item
        time.sleep(0.2)
    raise TimeoutError(
        f"Event {event_id} did not reach status={expected_status!r} within {timeout}s"
    )


def drain_queue(infra: dict) -> None:
    """Receive and delete all existing queue messages (test isolation)."""
    sqs = infra["sqs"]
    while True:
        resp = sqs.receive_message(
            QueueUrl=infra["queue_url"],
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            break
        for m in msgs:
            sqs.delete_message(QueueUrl=infra["queue_url"], ReceiptHandle=m["ReceiptHandle"])


def receive_all(infra: dict) -> list:
    """Return all messages currently on the queue without deleting them."""
    sqs = infra["sqs"]
    all_msgs = []
    for _ in range(5):
        resp = sqs.receive_message(
            QueueUrl=infra["queue_url"],
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            break
        all_msgs.extend(msgs)
    return all_msgs
