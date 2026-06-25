"""
Tests for Prometheus metrics in the AtlasFlow API.

These tests verify:
  - GET /metrics returns 200 with valid Prometheus text exposition format.
  - The events_ingested_total counter increments when a new event is created.
  - Deduplicated (idempotent) requests do NOT increment the counter.
  - The api_request_duration_seconds histogram is populated after requests.
"""
from __future__ import annotations

# ── /metrics endpoint ─────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def test_metrics_returns_200(self, api_client):
        resp = api_client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_is_prometheus(self, api_client):
        resp = api_client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_standard_go_metrics(self, api_client):
        """Prometheus client always exposes some process/python metrics."""
        resp = api_client.get("/metrics")
        body = resp.text
        # Our custom metric families should be declared
        assert "atlasflow_events_ingested_total" in body
        assert "atlasflow_api_request_duration_seconds" in body


# ── events_ingested_total counter ─────────────────────────────────────────────

class TestEventsIngestedCounter:
    def test_counter_increments_on_new_event(self, api_client):
        from app.core.metrics import EVENTS_INGESTED

        before = _sample_value(EVENTS_INGESTED, {"event_type": "ping"})

        api_client.post("/v1/events", json={"type": "ping", "payload": {}})

        after = _sample_value(EVENTS_INGESTED, {"event_type": "ping"})
        assert after == before + 1

    def test_counter_does_not_increment_on_duplicate(self, api_client):
        from app.core.metrics import EVENTS_INGESTED

        headers = {"Idempotency-Key": "metrics-idem-001"}
        api_client.post("/v1/events", json={"type": "ping", "payload": {}}, headers=headers)

        before = _sample_value(EVENTS_INGESTED, {"event_type": "ping"})

        # Second call with same key — should reuse, not increment
        api_client.post("/v1/events", json={"type": "ping", "payload": {}}, headers=headers)

        after = _sample_value(EVENTS_INGESTED, {"event_type": "ping"})
        assert after == before  # no change

    def test_counter_uses_event_type_label(self, api_client):
        from app.core.metrics import EVENTS_INGESTED

        before_notify = _sample_value(EVENTS_INGESTED, {"event_type": "notify"})

        api_client.post(
            "/v1/events",
            json={
                "type": "notify",
                "payload": {
                    "channel": "email",
                    "recipient": "a@b.com",
                    "message": "hello",
                },
            },
        )

        after_notify = _sample_value(EVENTS_INGESTED, {"event_type": "notify"})
        assert after_notify == before_notify + 1


# ── request duration histogram ────────────────────────────────────────────────

class TestRequestDurationHistogram:
    def test_histogram_recorded_after_request(self, api_client):
        from app.core.metrics import API_REQUEST_DURATION

        api_client.post("/v1/events", json={"type": "ping", "payload": {}})
        api_client.get("/v1/events")

        # Verify the histogram has at least one observation for POST and GET
        assert _histogram_count(API_REQUEST_DURATION, {"method": "POST"}) >= 1
        assert _histogram_count(API_REQUEST_DURATION, {"method": "GET"}) >= 1


# ── helpers ───────────────────────────────────────────────────────────────────

def _sample_value(metric, labels: dict) -> float:
    """Read the current value of a counter/gauge for the given label set."""
    samples = metric.collect()[0].samples
    for s in samples:
        if s.name.endswith("_total") and s.labels == labels:
            return s.value
    return 0.0


def _histogram_count(metric, partial_labels: dict) -> float:
    """Return the _count sample for histogram samples that match partial labels."""
    samples = metric.collect()[0].samples
    for s in samples:
        if s.name.endswith("_count"):
            if all(s.labels.get(k) == v for k, v in partial_labels.items()):
                return s.value
    return 0.0
