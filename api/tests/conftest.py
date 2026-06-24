"""
Shared pytest fixtures for AtlasFlow API tests.

All AWS resources are mocked with moto — no LocalStack required.
"""
from __future__ import annotations

import json
import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

# ── point app at fake AWS before importing anything that touches boto3 ──────
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("LOCALSTACK_ENDPOINT", "")          # moto ignores endpoint_url
os.environ.setdefault("PROJECT_NAME", "atlasflow")
os.environ.setdefault("EVENTS_TABLE", "atlasflow-events")
os.environ.setdefault("IDEMPOTENCY_TABLE", "atlasflow-idempotency")
os.environ.setdefault("EVENTS_QUEUE_NAME", "atlasflow-events")


REGION = "us-east-1"
EVENTS_TABLE = "atlasflow-events"
IDEM_TABLE = "atlasflow-idempotency"
QUEUE_NAME = "atlasflow-events"
DLQ_NAME = "atlasflow-dlq"
PAYLOAD_BUCKET = "atlasflow-payloads-test"


@pytest.fixture(scope="function")
def aws_env(monkeypatch):
    """Override boto3 clients to use moto's in-process mock."""
    monkeypatch.setenv("LOCALSTACK_ENDPOINT", "")


@pytest.fixture(scope="function")
def aws_resources(aws_env):
    """
    Spin up mocked DynamoDB tables + SQS queues.
    Yields a dict with boto3 resource/client handles.
    """
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        sqs = boto3.client("sqs", region_name=REGION)
        s3 = boto3.client("s3", region_name=REGION)

        # S3 payload bucket
        s3.create_bucket(Bucket=PAYLOAD_BUCKET)

        # events table (pk = hash key, gsi on status)
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

        # idempotency table
        idem_table = ddb.create_table(
            TableName=IDEM_TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        # SQS queues
        dlq = sqs.create_queue(QueueName=DLQ_NAME)
        dlq_arn = sqs.get_queue_attributes(
            QueueUrl=dlq["QueueUrl"], AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]

        main_q = sqs.create_queue(
            QueueName=QUEUE_NAME,
            Attributes={
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "5"}
                )
            },
        )

        yield {
            "ddb": ddb,
            "sqs": sqs,
            "s3": s3,
            "events_table": events_table,
            "idem_table": idem_table,
            "queue_url": main_q["QueueUrl"],
            "dlq_url": dlq["QueueUrl"],
            "payload_bucket": PAYLOAD_BUCKET,
        }


@pytest.fixture(scope="function")
def api_client(aws_resources):
    """
    FastAPI TestClient wired up after moto has patched boto3.
    We clear lru_caches so the service layer picks up the mocked clients.
    """
    from app.services import aws_clients
    aws_clients.ddb_resource.cache_clear()
    aws_clients.sqs_client.cache_clear()
    aws_clients.s3_client.cache_clear()

    from app.services import events_service
    events_service._get_queue_url.cache_clear()

    from app.main import app
    with TestClient(app) as client:
        yield client
