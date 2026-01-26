"""Transport abstraction base classes.

Defines the protocol-agnostic interfaces that allow swapping
SSE for HTTP/3 + WebTransport without changing client code.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class Event(BaseModel):
    """Base event structure."""

    type: str
    properties: dict


@runtime_checkable
class EventStream(Protocol):
    """Protocol for consuming events from server.

    Implementations:
    - SSEEventStream: Server-Sent Events over HTTP/1.1 or HTTP/2
    - WebTransportEventStream: HTTP/3 WebTransport (future)
    """

    def __aiter__(self) -> AsyncIterator[Event]:
        """Iterate over events from the stream."""
        ...

    async def close(self) -> None:
        """Close the event stream."""
        ...


@runtime_checkable
class EventPublisher(Protocol):
    """Protocol for publishing events to connected clients.

    Server-side interface for pushing events.
    """

    async def publish(self, event: Event) -> None:
        """Publish an event to all connected subscribers."""
        ...

    async def subscribe(self) -> AsyncIterator[Event]:
        """Subscribe to receive events."""
        ...


@dataclass
class TransportConfig:
    """Transport configuration."""

    # Connection settings
    base_url: str = "http://localhost:4096"
    timeout: float = 30.0

    # Reconnection settings (for intermittent connectivity)
    reconnect: bool = True
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 30.0
    reconnect_backoff: float = 2.0

    # HTTP/3 specific (future)
    prefer_http3: bool = False
    quic_config: dict = field(default_factory=dict)


class EventStreamFactory(ABC):
    """Factory for creating event streams.

    Allows runtime selection of transport based on config and availability.
    """

    @abstractmethod
    async def create_stream(self, config: TransportConfig) -> EventStream:
        """Create an event stream with the given configuration."""
        ...

    @abstractmethod
    def supports_http3(self) -> bool:
        """Check if this factory supports HTTP/3."""
        ...
