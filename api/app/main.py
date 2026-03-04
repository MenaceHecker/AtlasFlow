from fastapi import FastAPI
from app.routes.events import router as events_router

app = FastAPI(title="AtlasFlow API", version="0.1.0")

app.include_router(events_router)


@app.get("/health")
def health():
    return {"ok": True}