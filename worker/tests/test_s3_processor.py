"""
Tests for S3 payload resolution in the AtlasFlow worker processor.

These tests verify:
  - Events with payload_inline are dispatched correctly (normal path).
  - Events with s3_key fetch their payload from S3 before dispatch.
  - If PAYLOAD_BUCKET is unconfigured, s3_key events fall back to empty payload.
"""
from __future__ import annotations

import json
import uuid

# ── _resolve_payload ──────────────────────────────────────────────────────────

class TestResolvePayload:
    def test_inline_payload_returned_directly(self, aws_resources):
        from app.services.processor import _resolve_payload

        item = {"payload_inline": {"key": "value"}}
        assert _resolve_payload(item) == {"key": "value"}

    def test_empty_item_returns_empty_dict(self, aws_resources):
        from app.services.processor import _resolve_payload

        assert _resolve_payload({}) == {}

    def test_s3_key_fetches_from_s3(self, aws_resources, monkeypatch):
        """When s3_key is present, payload is fetched from S3."""
        from app.services import aws_clients, processor

        bucket = aws_resources["payload_bucket"]
        s3_key = "payloads/test-event-123.json"
        payload = {"from_s3": True, "value": 42}

        aws_resources["s3"].put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(payload).encode(),
        )

        monkeypatch.setattr(processor.settings, "payload_bucket", bucket)
        aws_clients.s3_client.cache_clear()

        item = {"s3_key": s3_key}
        result = processor._resolve_payload(item)
        assert result == payload

    def test_s3_key_without_bucket_config_returns_empty(self, aws_resources, monkeypatch):
        """If PAYLOAD_BUCKET is not set, s3_key events get an empty payload."""
        from app.services import processor

        monkeypatch.setattr(processor.settings, "payload_bucket", "")

        item = {"s3_key": "payloads/some-event.json"}
        result = processor._resolve_payload(item)
        assert result == {}


# ── process_message with S3 offload ──────────────────────────────────────────

class TestProcessMessageWithS3:
    def test_s3_offloaded_event_dispatched_correctly(self, aws_resources, monkeypatch):
        """Full flow: event with s3_key is fetched from S3 and dispatched to PingHandler."""
        from app.services import aws_clients, processor

        bucket = aws_resources["payload_bucket"]
        event_id = str(uuid.uuid4())

        # Seed a ping event that has its payload in S3
        s3_key = f"payloads/{event_id}.json"
        payload = {"ping_from": "s3"}
        aws_resources["s3"].put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(payload).encode(),
        )

        # Write DDB item with s3_key (no payload_inline)
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        aws_resources["events_table"].put_item(Item={
            "pk": f"EVENT#{event_id}",
            "event_id": event_id,
            "type": "ping",
            "status": "CREATED",
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
            "s3_key": s3_key,
        })

        monkeypatch.setattr(processor.settings, "payload_bucket", bucket)
        aws_clients.s3_client.cache_clear()

        processor.process_message(json.dumps({"event_id": event_id}))

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]
        assert item["status"] == "COMPLETED"
        # PingHandler echoes the payload
        assert item["result"]["echo"] == payload
