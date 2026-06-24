import os

from pydantic import BaseModel


class Settings(BaseModel):
    project_name: str = os.getenv("PROJECT_NAME", "atlasflow")

    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    localstack_endpoint: str = os.getenv("LOCALSTACK_ENDPOINT", "http://127.0.0.1:4566")

    # Derived names — fall back to TF_VAR_project_name so names stay
    # consistent with the Terraform-provisioned resources.
    _project = os.getenv("TF_VAR_project_name", "atlasflow")
    events_table: str = os.getenv("EVENTS_TABLE", f"{_project}-events")
    idem_table: str = os.getenv("IDEMPOTENCY_TABLE", f"{_project}-idempotency")
    events_queue_name: str = os.getenv("EVENTS_QUEUE_NAME", f"{_project}-events")

    # S3 payload offload — set PAYLOAD_BUCKET to enable large-payload storage.
    # Payloads exceeding PAYLOAD_OFFLOAD_THRESHOLD_BYTES are uploaded to S3
    # and only the S3 key is stored in DynamoDB, keeping items well under
    # DynamoDB's 400 KB item limit.
    payload_bucket: str = os.getenv("PAYLOAD_BUCKET", "")
    payload_offload_threshold_bytes: int = int(
        os.getenv("PAYLOAD_OFFLOAD_THRESHOLD_BYTES", str(32 * 1024))  # 32 KB default
    )

    # Admin auth — set ADMIN_API_KEY to enable the /v1/admin endpoints.
    # Leaving it empty disables them (returns 503).
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "")


settings = Settings()