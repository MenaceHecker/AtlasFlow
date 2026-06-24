from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.config import settings


def _cfg() -> Config:
    return Config(region_name=settings.aws_region, retries={"max_attempts": 3, "mode": "standard"})


def _endpoint_url() -> str | None:
    """Return None when the endpoint is unset so moto / real AWS work transparently."""
    url = settings.localstack_endpoint.strip()
    return url if url else None


@lru_cache(maxsize=1)
def ddb_resource():
    return boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=_endpoint_url(),
        config=_cfg(),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@lru_cache(maxsize=1)
def sqs_client():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=_endpoint_url(),
        config=_cfg(),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@lru_cache(maxsize=1)
def s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=_endpoint_url(),
        config=_cfg(),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )