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
from .websocket import (
    WebSocketClientTransport,
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketServerTransport,
)

# Note: stdio_adapter is imported separately to avoid circular imports
# Use: from amplifier_app_runtime.transport.stdio_adapter import StdioProtocolAdapter

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
    # WebSocket implementation
    "WebSocketClientTransport",
    "WebSocketServerTransport",
    "WebSocketMessage",
    "WebSocketMessageType",
    # stdio implementation
    "StdioConfig",
    "StdioTransport",
    "run_stdio_server",
]
