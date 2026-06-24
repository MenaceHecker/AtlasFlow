"""
Tests for S3 payload offload in the AtlasFlow API.

These tests verify:
  - Small payloads are stored inline in DynamoDB (no S3).
  - Large payloads above the threshold are offloaded to S3.
  - The public API never exposes s3_key — callers see payload as usual.
  - SQS enqueue failure after S3 upload cleans up both the DDB item and the S3 object.
"""
from __future__ import annotations

import json

import pytest

SMALL_PAYLOAD = {"ping": True}
# 40 KB of data — above the default 32 KB threshold
LARGE_PAYLOAD = {"data": "x" * (40 * 1024)}


# ── helpers ───────────────────────────────────────────────────────────────────

def _enable_offload(monkeypatch, bucket: str, threshold_bytes: int = 1024) -> None:
    """Patch settings so S3 offload is active with the given bucket and threshold."""
    import app.core.config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings, "payload_bucket", bucket)
    monkeypatch.setattr(cfg_mod.settings, "payload_offload_threshold_bytes", threshold_bytes)

    import app.services.events_service as svc_mod
    monkeypatch.setattr(svc_mod.settings, "payload_bucket", bucket)
    monkeypatch.setattr(svc_mod.settings, "payload_offload_threshold_bytes", threshold_bytes)


# ── small payload stays inline ────────────────────────────────────────────────

class TestSmallPayloadInline:
    def test_small_payload_stored_inline(self, api_client, aws_resources, monkeypatch):
        """Payloads below the threshold go to payload_inline, not S3."""
        bucket = aws_resources["payload_bucket"]
        _enable_offload(monkeypatch, bucket, threshold_bytes=32 * 1024)

        resp = api_client.post(
            "/v1/events",
            json={"type": "ping", "payload": SMALL_PAYLOAD},
        )
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]

        assert "payload_inline" in item
        assert item["payload_inline"] == SMALL_PAYLOAD
        assert "s3_key" not in item

    def test_s3_key_not_exposed_in_api_response(self, api_client, aws_resources, monkeypatch):
        """Internal s3_key must never appear in GET /v1/events/{event_id} responses."""
        bucket = aws_resources["payload_bucket"]
        _enable_offload(monkeypatch, bucket, threshold_bytes=100)  # very low threshold

        resp = api_client.post(
            "/v1/events",
            json={"type": "ping", "payload": {"key": "value" * 20}},
        )
        event_id = resp.json()["event_id"]

        detail = api_client.get(f"/v1/events/{event_id}").json()
        assert "s3_key" not in detail


# ── large payload offloads to S3 ──────────────────────────────────────────────

class TestLargePayloadOffload:
    def test_large_payload_stored_in_s3(self, api_client, aws_resources, monkeypatch):
        """Payloads exceeding the threshold are uploaded to S3."""
        bucket = aws_resources["payload_bucket"]
        # Set threshold to 1 byte so even a tiny payload offloads
        _enable_offload(monkeypatch, bucket, threshold_bytes=1)

        payload = {"msg": "hello from s3"}
        resp = api_client.post(
            "/v1/events",
            json={"type": "ping", "payload": payload},
        )
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]

        # DynamoDB item should have s3_key, not payload_inline
        assert "s3_key" in item
        assert "payload_inline" not in item

        # S3 object must exist and contain the original payload
        s3_obj = aws_resources["s3"].get_object(
            Bucket=bucket, Key=item["s3_key"]
        )
        stored = json.loads(s3_obj["Body"].read())
        assert stored == payload

    def test_offload_disabled_when_bucket_not_set(self, api_client, aws_resources, monkeypatch):
        """When PAYLOAD_BUCKET is empty, all payloads are stored inline."""
        import app.services.events_service as svc_mod
        monkeypatch.setattr(svc_mod.settings, "payload_bucket", "")

        resp = api_client.post(
            "/v1/events",
            json={"type": "ping", "payload": LARGE_PAYLOAD},
        )
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]

        item = aws_resources["events_table"].get_item(
            Key={"pk": f"EVENT#{event_id}"}
        )["Item"]

        # Must be inline — bucket not configured
        assert "payload_inline" in item
        assert "s3_key" not in item

    def test_s3_object_cleaned_up_on_enqueue_failure(
        self, aws_resources, monkeypatch
    ):
        """If SQS send_message fails after S3 upload, the S3 object is deleted."""
        from app.services import aws_clients, events_service

        aws_clients.ddb_resource.cache_clear()
        aws_clients.sqs_client.cache_clear()
        aws_clients.s3_client.cache_clear()
        events_service._get_queue_url.cache_clear()

        bucket = aws_resources["payload_bucket"]
        monkeypatch.setattr(events_service.settings, "payload_bucket", bucket)
        monkeypatch.setattr(events_service.settings, "payload_offload_threshold_bytes", 1)

        # Intercept SQS to fail after S3 upload
        def fail_send(**kwargs):
            raise RuntimeError("SQS unavailable")

        monkeypatch.setattr(
            events_service, "_get_queue_url",
            lambda: aws_resources["queue_url"],
        )
        monkeypatch.setattr(events_service, "sqs_client", lambda: aws_resources["sqs"])
        monkeypatch.setattr(aws_resources["sqs"], "send_message", fail_send)

        with pytest.raises(RuntimeError, match="SQS unavailable"):
            events_service.create_event("ping", {"x": 1}, None)

        # DynamoDB must be clean
        items = aws_resources["events_table"].scan().get("Items", [])
        assert items == []

        # S3 must be clean (object deleted on rollback)
        listed = aws_resources["s3"].list_objects_v2(Bucket=bucket)
        assert listed.get("KeyCount", 0) == 0
