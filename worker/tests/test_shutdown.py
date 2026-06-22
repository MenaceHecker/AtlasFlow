"""
Tests for graceful shutdown behaviour in worker/app/main.py.

We test the _shutdown flag and run_forever loop directly, using monkeypatching
to simulate a SIGTERM arriving mid-poll without actually sending OS signals.
"""
from __future__ import annotations

import json


class TestGracefulShutdown:
    def test_shutdown_flag_stops_poll_loop(self, aws_resources, monkeypatch):
        """run_forever exits cleanly when _shutdown is set before the loop."""
        import app.main as worker_main

        # Reset the shutdown flag in case a previous test left it set.
        worker_main._shutdown.clear()

        monkeypatch.setattr(
            worker_main, "get_queue_url", lambda: aws_resources["queue_url"]
        )
        monkeypatch.setattr(
            worker_main, "sqs_client", lambda: aws_resources["sqs"]
        )

        # Set the flag before run_forever starts — the loop should not even poll.
        worker_main._shutdown.set()

        # Should return immediately without blocking.
        worker_main.run_forever()

        # Clean up so other tests are not affected.
        worker_main._shutdown.clear()

    def test_shutdown_after_first_batch(self, aws_resources, monkeypatch):
        """run_forever processes a batch and then exits when _shutdown is set."""
        import app.main as worker_main

        worker_main._shutdown.clear()

        monkeypatch.setattr(
            worker_main, "get_queue_url", lambda: aws_resources["queue_url"]
        )
        monkeypatch.setattr(
            worker_main, "sqs_client", lambda: aws_resources["sqs"]
        )

        processed: list[str] = []

        def fake_process(body: str) -> None:
            processed.append(json.loads(body)["event_id"])
            # Simulate SIGTERM arriving while processing the first message.
            worker_main._shutdown.set()

        monkeypatch.setattr(worker_main, "process_message", fake_process)

        # Enqueue one message.
        aws_resources["sqs"].send_message(
            QueueUrl=aws_resources["queue_url"],
            MessageBody=json.dumps({"event_id": "shutdown-test"}),
        )

        worker_main.run_forever()

        # The message was fully processed before the loop exited.
        assert "shutdown-test" in processed

        worker_main._shutdown.clear()
