import os
from pydantic import BaseModel


class Settings(BaseModel):
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    localstack_endpoint: str = os.getenv("LOCALSTACK_ENDPOINT", "http://127.0.0.1:4566")

    project_name: str = os.getenv("TF_VAR_project_name", "atlasflow")
    events_table: str = os.getenv("EVENTS_TABLE", f"{project_name}-events")
    events_queue_name: str = os.getenv("EVENTS_QUEUE_NAME", f"{project_name}-events")

    # Worker behavior
    poll_wait_seconds: int = int(os.getenv("POLL_WAIT_SECONDS", "10"))
    max_messages: int = int(os.getenv("MAX_MESSAGES", "5"))
    visibility_timeout: int = int(os.getenv("VISIBILITY_TIMEOUT", "30"))


settings = Settings()