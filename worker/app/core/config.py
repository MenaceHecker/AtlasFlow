"""
Worker configuration loaded from environment variables.

Uses a plain dataclass instead of pydantic.BaseModel to avoid adding
pydantic as a runtime dependency of the worker. All coercion is handled
explicitly by reading env vars with int() where needed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")  # type: ignore[assignment]
    localstack_endpoint: str = os.getenv(  # type: ignore[assignment]
        "LOCALSTACK_ENDPOINT", "http://127.0.0.1:4566"
    )

    project_name: str = os.getenv("TF_VAR_project_name", "atlasflow")  # type: ignore[assignment]
    events_table: str = os.getenv(  # type: ignore[assignment]
        "EVENTS_TABLE",
        f"{os.getenv('TF_VAR_project_name', 'atlasflow')}-events",
    )
    events_queue_name: str = os.getenv(  # type: ignore[assignment]
        "EVENTS_QUEUE_NAME",
        f"{os.getenv('TF_VAR_project_name', 'atlasflow')}-events",
    )

    # S3 payload offload — set PAYLOAD_BUCKET to enable large-payload fetching.
    # The worker reads s3_key from the DynamoDB item and fetches the payload
    # from S3 before dispatching to the handler.
    payload_bucket: str = os.getenv("PAYLOAD_BUCKET", "")  # type: ignore[assignment]
    payload_offload_threshold_bytes: int = int(
        os.getenv("PAYLOAD_OFFLOAD_THRESHOLD_BYTES", str(32 * 1024))  # 32 KB default
    )

    # Worker polling behavior
    poll_wait_seconds: int = int(os.getenv("POLL_WAIT_SECONDS", "10"))
    max_messages: int = int(os.getenv("MAX_MESSAGES", "5"))
    visibility_timeout: int = int(os.getenv("VISIBILITY_TIMEOUT", "30"))


settings = Settings()