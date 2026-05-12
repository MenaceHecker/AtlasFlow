"""
Unit tests for the built-in handlers and the handler registry.
No AWS resources needed — handlers are pure functions.
"""
from __future__ import annotations

import pytest

from app.services.handlers.base import BaseHandler
from app.services.handlers.registry import HandlerRegistry
from app.services.handlers.builtin import (
    PingHandler,
    DataTransformHandler,
    NotifyHandler,
    FallbackHandler,
)


# ── PingHandler ───────────────────────────────────────────────────────────────

class TestPingHandler:
    def test_returns_pong(self):
        result = PingHandler().handle("evt-1", {"key": "val"})
        assert result["pong"] is True
        assert result["handler"] == "PingHandler"

    def test_echoes_payload(self):
        payload = {"foo": "bar"}
        result = PingHandler().handle("evt-2", payload)
        assert result["echo"] == payload

    def test_empty_payload_is_fine(self):
        result = PingHandler().handle("evt-3", {})
        assert result["pong"] is True


# ── DataTransformHandler ──────────────────────────────────────────────────────

class TestDataTransformHandler:
    def test_uppercase(self):
        payload = {"fields": {"name": "alice"}, "operation": "uppercase"}
        result = DataTransformHandler().handle("evt-4", payload)
        assert result["transformed"]["name"] == "ALICE"
        assert result["operation"] == "uppercase"

    def test_lowercase(self):
        payload = {"fields": {"city": "NYC"}, "operation": "lowercase"}
        result = DataTransformHandler().handle("evt-5", payload)
        assert result["transformed"]["city"] == "nyc"

    def test_reverse(self):
        payload = {"fields": {"word": "hello"}, "operation": "reverse"}
        result = DataTransformHandler().handle("evt-6", payload)
        assert result["transformed"]["word"] == "olleh"

    def test_defaults_to_uppercase_when_no_operation(self):
        payload = {"fields": {"x": "abc"}}
        result = DataTransformHandler().handle("evt-7", payload)
        assert result["transformed"]["x"] == "ABC"

    def test_invalid_operation_raises(self):
        payload = {"fields": {"x": "abc"}, "operation": "rot13"}
        with pytest.raises(ValueError, match="Unsupported operation"):
            DataTransformHandler().handle("evt-8", payload)

    def test_empty_fields_returns_empty_transformed(self):
        payload = {"fields": {}, "operation": "uppercase"}
        result = DataTransformHandler().handle("evt-9", payload)
        assert result["transformed"] == {}

    def test_multiple_fields(self):
        payload = {
            "fields": {"first": "alice", "last": "smith"},
            "operation": "uppercase",
        }
        result = DataTransformHandler().handle("evt-10", payload)
        assert result["transformed"] == {"first": "ALICE", "last": "SMITH"}


# ── NotifyHandler ─────────────────────────────────────────────────────────────

class TestNotifyHandler:
    def _base_payload(self, channel="email"):
        return {
            "channel": channel,
            "recipient": "user@example.com",
            "message": "Hello from AtlasFlow",
        }

    def test_email_delivery(self):
        result = NotifyHandler().handle("evt-11", self._base_payload("email"))
        assert result["delivered"] is True
        assert result["channel"] == "email"
        assert result["handler"] == "NotifyHandler"

    def test_sms_delivery(self):
        result = NotifyHandler().handle("evt-12", self._base_payload("sms"))
        assert result["delivered"] is True
        assert result["channel"] == "sms"

    def test_push_delivery(self):
        result = NotifyHandler().handle("evt-13", self._base_payload("push"))
        assert result["delivered"] is True

    def test_message_preview_truncated_at_80(self):
        long_msg = "A" * 200
        payload = {**self._base_payload(), "message": long_msg}
        result = NotifyHandler().handle("evt-14", payload)
        assert len(result["message_preview"]) == 80

    def test_missing_channel_raises(self):
        payload = {"recipient": "x@y.com", "message": "hi"}
        with pytest.raises(ValueError, match="channel"):
            NotifyHandler().handle("evt-15", payload)

    def test_unsupported_channel_raises(self):
        payload = {"channel": "carrier_pigeon", "recipient": "x", "message": "hi"}
        with pytest.raises(ValueError, match="Unsupported channel"):
            NotifyHandler().handle("evt-16", payload)

    def test_missing_recipient_raises(self):
        payload = {"channel": "email", "message": "hi"}
        with pytest.raises(ValueError, match="recipient"):
            NotifyHandler().handle("evt-17", payload)

    def test_missing_message_raises(self):
        payload = {"channel": "email", "recipient": "x@y.com"}
        with pytest.raises(ValueError, match="message"):
            NotifyHandler().handle("evt-18", payload)


# ── FallbackHandler ───────────────────────────────────────────────────────────

class TestFallbackHandler:
    def test_returns_warning_result(self):
        result = FallbackHandler().handle("evt-19", {})
        assert result["handler"] == "FallbackHandler"
        assert "warning" in result
        assert "No handler registered" in result["warning"]


# ── HandlerRegistry ───────────────────────────────────────────────────────────

class TestHandlerRegistry:
    def test_register_and_dispatch(self):
        reg = HandlerRegistry()

        @reg.register("test.event")
        class MyHandler(BaseHandler):
            def handle(self, event_id, payload):
                return {"ok": True}

        result = reg.dispatch("test.event", "evt-20", {})
        assert result == {"ok": True}

    def test_dispatch_unknown_type_uses_fallback(self):
        reg = HandlerRegistry()
        result = reg.dispatch("completely.unknown", "evt-21", {})
        assert result["handler"] == "FallbackHandler"

    def test_registered_types_lists_types(self):
        reg = HandlerRegistry()

        @reg.register("foo")
        class FooHandler(BaseHandler):
            def handle(self, event_id, payload):
                return {}

        assert "foo" in reg.registered_types

    def test_overwrite_logs_warning(self, caplog):
        import logging
        reg = HandlerRegistry()

        @reg.register("dup.type")
        class FirstHandler(BaseHandler):
            def handle(self, event_id, payload):
                return {"v": 1}

        with caplog.at_level(logging.WARNING, logger="app.services.handlers.registry"):
            @reg.register("dup.type")
            class SecondHandler(BaseHandler):
                def handle(self, event_id, payload):
                    return {"v": 2}

        assert any("already registered" in r.message for r in caplog.records)
        # The second registration wins
        result = reg.dispatch("dup.type", "evt-22", {})
        assert result["v"] == 2

    def test_builtin_types_are_registered(self):
        """Importing builtin registers ping, data.transform, notify in the global registry."""
        import app.services.handlers.builtin  # noqa: F401
        from app.services.handlers.registry import registry

        for expected in ("ping", "data.transform", "notify"):
            assert expected in registry.registered_types
