"""Amplifier SDK - Client for connecting to Amplifier Server.

Provides both HTTP (remote) and embedded (in-process) modes.
"""

from .client import AmplifierClient, create_client, create_embedded_client
from .types import MessageInfo, MessagePart, SessionInfo

__all__ = [
    "AmplifierClient",
    "create_client",
    "create_embedded_client",
    "SessionInfo",
    "MessageInfo",
    "MessagePart",
]
