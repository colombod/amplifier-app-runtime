"""Unit tests for Event protocol type."""

import json
from datetime import datetime

from amplifier_server_app.protocol.events import Event, EventType


class TestEventCreation:
    """Test Event creation and basic properties."""

    def test_create_with_defaults(self):
        """Event should generate ID and timestamp automatically."""
        event = Event(type="test.event")

        assert event.type == "test.event"
        assert event.id.startswith("evt_")
        assert len(event.id) == 16  # "evt_" + 12 hex chars
        assert event.data == {}
        assert event.correlation_id is None
        assert event.sequence is None
        assert event.final is False

    def test_create_with_correlation(self):
        """Event should accept correlation_id."""
        event = Event(
            type="result",
            correlation_id="cmd_123",
            data={"key": "value"},
        )

        assert event.correlation_id == "cmd_123"
        assert event.is_correlated() is True

    def test_create_uncorrelated(self):
        """Event without correlation_id should report uncorrelated."""
        event = Event(type="notification")

        assert event.correlation_id is None
        assert event.is_correlated() is False

    def test_create_with_sequence(self):
        """Event should accept sequence number."""
        event = Event(
            type="content.delta",
            correlation_id="cmd_123",
            sequence=5,
        )

        assert event.sequence == 5

    def test_create_final_event(self):
        """Event should accept final marker."""
        event = Event(
            type="result",
            correlation_id="cmd_123",
            final=True,
        )

        assert event.final is True
        assert event.is_final() is True

    def test_timestamp_is_iso8601(self):
        """Event timestamp should be ISO8601 format."""
        event = Event(type="test")

        # Should parse without error
        parsed = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        assert parsed is not None


class TestEventFactoryMethod:
    """Test Event.create() factory method."""

    def test_create_basic(self):
        """Event.create() should work with minimal args."""
        event = Event.create(EventType.RESULT, {"key": "value"})

        assert event.type == "result"
        assert event.data["key"] == "value"

    def test_create_with_correlation(self):
        """Event.create() should accept correlation_id."""
        event = Event.create(
            EventType.CONTENT_DELTA,
            {"delta": "hello"},
            correlation_id="cmd_abc",
            sequence=0,
        )

        assert event.correlation_id == "cmd_abc"
        assert event.sequence == 0

    def test_create_with_string_type(self):
        """Event.create() should accept string type."""
        event = Event.create("custom.event", {"data": 123})

        assert event.type == "custom.event"


class TestEventConvenienceFactories:
    """Test convenience factory methods."""

    def test_result(self):
        """Event.result() should create final result event."""
        event = Event.result("cmd_123", {"session_id": "sess_456"})

        assert event.type == "result"
        assert event.correlation_id == "cmd_123"
        assert event.data["session_id"] == "sess_456"
        assert event.final is True

    def test_error(self):
        """Event.error() should create error event."""
        event = Event.error(
            "cmd_123",
            error="Something went wrong",
            code="TEST_ERROR",
            details={"context": "test"},
        )

        assert event.type == "error"
        assert event.correlation_id == "cmd_123"
        assert event.data["error"] == "Something went wrong"
        assert event.data["code"] == "TEST_ERROR"
        assert event.data["details"]["context"] == "test"
        assert event.final is True
        assert event.is_error() is True

    def test_error_uncorrelated(self):
        """Event.error() should work without correlation_id."""
        event = Event.error(None, error="Parse error", code="PARSE_ERROR")

        assert event.correlation_id is None
        assert event.is_error() is True

    def test_ack(self):
        """Event.ack() should create acknowledgment event."""
        event = Event.ack("cmd_123", message="Processing")

        assert event.type == "ack"
        assert event.correlation_id == "cmd_123"
        assert event.data["message"] == "Processing"
        assert event.final is False

    def test_content_delta(self):
        """Event.content_delta() should create streaming delta."""
        event = Event.content_delta(
            correlation_id="cmd_123",
            delta="Hello",
            sequence=0,
            block_index=0,
        )

        assert event.type == "content.delta"
        assert event.correlation_id == "cmd_123"
        assert event.data["delta"] == "Hello"
        assert event.data["block_index"] == 0
        assert event.sequence == 0
        assert event.final is False

    def test_content_end(self):
        """Event.content_end() should create final content event."""
        event = Event.content_end(
            correlation_id="cmd_123",
            content="Hello world",
            sequence=5,
            block_index=0,
        )

        assert event.type == "content.end"
        assert event.data["content"] == "Hello world"
        assert event.final is True

    def test_tool_call(self):
        """Event.tool_call() should create tool call event."""
        event = Event.tool_call(
            correlation_id="cmd_123",
            tool_name="read_file",
            tool_call_id="tc_456",
            arguments={"path": "/tmp/test.txt"},
            sequence=2,
        )

        assert event.type == "tool.call"
        assert event.data["tool_name"] == "read_file"
        assert event.data["tool_call_id"] == "tc_456"
        assert event.data["arguments"]["path"] == "/tmp/test.txt"

    def test_tool_result(self):
        """Event.tool_result() should create tool result event."""
        event = Event.tool_result(
            correlation_id="cmd_123",
            tool_call_id="tc_456",
            output={"content": "file contents"},
            sequence=3,
        )

        assert event.type == "tool.result"
        assert event.data["tool_call_id"] == "tc_456"
        assert event.data["output"]["content"] == "file contents"

    def test_approval_required(self):
        """Event.approval_required() should create approval event."""
        event = Event.approval_required(
            correlation_id="cmd_123",
            request_id="req_789",
            prompt="Allow file write?",
            options=["yes", "no", "always"],
            timeout=30.0,
            sequence=4,
        )

        assert event.type == "approval.required"
        assert event.data["request_id"] == "req_789"
        assert event.data["prompt"] == "Allow file write?"
        assert event.data["options"] == ["yes", "no", "always"]
        assert event.data["timeout"] == 30.0

    def test_notification(self):
        """Event.notification() should create uncorrelated notification."""
        event = Event.notification(
            message="Server restarting",
            level="warning",
            source="system",
        )

        assert event.type == "notification"
        assert event.correlation_id is None
        assert event.data["message"] == "Server restarting"
        assert event.data["level"] == "warning"
        assert event.data["source"] == "system"

    def test_pong(self):
        """Event.pong() should create ping response."""
        event = Event.pong("cmd_ping")

        assert event.type == "pong"
        assert event.correlation_id == "cmd_ping"
        assert event.final is True

    def test_connected(self):
        """Event.connected() should create connection event."""
        event = Event.connected({"transport": "websocket", "version": "1.0"})

        assert event.type == "connected"
        assert event.data["capabilities"]["transport"] == "websocket"


