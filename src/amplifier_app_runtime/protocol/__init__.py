"""Transport-agnostic protocol layer.

Defines the command/event protocol that works identically
across all transports (HTTP, WebSocket, stdio, WebTransport).

Key concepts:
- Commands: Client → Server requests with correlation IDs
- Events: Server → Client responses/streams with correlation IDs
- Correlation: Every event links back to its originating command

This enables:
- Request/response patterns (command → single event)
- Streaming patterns (command → multiple events)
- Server-initiated events (no correlation ID)
- Error handling with proper correlation
"""

from .commands import Command, CommandType
from .events import Event, EventType
from .handler import CommandHandler

__all__ = [
    "Command",
    "CommandType",
    "Event",
    "EventType",
    "CommandHandler",
]
