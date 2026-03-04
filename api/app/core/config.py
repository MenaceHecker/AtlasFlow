from pydantic import BaseModel
import os


class Settings(BaseModel):
    project_name: str = os.getenv("PROJECT_NAME", "atlasflow")

    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    localstack_endpoint: str = os.getenv("LOCALSTACK_ENDPOINT", "http://127.0.0.1:4566")

    # Derived names 
    events_table: str = os.getenv("EVENTS_TABLE", f"{os.getenv('TF_VAR_project_name', 'atlasflow')}-events")
    idem_table: str = os.getenv("IDEMPOTENCY_TABLE", f"{os.getenv('TF_VAR_project_name', 'atlasflow')}-idempotency")
    events_queue_name: str = os.getenv("EVENTS_QUEUE_NAME", f"{os.getenv('TF_VAR_project_name', 'atlasflow')}-events")


settings = Settings()