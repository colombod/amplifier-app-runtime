"""Amplifier SDK - Client for connecting to Amplifier Server.

Provides multiple transport modes:
- stdio: Launch runtime as subprocess (TUI, CLI integration)
- http: Connect to existing HTTP server
- mock: For testing without real I/O

Two client APIs:
- AmplifierClient: HTTP-based client (legacy, for direct HTTP connections)
- TransportAmplifierClient: Transport-agnostic client (recommended for new integrations)
"""

from .client import AmplifierClient, create_client, create_embedded_client
from .transport import (
    BaseClientTransport,
    ClientTransport,
    ClientTransportConfig,
    HTTPClientTransport,
    MockClientTransport,
    StdioClientTransport,
    TransportState,
    create_http_transport,
    create_mock_transport,
    create_stdio_transport,
)
from .transport_client import (
    TransportAmplifierClient,
    TransportApprovalAPI,
    TransportEventAPI,
    TransportSessionAPI,
    create_attach_client,
    create_subprocess_client,
    create_test_client,
)
from .types import MessageInfo, MessagePart, SessionInfo

__all__ = [
    # Transport-aware Client (recommended)
    "TransportAmplifierClient",
    "TransportSessionAPI",
    "TransportEventAPI",
    "TransportApprovalAPI",
    "create_subprocess_client",
    "create_attach_client",
    "create_test_client",
    # HTTP Client (legacy)
    "AmplifierClient",
    "create_client",
    "create_embedded_client",
    # Transport Protocol & Base
    "ClientTransport",
    "BaseClientTransport",
    "ClientTransportConfig",
    "TransportState",
    # Transport Implementations
    "StdioClientTransport",
    "HTTPClientTransport",
    "MockClientTransport",
    # Transport Factory Functions
    "create_stdio_transport",
    "create_http_transport",
    "create_mock_transport",
    # Types
    "SessionInfo",
    "MessageInfo",
    "MessagePart",
]
