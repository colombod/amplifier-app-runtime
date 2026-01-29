"""Streaming hook for forwarding events to clients.

Captures amplifier-core events and forwards them via the transport layer.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..transport.base import Event

logger = logging.getLogger(__name__)


class ServerStreamingHook:
    """Hook that forwards amplifier-core events to the server transport.

    This is registered with the session's hook registry to capture all
    events and forward them to connected clients via the send function.

    Similar to WebStreamingHook in amplifier-web but transport-agnostic.
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Awaitable[None]] | None = None,
        show_thinking: bool = True,
    ) -> None:
        """Initialize the streaming hook.

        Args:
            send_fn: Async function to send events to the client
            show_thinking: Whether to forward thinking blocks
        """
        self._send_fn = send_fn
        self._show_thinking = show_thinking
        self._sequence = 0

    def set_send_fn(self, send_fn: Callable[[Event], Awaitable[None]]) -> None:
        """Set the send function after initialization."""
        self._send_fn = send_fn

    async def __call__(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle an event from amplifier-core.

        Args:
            event_type: The event type (e.g., "content_block:delta")
            data: The event data

        Returns:
            HookResult-compatible dict with action="continue"
        """
        if not self._send_fn:
            return {"action": "continue"}

        # Skip thinking events if disabled
        if not self._show_thinking and event_type.startswith("thinking:"):
            return {"action": "continue"}

        try:
            # Convert to transport Event
            transport_event = Event(
                type=event_type,
                properties=data,
                sequence=self._sequence,
            )
            self._sequence += 1

            await self._send_fn(transport_event)

        except Exception as e:
            logger.warning(f"Failed to send event {event_type}: {e}")

        # Always continue - streaming is observational
        return {"action": "continue"}

    def reset_sequence(self) -> None:
        """Reset the sequence counter for a new prompt."""
        self._sequence = 0


# Events to capture from amplifier-core
# Based on amplifier-web's event list and amplifier_core.events.ALL_EVENTS
DEFAULT_EVENTS_TO_CAPTURE = [
    # Content streaming
    "content_block:start",
    "content_block:delta",
    "content_block:end",
    # Thinking (extended thinking)
    "thinking:delta",
    "thinking:final",
    # Tool execution
    "tool:pre",
    "tool:post",
    "tool:error",
    # Session lifecycle
    "session:start",
    "session:end",
    "session:fork",
    "session:resume",
    # Prompt lifecycle
    "prompt:submit",
    "prompt:complete",
    # Provider/LLM
    "provider:request",
    "provider:response",
    "provider:error",
    "llm:request",
    "llm:request:debug",
    "llm:request:raw",
    "llm:response",
    "llm:response:debug",
    "llm:response:raw",
    # Cancellation
    "cancel:requested",
    "cancel:completed",
    # User notifications
    "user:notification",
    # Context
    "context:compaction",
    # Planning
    "plan:start",
    "plan:end",
    # Artifacts
    "artifact:write",
    "artifact:read",
    # Approval
    "approval:required",
    "approval:granted",
    "approval:denied",
]


def get_events_to_capture() -> list[str]:
    """Get list of events to capture.

    Tries to import ALL_EVENTS from amplifier-core, falls back to default list.

    Returns:
        List of event type strings to register hooks for.
    """
    try:
        from amplifier_core.events import ALL_EVENTS

        return list(ALL_EVENTS)
    except ImportError:
        logger.warning(
            "Could not import ALL_EVENTS from amplifier_core.events, using fallback list"
        )
        return DEFAULT_EVENTS_TO_CAPTURE.copy()


def register_streaming_hook(
    session: Any,
    hook: ServerStreamingHook,
) -> int:
    """Register streaming hook with a session's hook registry.

    Args:
        session: AmplifierSession to register hook on
        hook: The streaming hook instance

    Returns:
        Number of events registered
    """
    hook_registry = session.coordinator.hooks
    if not hook_registry:
        logger.warning("Session has no hook registry")
        return 0

    events = get_events_to_capture()

    # Also try to get auto-discovered module events
    discovered = session.coordinator.get_capability("observability.events") or []
    if discovered:
        events.extend(discovered)
        logger.info(f"Auto-discovered {len(discovered)} additional module events")

    # Register hook for each event
    for event in events:
        hook_registry.register(
            event=event,
            handler=hook,
            priority=100,  # Run early to capture events
            name=f"server-streaming:{event}",
        )

    logger.info(f"Registered streaming hook for {len(events)} events")
    return len(events)
