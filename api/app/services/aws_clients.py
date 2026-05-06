from __future__ import annotations

import boto3
from functools import lru_cache
from botocore.config import Config
from app.core.config import settings


def _boto_config() -> Config:
    # LocalStack-friendly: retries low, no IMDS
    return Config(
        region_name=settings.aws_region,
        retries={"max_attempts": 3, "mode": "standard"},
    )


@lru_cache(maxsize=1)
def ddb_resource():
    return boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.localstack_endpoint,
        config=_boto_config(),
        aws_access_key_id="test",      # Consider pulling from env for production
        aws_secret_access_key="test",  # Consider pulling from env for production
    )


@lru_cache(maxsize=1)
def sqs_client():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.localstack_endpoint,
        config=_boto_config(),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )