"""Streaming hook for forwarding events to clients.

Captures amplifier-core events and forwards them via the transport layer.
Also queues events for yielding by session.execute().
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ..transport.base import Event

logger = logging.getLogger(__name__)


class ServerStreamingHook:
    """Hook that forwards amplifier-core events to the server transport.

    This is registered with the session's hook registry to capture all
    events and forward them to connected clients via the send function.

    Events are also queued so they can be yielded by session.execute().
    This ensures the SDK client receives ALL events (thinking, tools, etc).
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
        # Queue for events to be yielded by execute()
        self._event_queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._streaming = False

    def set_send_fn(self, send_fn: Callable[[Event], Awaitable[None]]) -> None:
        """Set the send function after initialization."""
        self._send_fn = send_fn

    def start_streaming(self) -> None:
        """Start collecting events for streaming."""
        self._streaming = True
        # Clear any stale events
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def stop_streaming(self) -> None:
        """Stop streaming and signal completion."""
        self._streaming = False
        # Signal end of stream
        self._event_queue.put_nowait(None)

    async def get_events(self) -> AsyncIterator[Event]:
        """Yield events as they arrive during execution."""
        while True:
            event = await self._event_queue.get()
            if event is None:
                break
            yield event

    # Events with potentially huge payloads that should not be forwarded to clients
    SKIP_EVENTS = {
        "llm:request:raw",
        "llm:response:raw",
        "llm:request:debug",
        "llm:response:debug",
        "session:start:raw",
        "session:start:debug",
    }

    async def __call__(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle an event from amplifier-core.

        Args:
            event_type: The event type (e.g., "content_block:delta")
            data: The event data

        Returns:
            HookResult-compatible dict with action="continue"
        """
        # Skip raw/debug events with huge payloads
        if event_type in self.SKIP_EVENTS:
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

            # Queue event for yielding by execute()
            if self._streaming:
                self._event_queue.put_nowait(transport_event)

            # Also send via send_fn if available (for other channels)
            if self._send_fn:
                await self._send_fn(transport_event)

        except Exception as e:
            logger.warning(f"Failed to handle event {event_type}: {e}")

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
    "session:join",  # When sub-session completes
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
