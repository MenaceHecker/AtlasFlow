"""
Shared pytest fixtures for AtlasFlow integration tests.

These tests spin up a REAL LocalStack container via testcontainers-python and
exercise the full pipeline without any mocks.

Prerequisites:
  - Docker must be running.
  - Both api/ and worker/ packages must be installed (pip install -e api/ -e worker/).

Fixture hierarchy:
  localstack        (session) — starts the LocalStack container
  localstack_endpoint (session)
  aws_session       (session)
  infra             (session) — creates DDB tables + SQS queues + S3 bucket once
  env               (function) — wires API + worker service layers to LocalStack,
                                 yields {"client": TestClient, "infra": infra}
"""
from __future__ import annotations

import json

import boto3
import pytest
from testcontainers.localstack import LocalStackContainer

from integration.helpers import (
    DLQ_NAME,
    EVENTS_TABLE,
    IDEM_TABLE,
    PAYLOAD_BUCKET,
    QUEUE_NAME,
    REGION,
)

LOCALSTACK_IMAGE = "localstack/localstack:3.2"


# ── LocalStack container (session-scoped) ─────────────────────────────────────

@pytest.fixture(scope="session")
def localstack():
    """Start a LocalStack container for the entire test session."""
    with LocalStackContainer(image=LOCALSTACK_IMAGE) as ls:
        yield ls


@pytest.fixture(scope="session")
def localstack_endpoint(localstack) -> str:
    return localstack.get_url()


@pytest.fixture(scope="session")
def aws_session(localstack_endpoint) -> boto3.Session:
    """Return a boto3 Session pre-configured for LocalStack."""
    return boto3.Session(
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


# ── infrastructure (session-scoped — created once) ────────────────────────────

@pytest.fixture(scope="session")
def infra(aws_session, localstack_endpoint):
    """Create all required AWS resources inside LocalStack."""
    ddb = aws_session.resource("dynamodb", endpoint_url=localstack_endpoint)
    sqs = aws_session.client("sqs", endpoint_url=localstack_endpoint)
    s3 = aws_session.client("s3", endpoint_url=localstack_endpoint)

    # DynamoDB — events table
    events_table = ddb.create_table(
        TableName=EVENTS_TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "gsi_status",
                "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # DynamoDB — idempotency table
    ddb.create_table(
        TableName=IDEM_TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # SQS — DLQ then main queue with redrive
    dlq = sqs.create_queue(QueueName=DLQ_NAME)
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq["QueueUrl"], AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    main_q = sqs.create_queue(
        QueueName=QUEUE_NAME,
        Attributes={
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}
            )
        },
    )

    # S3 — payload bucket
    s3.create_bucket(Bucket=PAYLOAD_BUCKET)

    return {
        "ddb": ddb,
        "sqs": sqs,
        "s3": s3,
        "events_table": events_table,
        "queue_url": main_q["QueueUrl"],
        "dlq_url": dlq["QueueUrl"],
        "payload_bucket": PAYLOAD_BUCKET,
    }


# ── per-test service layer (function-scoped) ──────────────────────────────────

@pytest.fixture(scope="function")
def env(infra, localstack_endpoint, monkeypatch):
    """
    Wire the API and worker service layers to the real LocalStack instance.

    Sets all required env vars and clears lru_caches so clients are
    re-created against the real endpoint for each test.
    """
    monkeypatch.setenv("LOCALSTACK_ENDPOINT", localstack_endpoint)
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("EVENTS_TABLE", EVENTS_TABLE)
    monkeypatch.setenv("IDEMPOTENCY_TABLE", IDEM_TABLE)
    monkeypatch.setenv("EVENTS_QUEUE_NAME", QUEUE_NAME)
    monkeypatch.setenv("PAYLOAD_BUCKET", "")
    monkeypatch.setenv("ADMIN_API_KEY", "inttest-admin-key")

    # ── API service layer ──────────────────────────────────────────────────
    from app.services import aws_clients as api_aws_clients
    from app.services import events_service

    api_aws_clients.ddb_resource.cache_clear()
    api_aws_clients.sqs_client.cache_clear()
    api_aws_clients.s3_client.cache_clear()
    events_service._get_queue_url.cache_clear()

    from app.core import config as api_config

    monkeypatch.setattr(api_config.settings, "localstack_endpoint", localstack_endpoint)
    monkeypatch.setattr(api_config.settings, "events_table", EVENTS_TABLE)
    monkeypatch.setattr(api_config.settings, "idem_table", IDEM_TABLE)
    monkeypatch.setattr(api_config.settings, "events_queue_name", QUEUE_NAME)
    monkeypatch.setattr(api_config.settings, "admin_api_key", "inttest-admin-key")

    # ── Worker service layer ───────────────────────────────────────────────
    from app.services import aws_clients as worker_aws_clients

    worker_aws_clients.ddb_resource.cache_clear()
    worker_aws_clients.sqs_client.cache_clear()
    worker_aws_clients.s3_client.cache_clear()

    from app.core import config as worker_config

    monkeypatch.setattr(worker_config.settings, "localstack_endpoint", localstack_endpoint)
    monkeypatch.setattr(worker_config.settings, "events_table", EVENTS_TABLE)
    monkeypatch.setattr(worker_config.settings, "events_queue_name", QUEUE_NAME)

    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield {
            "client": client,
            "infra": infra,
        }
