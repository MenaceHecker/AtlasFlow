"""AtlasFlow API — FastAPI application entrypoint."""
from __future__ import annotations

# configure_logging() MUST be called before any other import that touches
# the logging module. The E402 noqa comments below acknowledge that the
# remaining imports intentionally come after this call.
from app.core.logging_config import configure_logging

configure_logging()

import logging  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from app.routes.admin import router as admin_router  # noqa: E402
from app.routes.events import router as events_router  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AtlasFlow API",
    version="0.1.0",
    description=(
        "AtlasFlow is an event-driven ingestion API backed by DynamoDB and SQS. "
        "POST an event to ingest it; a background worker picks it up, runs the "
        "appropriate handler, and writes the result back. Use the admin endpoints "
        "to replay failed events from the dead-letter queue.\n\n"
        "All routes are prefixed with `/v1`. Admin routes require an `X-Admin-Key` header."
    ),
    openapi_tags=[
        {"name": "Events", "description": "Ingest and query events."},
        {"name": "Admin", "description": "Operational tools. Require X-Admin-Key header."},
    ],
)

app.include_router(events_router)
app.include_router(admin_router)


@app.get("/health")
def health():
    logger.debug("health check")
    return {"ok": True}


logger.info("AtlasFlow API starting up")