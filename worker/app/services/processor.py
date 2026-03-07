

from api.app.services.aws_clients import ddb_resource
from app.core.config import settings
import datetime


def _now_iso() -> str:
    return datetime.now(datetime.timezone.utc).isoformat()


def _events_table():
    return ddb_resource().Table(settings.events_table)


def _pk(event_id: str) -> str:
    return f"EVENT#{event_id}"

def transition_to_processing(event_id: str) -> bool:
    """
    Conditional update prevents double-processing under at-least-once delivery.
    Returns True if we successfully claimed it, False if it was already finished.
    """
    table = _events_table()
    try:
        table.update_item(
            Key={"pk": _pk(event_id)},
            UpdateExpression="SET #s = :p, updatedAt = :u ADD attempts :one",
            ConditionExpression="#s = :created",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":p": "PROCESSING",
                ":u": _now_iso(),
                ":created": "CREATED",
                ":one": 1,
            },
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def mark_completed(event_id: str, result: Dict[str, Any]) -> None:
    table = _events_table()
    table.update_item(
        Key={"pk": _pk(event_id)},
        UpdateExpression="SET #s = :c, updatedAt = :u, result = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":c": "COMPLETED", ":u": _now_iso(), ":r": result},
    )