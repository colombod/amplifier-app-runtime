"""Transport abstraction base classes.

Defines the protocol-agnostic interfaces that allow swapping
between SSE, WebTransport, WebSocket, and stdio without changing client code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel


class TransportMode(str, Enum):
    """Available transport modes."""

    SSE = "sse"  # Server-Sent Events (HTTP/1.1, HTTP/2)
    WEBSOCKET = "websocket"  # WebSocket
    WEBTRANSPORT = "webtransport"  # HTTP/3 WebTransport
    STDIO = "stdio"  # stdin/stdout (for subprocess/IPC)


class Event(BaseModel):
    """Base event structure."""

    type: str
    properties: dict[str, Any] = {}


class EventStream(ABC):
    """Abstract base for consuming events from server.

    Implementations:
    - SSEEventStream: Server-Sent Events over HTTP/1.1 or HTTP/2
    - WebTransportEventStream: HTTP/3 WebTransport
    - StdioEventStream: stdin/stdout for subprocess IPC
    """

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[Event]:
        """Iterate over events from the stream."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the event stream."""
        ...


class EventPublisher(ABC):
    """Abstract base for publishing events to connected clients.

    Server-side interface for pushing events.
    """

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """Publish an event to all connected subscribers."""
        ...

    @abstractmethod
    async def subscribe(self) -> AsyncIterator[Event]:
        """Subscribe to receive events."""
        ...


@dataclass
class TransportConfig:
    """Transport configuration."""

    # Transport mode
    mode: TransportMode = TransportMode.SSE

    # Connection settings (for network transports)
    base_url: str = "http://localhost:4096"
    timeout: float = 30.0

    # Reconnection settings (for intermittent connectivity)
    reconnect: bool = True
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 30.0
    reconnect_backoff: float = 2.0

    # HTTP/3 / WebTransport specific
    prefer_http3: bool = False
    quic_config: dict = field(default_factory=dict)

    # TLS settings (required for HTTP/3)
    certfile: str | None = None
    keyfile: str | None = None


class EventStreamFactory(ABC):
    """Factory for creating event streams.

    Allows runtime selection of transport based on config and availability.
    """

    @abstractmethod
    async def create_stream(self, config: TransportConfig) -> EventStream:
        """Create an event stream with the given configuration."""
        ...

    @abstractmethod
    def supports_mode(self, mode: TransportMode) -> bool:
        """Check if this factory supports the given transport mode."""
        ...


class Transport(ABC):
    """Abstract bidirectional transport.

    Combines reading and writing for full-duplex communication.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the transport connection."""
        ...

    @abstractmethod
    async def send(self, event: Event) -> None:
        """Send an event."""
        ...

    @abstractmethod
    def receive(self) -> AsyncIterator[Event]:
        """Receive events."""
        ...

    async def __aenter__(self) -> Transport:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()
