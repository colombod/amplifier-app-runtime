"""Streaming Hook Protocol.

Implements a hook that streams Amplifier events to clients via the transport layer.
Handles event mapping, filtering, and sanitization for safe transmission.

Design: Pass through ALL raw event data unchanged (except image sanitization).
Clients receive exactly what Amplifier emits for full debugging capability.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from ..event_types import UI_EVENTS, is_debug_event

if TYPE_CHECKING:
    from ..transport.base import Event

logger = logging.getLogger(__name__)


class StreamingHook:
    """Transport-agnostic streaming hook for real-time event delivery.

    Subscribes to Amplifier events and forwards them to clients
    for real-time display of streaming content, tool calls, and status.

    All events pass through raw data unchanged (only images sanitized).

    Usage:
        hook = StreamingHook(send_fn=transport.send)

        # Register with session's hook registry
        for event in ALL_EVENTS:
            hook_registry.register(event, hook, priority=100)
    """

    # Hook metadata (for registration)
    name = "streaming"
    priority = 100  # Run early to capture events

    def __init__(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]] | None = None,
        show_thinking: bool = True,
        include_debug: bool = False,
    ):
        """Initialize streaming hook.

        Args:
            send_fn: Async function to send events to client
            show_thinking: Whether to stream thinking blocks
            include_debug: Whether to include debug/raw events
        """
        self._send = send_fn
        self._show_thinking = show_thinking
        self._include_debug = include_debug
        self._current_blocks: dict[int, str] = {}  # index -> block_type

    async def __call__(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle Amplifier event and stream to client.

        Args:
            event: Event name (e.g., "content_block:start")
            data: Event data dict

        Returns:
            HookResult-compatible dict with action="continue"
        """
        # Log all events for debugging
        logger.debug(f"[EVENT] {event}: {list(data.keys()) if data else 'no data'}")

        # Filter debug events unless explicitly included
        if is_debug_event(event) and not self._include_debug:
            return {"action": "continue"}

        # Filter non-UI events
        if event not in UI_EVENTS and not self._include_debug:
            return {"action": "continue"}

        try:
            message = self._map_event_to_message(event, data)
            if message and self._send:
                from ..transport.base import Event as TransportEvent

                await self._send(TransportEvent(type=message["type"], properties=message))
                logger.debug(f"[SENT] {message.get('type', event)}")
        except Exception as e:
            logger.warning(f"Failed to stream event {event}: {e}")

        # Always continue - streaming is observational
        return {"action": "continue"}

    def _map_event_to_message(self, event: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Map Amplifier event to transport message format.

        Passes through full raw data. Only adds minimal required fields
        for UI functionality. Images are sanitized to avoid huge payloads.

        Args:
            event: Event name
            data: Event data

        Returns:
            Transport message dict or None if event should be skipped
        """
        # Sanitize to remove only image binary data
        sanitized = self._sanitize_for_transport(data)

        # Convert event name to message type
        # e.g., "content_block:start" -> "content_start"
        msg_type = event.replace(":", "_").replace("_block", "")

        # Content streaming events - need index tracking for UI
        if event == "content_block:start":
            block_type = data.get("block_type") or data.get("type", "text")
            block_index = data.get("block_index")
            fallback_index = data.get("index")
            index: int = (
                block_index
                if block_index is not None
                else (fallback_index if fallback_index is not None else 0)
            )
            self._current_blocks[index] = block_type

            # Skip thinking blocks if disabled
            if block_type == "thinking" and not self._show_thinking:
                return None

            return {
                "type": "content_start",
                "block_type": block_type,
                "index": index,
                **sanitized,
            }

        elif event == "content_block:delta":
            block_index = data.get("block_index")
            fallback_index = data.get("index")
            index = (
                block_index
                if block_index is not None
                else (fallback_index if fallback_index is not None else 0)
            )
            block_type = self._current_blocks.get(index, "text")

            # Skip thinking blocks if disabled
            if block_type == "thinking" and not self._show_thinking:
                return None

            # Extract delta text for UI convenience
            delta = data.get("delta", {})
            delta_text = delta.get("text", "") if isinstance(delta, dict) else str(delta)

            return {
                "type": "content_delta",
                "index": index,
                "delta": delta_text,
                "block_type": block_type,
                **sanitized,
            }

        elif event == "content_block:end":
            block_index = data.get("block_index")
            fallback_index = data.get("index")
            index = (
                block_index
                if block_index is not None
                else (fallback_index if fallback_index is not None else 0)
            )
            block_type = self._current_blocks.pop(index, "text")

            # Skip thinking blocks if disabled
            if block_type == "thinking" and not self._show_thinking:
                return None

            # Extract content for UI convenience
            block = data.get("block", {})
            if isinstance(block, dict):
                content = block.get("text", "") or block.get("content", "")
            else:
                content = data.get("content", "")

            return {
                "type": "content_end",
                "index": index,
                "content": content,
                "block_type": block_type,
                **sanitized,
            }

        # Thinking events
        elif event == "thinking:delta":
            if not self._show_thinking:
                return None
            return {"type": "thinking_delta", **sanitized}

        elif event == "thinking:final":
            if not self._show_thinking:
                return None
            return {"type": "thinking_final", **sanitized}

        # Tool lifecycle
        elif event == "tool:pre":
            return {
                "type": "tool_call",
                "tool_name": data.get("tool_name", "unknown"),
                "tool_call_id": data.get("tool_call_id", ""),
                "arguments": data.get("tool_input") or data.get("arguments", {}),
                "status": "pending",
                **sanitized,
            }

        elif event == "tool:post":
            result = data.get("result", {})
            return {
                "type": "tool_result",
                "tool_name": data.get("tool_name", "unknown"),
                "tool_call_id": data.get("tool_call_id", ""),
                "output": (result.get("output", "") if isinstance(result, dict) else str(result)),
                "success": result.get("success", True) if isinstance(result, dict) else True,
                "error": result.get("error") if isinstance(result, dict) else None,
                **sanitized,
            }

        elif event == "tool:error":
            return {"type": "tool_error", **sanitized}

        # Session lifecycle
        elif event == "session:fork":
            return {"type": "session_fork", **sanitized}

        # User notifications
        elif event == "user:notification":
            return {"type": "display_message", **sanitized}

        # All other events - pass through with raw data
        else:
            return {
                "type": msg_type,
                "event": event,  # Keep original event name for reference
                **sanitized,
            }

    def _sanitize_for_transport(self, data: dict[str, Any]) -> dict[str, Any]:
        """Sanitize data for transport transmission.

        Only removes large binary data (images) to avoid huge payloads.
        All other data is passed through unchanged for full debugging.
        """

        def sanitize_value(val: Any) -> Any:
            if isinstance(val, dict):
                # Check for image source pattern
                if val.get("type") == "image" and "source" in val:
                    sanitized = dict(val)
                    sanitized["source"] = {
                        "type": "base64",
                        "data": "[image data omitted]",
                    }
                    return sanitized
                # Check for base64 image source
                if (
                    val.get("type") == "base64"
                    and "data" in val
                    and len(str(val.get("data", ""))) > 1000
                ):
                    return {"type": "base64", "data": "[image data omitted]"}
                return {k: sanitize_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [sanitize_value(item) for item in val]
            else:
                return val

        return sanitize_value(data)

    def set_show_thinking(self, show: bool) -> None:
        """Toggle thinking block display."""
        self._show_thinking = show

    def set_include_debug(self, include: bool) -> None:
        """Toggle debug event inclusion."""
        self._include_debug = include

    def set_send_function(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]],
    ) -> None:
        """Set or update the send function."""
        self._send = send_fn
