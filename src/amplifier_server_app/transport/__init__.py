"""Transport abstraction layer.

Provides protocol-agnostic interfaces for client-server communication:
- SSE (Server-Sent Events) - HTTP/1.1, HTTP/2, wide compatibility
- WebSocket - Bidirectional, widely supported
- WebTransport - HTTP/3, best for multiplexing and reconnection
- stdio - For subprocess/IPC/editor integration

The transport layer abstracts the underlying protocol so clients
and servers can switch between transports without code changes.
"""

from .base import (
    Event,
    EventPublisher,
    EventStream,
    EventStreamFactory,
    Transport,
    TransportConfig,
    TransportMode,
)
from .sse import SSEEventStream
from .stdio import StdioConfig, StdioTransport, run_stdio_server
from .stdio_adapter import StdioProtocolAdapter, run_stdio_adapter

__all__ = [
    # Base abstractions
    "Event",
    "EventStream",
    "EventPublisher",
    "EventStreamFactory",
    "Transport",
    "TransportConfig",
    "TransportMode",
    # SSE implementation
    "SSEEventStream",
    # stdio implementation
    "StdioConfig",
    "StdioTransport",
    "run_stdio_server",
    # Protocol-based stdio adapter
    "StdioProtocolAdapter",
    "run_stdio_adapter",
]
