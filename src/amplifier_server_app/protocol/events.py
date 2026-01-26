"""Event definitions for the protocol layer.

Events are server responses sent to clients. They can be:
- Correlated: Response to a specific command (has correlation_id)
- Uncorrelated: Server-initiated notifications (no correlation_id)

Streaming commands produce multiple events with the same correlation_id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """All event types in the protocol."""

    # Response events (correlated to commands)
    RESULT = "result"  # Final result of a command
    ERROR = "error"  # Error response to a command
    ACK = "ack"  # Acknowledgment (command received, processing)

    # Streaming events (correlated, multiple per command)
    STREAM_START = "stream.start"
    STREAM_DELTA = "stream.delta"
    STREAM_END = "stream.end"

    # Content streaming (aligned with Amplifier events)
    CONTENT_START = "content.start"
    CONTENT_DELTA = "content.delta"
    CONTENT_END = "content.end"

    # Thinking/reasoning
    THINKING_DELTA = "thinking.delta"
    THINKING_END = "thinking.end"

    # Tool execution
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"

    # Session lifecycle
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    SESSION_DELETED = "session.deleted"
    SESSION_STATE = "session.state"

    # Approval flow
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_RESOLVED = "approval.resolved"

    # Agent spawning
    AGENT_SPAWNED = "agent.spawned"
    AGENT_COMPLETED = "agent.completed"

    # Server events (uncorrelated)
    CONNECTED = "connected"
    PING = "pong"  # Response to ping
    NOTIFICATION = "notification"
    HEARTBEAT = "heartbeat"


class Event(BaseModel):
    """An event from server to client.

    Events are the response side of the protocol. Each event:
    - Has a unique `id` for deduplication
    - Has a `type` identifying the event kind
    - Has optional `correlation_id` linking to originating command
    - Has `data` containing the event payload

    Correlation patterns:
    - Request/Response: One command → one event with correlation_id
    - Streaming: One command → multiple events with same correlation_id
    - Server-initiated: No correlation_id (notifications, heartbeats)

    Example (correlated response):
        {
            "id": "evt_xyz789",
            "type": "result",
            "correlation_id": "cmd_abc123",
            "data": {"session_id": "sess_456", "state": "ready"}
        }

    Example (streaming):
        {
            "id": "evt_001",
            "type": "content.delta",
            "correlation_id": "cmd_abc123",
            "data": {"delta": "Hello"}
        }
        {
            "id": "evt_002",
            "type": "content.delta",
            "correlation_id": "cmd_abc123",
            "data": {"delta": " world"}
        }
        {
            "id": "evt_003",
            "type": "content.end",
            "correlation_id": "cmd_abc123",
            "data": {"content": "Hello world"}
        }

    Example (uncorrelated):
        {
            "id": "evt_heartbeat_1",
            "type": "heartbeat",
            "data": {"timestamp": "2024-01-15T10:30:00Z"}
        }
    """

    id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    type: str
    correlation_id: str | None = None  # Links to command.id
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Stream position (for ordered streaming events)
    sequence: int | None = None  # Position in stream (0, 1, 2, ...)
    final: bool = False  # True if this is the last event for correlation_id

    def is_correlated(self) -> bool:
        """Check if this event is a response to a command."""
        return self.correlation_id is not None

    def is_final(self) -> bool:
        """Check if this is the final event for a command."""
        return self.final

    def is_error(self) -> bool:
        """Check if this is an error event."""
        return self.type == EventType.ERROR.value

    @classmethod
    def create(
        cls,
        event_type: str | EventType,
        data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        sequence: int | None = None,
        final: bool = False,
    ) -> Event:
        """Factory method for creating events."""
        return cls(
            type=event_type.value if isinstance(event_type, EventType) else event_type,
            data=data or {},
            correlation_id=correlation_id,
            sequence=sequence,
            final=final,
        )

    # =========================================================================
    # Factory methods for common events
    # =========================================================================

    @classmethod
    def result(
        cls,
        correlation_id: str,
        data: dict[str, Any],
    ) -> Event:
        """Create a successful result event (final response to command)."""
        return cls.create(
            EventType.RESULT,
            data=data,
            correlation_id=correlation_id,
            final=True,
        )

    @classmethod
    def error(
        cls,
        correlation_id: str | None,
        error: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> Event:
        """Create an error event."""
        data: dict[str, Any] = {"error": error}
        if code:
            data["code"] = code
        if details:
            data["details"] = details
        return cls.create(
            EventType.ERROR,
            data=data,
            correlation_id=correlation_id,
            final=True,
        )

    @classmethod
    def ack(cls, correlation_id: str, message: str | None = None) -> Event:
        """Create an acknowledgment event (command received)."""
        return cls.create(
            EventType.ACK,
            data={"message": message} if message else {},
            correlation_id=correlation_id,
        )

    @classmethod
    def content_delta(
        cls,
        correlation_id: str,
        delta: str,
        sequence: int,
        block_index: int = 0,
    ) -> Event:
        """Create a content streaming delta event."""
        return cls.create(
            EventType.CONTENT_DELTA,
            data={"delta": delta, "block_index": block_index},
            correlation_id=correlation_id,
            sequence=sequence,
        )

    @classmethod
    def content_end(
        cls,
        correlation_id: str,
        content: str,
        sequence: int,
        block_index: int = 0,
    ) -> Event:
        """Create a content streaming end event."""
        return cls.create(
            EventType.CONTENT_END,
            data={"content": content, "block_index": block_index},
            correlation_id=correlation_id,
            sequence=sequence,
            final=True,
        )

    @classmethod
    def tool_call(
        cls,
        correlation_id: str,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        sequence: int,
    ) -> Event:
        """Create a tool call event."""
        return cls.create(
            EventType.TOOL_CALL,
            data={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "arguments": arguments,
            },
            correlation_id=correlation_id,
            sequence=sequence,
        )

    @classmethod
    def tool_result(
        cls,
        correlation_id: str,
        tool_call_id: str,
        output: Any,
        sequence: int,
    ) -> Event:
        """Create a tool result event."""
        return cls.create(
            EventType.TOOL_RESULT,
            data={
                "tool_call_id": tool_call_id,
                "output": output,
            },
            correlation_id=correlation_id,
            sequence=sequence,
        )

    @classmethod
    def approval_required(
        cls,
        correlation_id: str,
        request_id: str,
        prompt: str,
        options: list[str],
        timeout: float,
        sequence: int,
    ) -> Event:
        """Create an approval required event."""
        return cls.create(
            EventType.APPROVAL_REQUIRED,
            data={
                "request_id": request_id,
                "prompt": prompt,
                "options": options,
                "timeout": timeout,
            },
            correlation_id=correlation_id,
            sequence=sequence,
        )

    @classmethod
    def notification(
        cls,
        message: str,
        level: str = "info",
        source: str | None = None,
    ) -> Event:
        """Create an uncorrelated notification event."""
        data = {"message": message, "level": level}
        if source:
            data["source"] = source
        return cls.create(EventType.NOTIFICATION, data=data)

    @classmethod
    def pong(cls, correlation_id: str) -> Event:
        """Create a pong response to ping."""
        return cls.create(
            EventType.PING,
            correlation_id=correlation_id,
            final=True,
        )

    @classmethod
    def connected(cls, capabilities: dict[str, Any] | None = None) -> Event:
        """Create a connected event (sent on transport connect)."""
        return cls.create(
            EventType.CONNECTED,
            data={"capabilities": capabilities or {}},
        )
