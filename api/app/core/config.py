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

    # Admin auth — set ADMIN_API_KEY to enable the /v1/admin endpoints.
    # Leaving it empty disables them (returns 503).
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "")


settings = Settings()