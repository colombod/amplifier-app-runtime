"""HTTP API routes."""

from .events import event_routes
from .health import health_routes
from .protocol_adapter import protocol_routes
from .session import session_routes
from .websocket import websocket_routes

__all__ = [
    "event_routes",
    "health_routes",
    "session_routes",
    "protocol_routes",
    "websocket_routes",
]
