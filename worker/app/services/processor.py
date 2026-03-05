

from api.app.services.aws_clients import ddb_resource
from app.core.config import settings
import datetime


def _now_iso() -> str:
    return datetime.now(datetime.timezone.utc).isoformat()


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _pk(event_id: str) -> str:
    return f"EVENT#{event_id}"
