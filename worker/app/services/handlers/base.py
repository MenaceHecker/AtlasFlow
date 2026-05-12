"""
Base handler interface for AtlasFlow event processing.

Every handler must accept an event_id and a payload dict, perform its work,
and return a result dict that will be written back to DynamoDB.

Handlers should raise an exception if they cannot process the event — the
worker will propagate that exception so SQS retries (and eventually the DLQ)
take over.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseHandler(ABC):
    """Abstract base for all event-type handlers."""

    @abstractmethod
    def handle(self, event_id: str, payload: dict) -> dict:
        """
        Process the event and return a result dict.

        Args:
            event_id: The unique event identifier.
            payload:  The event payload as stored in DynamoDB.

        Returns:
            A dict that will be written to the event record as `result`.

        Raises:
            Exception: If processing fails. The exception propagates to the
                       worker loop so SQS can retry the message.
        """
