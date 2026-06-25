"""AtlasFlow API — FastAPI application entrypoint."""
from __future__ import annotations

# configure_logging() MUST be called before any other import that touches
# the logging module. The E402 noqa comments below acknowledge that the
# remaining imports intentionally come after this call.
from app.core.logging_config import configure_logging

configure_logging()

import logging  # noqa: E402
import time  # noqa: E402

from fastapi import FastAPI, Request, Response  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from app.core.metrics import API_REQUEST_DURATION, metrics_app  # noqa: E402
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
        "All routes are prefixed with `/v1`. Admin routes require an `X-Admin-Key` header.\n\n"
        "Prometheus metrics are available at `/metrics`."
    ),
    openapi_tags=[
        {"name": "Events", "description": "Ingest and query events."},
        {"name": "Admin", "description": "Operational tools. Require X-Admin-Key header."},
    ],
)


class _MetricsMiddleware(BaseHTTPMiddleware):
    """Record per-request duration in the API_REQUEST_DURATION histogram."""

    async def dispatch(self, request: Request, call_next) -> Response:
        t0 = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - t0

        # Collapse path parameters to avoid high cardinality.
        # e.g. /v1/events/abc-123 -> /v1/events/{event_id}
        path = request.url.path
        for route in request.app.routes:
            if hasattr(route, "path") and hasattr(route, "path_regex"):
                if route.path_regex.match(path):
                    path = route.path
                    break

        API_REQUEST_DURATION.labels(
            method=request.method,
            path=path,
            status_code=str(response.status_code),
        ).observe(duration)
        return response


app.add_middleware(_MetricsMiddleware)
app.include_router(events_router)
app.include_router(admin_router)

# Mount the Prometheus metrics endpoint as a sub-application.
# Requests to /metrics are handled by prometheus_client directly,
# bypassing FastAPI routing (so it won't appear in the OpenAPI docs).
app.mount("/metrics", metrics_app)


@app.get("/health")
def health():
    logger.debug("health check")
    return {"ok": True}


logger.info("AtlasFlow API starting up")