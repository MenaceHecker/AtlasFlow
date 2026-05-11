"""
Tests for /v1/admin routes — auth gating + DLQ replay logic.
"""
from __future__ import annotations

import json
import pytest

VALID_KEY = "test-admin-key-abc123"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client_with_key(aws_resources, monkeypatch):
    """TestClient wired with a known ADMIN_API_KEY."""
    monkeypatch.setenv("ADMIN_API_KEY", VALID_KEY)

    from app.services import aws_clients
    aws_clients.ddb_resource.cache_clear()
    aws_clients.sqs_client.cache_clear()

    from app.services import events_service
    events_service._get_queue_url.cache_clear()

    # Reload settings so it picks up the monkeypatched env var
    import importlib, app.core.config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import dependencies as dep_mod
    importlib.reload(dep_mod)
    import app.routes.admin as admin_mod
    importlib.reload(admin_mod)

    import app.main as main_mod
    importlib.reload(main_mod)

    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as client:
        yield client


@pytest.fixture
def api_client_no_key(aws_resources, monkeypatch):
    """TestClient with ADMIN_API_KEY unset (disabled)."""
    monkeypatch.setenv("ADMIN_API_KEY", "")

    from app.services import aws_clients
    aws_clients.ddb_resource.cache_clear()
    aws_clients.sqs_client.cache_clear()

    from app.services import events_service
    events_service._get_queue_url.cache_clear()

    import importlib, app.core.config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import dependencies as dep_mod
    importlib.reload(dep_mod)
    import app.routes.admin as admin_mod
    importlib.reload(admin_mod)

    import app.main as main_mod
    importlib.reload(main_mod)

    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as client:
        yield client


# ── auth gating ───────────────────────────────────────────────────────────────

class TestAdminAuth:
    def test_missing_key_returns_401(self, api_client_with_key):
        resp = api_client_with_key.post("/v1/admin/dlq/replay")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, api_client_with_key):
        resp = api_client_with_key.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_correct_key_is_accepted(self, api_client_with_key):
        resp = api_client_with_key.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": VALID_KEY},
        )
        # 200 with empty replay (no DLQ messages) is fine
        assert resp.status_code == 200

    def test_admin_disabled_when_key_not_configured(self, api_client_no_key):
        resp = api_client_no_key.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": "any-key"},
        )
        assert resp.status_code == 503


# ── DLQ replay logic ──────────────────────────────────────────────────────────

class TestDlqReplay:
    def _seed_dlq(self, aws_resources, n: int = 2):
        """Push n messages directly onto the DLQ."""
        sqs = aws_resources["sqs"]
        dlq_url = aws_resources["dlq_url"]
        for i in range(n):
            sqs.send_message(
                QueueUrl=dlq_url,
                MessageBody=json.dumps({"event_id": f"evt-{i}"}),
            )

    def test_replay_moves_messages_to_main_queue(self, api_client_with_key, aws_resources):
        self._seed_dlq(aws_resources, n=2)

        resp = api_client_with_key.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": VALID_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["replayed"] == 2

        # Verify messages landed on the main queue
        sqs = aws_resources["sqs"]
        received = sqs.receive_message(
            QueueUrl=aws_resources["queue_url"],
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        ).get("Messages", [])
        assert len(received) == 2

    def test_replay_empty_dlq_returns_zero(self, api_client_with_key, aws_resources):
        resp = api_client_with_key.post(
            "/v1/admin/dlq/replay",
            headers={"X-Admin-Key": VALID_KEY},
        )
        assert resp.status_code == 200
        assert resp.json()["replayed"] == 0

    def test_replay_respects_max_messages_param(self, api_client_with_key, aws_resources):
        self._seed_dlq(aws_resources, n=5)

        resp = api_client_with_key.post(
            "/v1/admin/dlq/replay?max_messages=2",
            headers={"X-Admin-Key": VALID_KEY},
        )
        assert resp.status_code == 200
        assert resp.json()["replayed"] <= 2
