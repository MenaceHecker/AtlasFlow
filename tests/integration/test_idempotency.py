"""
Integration tests: idempotency across the full API + DynamoDB pipeline.

Verifies that submitting the same event twice with the same idempotency key
results in exactly one event record in DynamoDB and one SQS message.
"""
from __future__ import annotations

import uuid

from integration.helpers import process_one, wait_for_status


class TestIdempotency:
    def test_same_key_returns_same_event_id(self, env):
        """Two POST calls with the same idempotency key return the same event_id."""
        client = env["client"]
        key = f"idem-{uuid.uuid4()}"
        headers = {"Idempotency-Key": key}
        payload = {"type": "ping", "payload": {}}

        r1 = client.post("/v1/events", json=payload, headers=headers)
        r2 = client.post("/v1/events", json=payload, headers=headers)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["event_id"] == r2.json()["event_id"]

    def test_duplicate_request_creates_single_ddb_record(self, env):
        """Only one DynamoDB record exists after two idempotent submissions."""
        client = env["client"]
        infra = env["infra"]
        key = f"idem-{uuid.uuid4()}"
        headers = {"Idempotency-Key": key}
        payload = {"type": "ping", "payload": {}}

        r1 = client.post("/v1/events", json=payload, headers=headers)
        client.post("/v1/events", json=payload, headers=headers)

        event_id = r1.json()["event_id"]

        # Exactly one DDB record for this event
        item = infra["events_table"].get_item(Key={"pk": f"EVENT#{event_id}"})
        assert item.get("Item") is not None

        # Scan to verify only one record with this event_id exists
        result = infra["events_table"].scan(
            FilterExpression="event_id = :eid",
            ExpressionAttributeValues={":eid": event_id},
        )
        assert len(result["Items"]) == 1

    def test_duplicate_does_not_enqueue_twice(self, env):
        """A duplicate idempotent request must not produce a second SQS message."""
        client = env["client"]
        infra = env["infra"]
        key = f"idem-{uuid.uuid4()}"
        headers = {"Idempotency-Key": key}
        payload = {"type": "ping", "payload": {}}

        # Drain any pre-existing messages first
        _drain(infra)

        client.post("/v1/events", json=payload, headers=headers)
        client.post("/v1/events", json=payload, headers=headers)

        # Only one message should be on the queue
        messages = _receive_all(infra)
        assert len(messages) == 1

    def test_different_keys_create_different_events(self, env):
        """Two requests with different idempotency keys create two distinct events."""
        client = env["client"]
        payload = {"type": "ping", "payload": {}}

        r1 = client.post(
            "/v1/events", json=payload, headers={"Idempotency-Key": f"key-{uuid.uuid4()}"}
        )
        r2 = client.post(
            "/v1/events", json=payload, headers={"Idempotency-Key": f"key-{uuid.uuid4()}"}
        )

        assert r1.json()["event_id"] != r2.json()["event_id"]

    def test_idempotent_event_completes_on_first_process(self, env):
        """The single SQS message for an idempotent pair processes to COMPLETED."""
        client = env["client"]
        infra = env["infra"]
        key = f"idem-{uuid.uuid4()}"
        headers = {"Idempotency-Key": key}
        payload = {"type": "ping", "payload": {"x": 1}}

        r1 = client.post("/v1/events", json=payload, headers=headers)
        client.post("/v1/events", json=payload, headers=headers)  # duplicate

        event_id = r1.json()["event_id"]
        process_one(infra, event_id)

        item = wait_for_status(infra, event_id, "COMPLETED")
        assert item["result"]["status"] == "pong"


# ── helpers ───────────────────────────────────────────────────────────────────

def _drain(infra) -> None:
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


def _receive_all(infra) -> list:
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
