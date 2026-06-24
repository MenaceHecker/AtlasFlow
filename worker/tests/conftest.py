"""
Shared pytest fixtures for AtlasFlow worker tests.
All AWS resources are mocked with moto.
"""
from __future__ import annotations

import os
from datetime import UTC

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("LOCALSTACK_ENDPOINT", "")
os.environ.setdefault("PROJECT_NAME", "atlasflow")
os.environ.setdefault("EVENTS_TABLE", "atlasflow-events")
os.environ.setdefault("EVENTS_QUEUE_NAME", "atlasflow-events")

REGION = "us-east-1"
EVENTS_TABLE = "atlasflow-events"
QUEUE_NAME = "atlasflow-events"
PAYLOAD_BUCKET = "atlasflow-payloads-test"


@pytest.fixture(scope="function")
def aws_resources():
    """Mocked DynamoDB events table + SQS queue + S3 payload bucket."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        sqs = boto3.client("sqs", region_name=REGION)
        s3 = boto3.client("s3", region_name=REGION)

        # S3 payload bucket
        s3.create_bucket(Bucket=PAYLOAD_BUCKET)

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

        queue = sqs.create_queue(QueueName=QUEUE_NAME)

        # clear lru_cache so the processor picks up the mocked clients
        from app.services import aws_clients
        aws_clients.ddb_resource.cache_clear()
        aws_clients.s3_client.cache_clear()

        yield {
            "ddb": ddb,
            "sqs": sqs,
            "s3": s3,
            "events_table": events_table,
            "queue_url": queue["QueueUrl"],
            "payload_bucket": PAYLOAD_BUCKET,
        }


def _seed_event(table, event_id: str, status: str = "CREATED") -> dict:
    """Helper: insert a bare event record directly into DDB."""
    from datetime import datetime
    now = datetime.now(UTC).isoformat()
    item = {
        "pk": f"EVENT#{event_id}",
        "event_id": event_id,
        "type": "test.event",
        "status": status,
        "created_at": now,
        "updated_at": now,
        "attempts": 0,
        "payload_inline": {},
    }
    table.put_item(Item=item)
    return item
