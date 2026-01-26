"""Transport abstraction layer.

Provides protocol-agnostic interfaces for event streaming.
Start with SSE over HTTP/2, designed for HTTP/3 + WebTransport future.
"""

from .base import EventStream, EventStreamFactory, TransportConfig
from .sse import SSEEventStream, SSETransport

__all__ = [
    "EventStream",
    "EventStreamFactory",
    "TransportConfig",
    "SSEEventStream",
    "SSETransport",
]
