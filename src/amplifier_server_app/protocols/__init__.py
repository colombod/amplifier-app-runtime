"""Protocol implementations for Amplifier Server.

These protocols bridge the gap between Amplifier's core abstractions
and the transport layer, enabling:
- Real-time event streaming to clients
- User approval handling
- Display notifications
- Agent spawning with event forwarding

Aligned with amplifier-web patterns for compatibility.
"""

from .approval import ApprovalSystem
from .display import DisplaySystem
from .hooks import StreamingHook
from .spawn import SpawnManager

__all__ = [
    "ApprovalSystem",
    "DisplaySystem",
    "StreamingHook",
    "SpawnManager",
]
