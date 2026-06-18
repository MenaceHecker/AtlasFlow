from app.core.logging_config import configure_logging

configure_logging()  # must run before any other import that touches logging

import logging  # noqa: E402

from fastapi import FastAPI
from app.routes.events import router as events_router
from app.routes.admin import router as admin_router

logger = logging.getLogger(__name__)

app = FastAPI(title="AtlasFlow API", version="0.1.0")

app.include_router(events_router)
app.include_router(admin_router)


@app.get("/health")
def health():
    logger.debug("health check")
    return {"ok": True}


logger.info("AtlasFlow API starting up")