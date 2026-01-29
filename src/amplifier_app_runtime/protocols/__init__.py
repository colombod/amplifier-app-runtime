"""Protocol implementations for amplifier-core integration.

These implement the interfaces expected by amplifier-core for:
- Streaming events to clients
- Handling approval requests
- Displaying notifications
- Spawning sub-sessions
"""

from .approval import ServerApprovalSystem
from .display import ServerDisplaySystem
from .spawn import ServerSpawnManager, register_spawn_capability
from .streaming import (
    ServerStreamingHook,
    get_events_to_capture,
    register_streaming_hook,
)

__all__ = [
    "ServerApprovalSystem",
    "ServerDisplaySystem",
    "ServerSpawnManager",
    "ServerStreamingHook",
    "get_events_to_capture",
    "register_spawn_capability",
    "register_streaming_hook",
]