class TestEventSerialization:
    """Test JSON serialization/deserialization."""

    def test_serialize_to_json(self):
        """Event should serialize to JSON."""
        event = Event(
            id="evt_test123",
            type="result",
            correlation_id="cmd_abc",
            data={"key": "value"},
            final=True,
        )

        json_str = event.model_dump_json()
        data = json.loads(json_str)

        assert data["id"] == "evt_test123"
        assert data["type"] == "result"
        assert data["correlation_id"] == "cmd_abc"
        assert data["data"]["key"] == "value"
        assert data["final"] is True

    def test_deserialize_from_json(self):
        """Event should deserialize from JSON."""
        json_str = """{
            "id": "evt_abc",
            "type": "content.delta",
            "correlation_id": "cmd_123",
            "data": {"delta": "Hello"},
            "sequence": 0,
            "final": false,
            "timestamp": "2024-01-15T10:30:00+00:00"
        }"""

        event = Event.model_validate_json(json_str)

        assert event.id == "evt_abc"
        assert event.type == "content.delta"
        assert event.correlation_id == "cmd_123"
        assert event.data["delta"] == "Hello"
        assert event.sequence == 0
        assert event.final is False

    def test_roundtrip_with_unicode(self):
        """Event should roundtrip with Unicode content."""
        original = Event.content_delta(
            correlation_id="cmd_unicode",
            delta="Hello 世界 🌍 Привет",
            sequence=0,
        )

        json_str = original.model_dump_json()
        restored = Event.model_validate_json(json_str)

        assert restored.data["delta"] == "Hello 世界 🌍 Привет"

    def test_serialize_excludes_none_values(self):
        """Serialization should handle None values appropriately."""
        event = Event(type="test", correlation_id=None, sequence=None)

        json_str = event.model_dump_json()
        data = json.loads(json_str)

        # Pydantic includes None by default, which is fine for protocol
        assert "correlation_id" in data
        assert data["correlation_id"] is None


class TestEventTypes:
    """Test EventType enum."""

    def test_all_event_types_are_strings(self):
        """All EventType values should be valid strings."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)

    def test_expected_event_types_exist(self):
        """Expected event types should be defined."""
        expected = [
            "result",
            "error",
            "ack",
            "stream.start",
            "stream.delta",
            "stream.end",
            "content.start",
            "content.delta",
            "content.end",
            "tool.call",
            "tool.result",
            "approval.required",
            "approval.resolved",
            "connected",
            "pong",
            "notification",
        ]

        values = [et.value for et in EventType]
        for exp in expected:
            assert exp in values, f"Missing event type: {exp}"


class TestCorrelationPatterns:
    """Test correlation ID patterns for request/response."""

    def test_streaming_sequence(self):
        """Streaming events should have incrementing sequence."""
        correlation_id = "cmd_stream_test"

        events = [
            Event.ack(correlation_id),
            Event.content_delta(correlation_id, "Hello", sequence=0),
            Event.content_delta(correlation_id, " world", sequence=1),
            Event.content_end(correlation_id, "Hello world", sequence=2),
        ]

        # All events should have same correlation_id
        for event in events:
            assert event.correlation_id == correlation_id

        # Sequences should be ordered
        sequences = [e.sequence for e in events if e.sequence is not None]
        assert sequences == [0, 1, 2]

        # Only last should be final
        assert events[-1].is_final() is True
        assert all(not e.is_final() for e in events[:-1])

    def test_mixed_correlated_and_uncorrelated(self):
        """System can have both correlated and uncorrelated events."""
        correlated = Event.result("cmd_123", {"done": True})
        uncorrelated = Event.notification("Server event")

        assert correlated.is_correlated() is True
        assert uncorrelated.is_correlated() is False
