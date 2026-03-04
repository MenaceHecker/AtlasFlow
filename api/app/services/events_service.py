from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.aws_clients import ddb_resource, sqs_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch_seconds(minutes: int = 60) -> int:
    return int(time.time()) + minutes * 60


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _idem_table():
    return ddb_resource().Table(settings.idem_table)