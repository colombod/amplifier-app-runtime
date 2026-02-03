"""Amplifier to ACP event mapping.

This module handles the conversion of Amplifier events to ACP session updates.
Extracted from agent.py to improve maintainability and testability.

Event Mapping:
- tool:pre -> ToolCallStart (sessionUpdate="tool_call")
- tool:post -> ToolCallUpdate with status="completed"
- tool:error -> ToolCallUpdate with status="failed"
- todo:update -> AgentPlanUpdate (sessionUpdate="plan")
- content_block:* -> update_agent_message
- thinking:* -> update_agent_thought
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from acp import (  # type: ignore[import-untyped]
    text_block,
    update_agent_message,
    update_agent_thought,
)
from acp.schema import (  # type: ignore[import-untyped]
    AgentPlanUpdate,
    PlanEntry,
    ToolCallStart,
    ToolCallUpdate,
)

from .tool_metadata import get_tool_kind, get_tool_title

if TYPE_CHECKING:
    from acp.schema import SessionUpdate  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class EventMapResult:
    """Result of mapping an Amplifier event to ACP.

    Attributes:
        update: The ACP SessionUpdate to send, or None if no update needed
        track_tool: If set, indicates a tool call should be tracked (call_id, name, args)
        clear_tool_tracking: If True, tool tracking should be cleared
    """

    update: SessionUpdate | None = None
    track_tool: tuple[str, str, dict[str, Any]] | None = None
    clear_tool_tracking: bool = False


@dataclass
class AmplifierToAcpEventMapper:
    """Maps Amplifier events to ACP session updates.

    This class encapsulates the event mapping logic, making it easier to test
    and maintain separately from the session management code.

    Usage:
        mapper = AmplifierToAcpEventMapper()
        result = mapper.map_event(event)
        if result.update:
            await conn.session_update(session_id, result.update)
    """

    # Event types that are expected but don't need mapping
    _ignored_prefixes: tuple[str, ...] = field(
        default=(
            "session:",
            "execution:",
            "llm:",
            "provider:",
            "prompt:",
            "orchestrator:",
        ),
        repr=False,
    )

    def map_event(self, event: Any) -> EventMapResult:
        """Map an Amplifier event to an ACP session update.

        Args:
            event: Amplifier event (object with type/properties or dict)

        Returns:
            EventMapResult with the ACP update (if any) and side-effect flags
        """
        # Extract event type and properties
        event_type = self._get_event_type(event)
        props = self._get_event_props(event)

        if not event_type:
            return EventMapResult()

        # Dispatch to specific handler
        handler = self._get_handler(event_type)
        if handler:
            return handler(props)

        # Log unmapped events at debug level (but not expected ones)
        if not event_type.startswith(self._ignored_prefixes):
            logger.debug(f"Unmapped event type: {event_type}")

        return EventMapResult()

    def _get_event_type(self, event: Any) -> str:
        """Extract event type from event object or dict."""
        event_type = getattr(event, "type", None)
        if event_type is None and isinstance(event, dict):
            event_type = event.get("type", "")
        return event_type or ""

    def _get_event_props(self, event: Any) -> dict[str, Any]:
        """Extract properties from event object or dict."""
        props = getattr(event, "properties", None)
        if props is None and isinstance(event, dict):
            props = event
        return props or {}

    def _get_handler(self, event_type: str) -> Any:
        """Get the handler method for an event type."""
        handlers = {
            "content_block:delta": self._handle_content_delta,
            "content_block:end": self._handle_content_end,
            "content_block:start": self._handle_content_start,
            "content": self._handle_text_content,
            "assistant_message": self._handle_text_content,
            "text": self._handle_text_content,
            "tool:pre": self._handle_tool_pre,
            "tool:post": self._handle_tool_post,
            "tool:error": self._handle_tool_error,
            "todo:update": self._handle_todo_update,
            "thinking:delta": self._handle_thinking,
            "thinking:final": self._handle_thinking,
            "thinking:start": self._handle_thinking,
        }
        return handlers.get(event_type)

    # =========================================================================
    # Content handlers
    # =========================================================================

    def _handle_content_delta(self, props: dict[str, Any]) -> EventMapResult:
        """Handle streaming text delta."""
        delta = props.get("delta", {})
        text = delta.get("text", "")
        if text:
            return EventMapResult(update=update_agent_message(text_block(text)))
        return EventMapResult()

    def _handle_content_end(self, props: dict[str, Any]) -> EventMapResult:
        """Handle final content block."""
        block = props.get("block", {})
        text = block.get("text", "")
        if text:
            return EventMapResult(update=update_agent_message(text_block(text)))
        return EventMapResult()

    def _handle_content_start(self, props: dict[str, Any]) -> EventMapResult:
        """Handle content block starting (mostly a no-op, waits for delta/end)."""
        # Content block starting - check if it's thinking
        block = props.get("block", {})
        block_type = block.get("type", "")
        if block_type == "thinking":
            # Thinking block starting - we'll get content in delta/end
            pass
        # For text blocks, wait for delta/end to send content
        return EventMapResult()

    def _handle_text_content(self, props: dict[str, Any]) -> EventMapResult:
        """Handle direct text content events."""
        text = props.get("text", "")
        if text:
            return EventMapResult(update=update_agent_message(text_block(text)))
        return EventMapResult()

    # =========================================================================
    # Tool call handlers
    # =========================================================================

    def _handle_tool_pre(self, props: dict[str, Any]) -> EventMapResult:
        """Handle tool call starting - ACP ToolCallStart."""
        tool_info = props.get("tool", {})
        tool_name = tool_info.get("name", "") if isinstance(tool_info, dict) else str(tool_info)
        tool_call_id = props.get("call_id", "")
        arguments = props.get("arguments", {})

        # Generate human-readable title and kind
        title = get_tool_title(tool_name, arguments)
        kind = get_tool_kind(tool_name)

        update = ToolCallStart(
            session_update="tool_call",
            tool_call_id=tool_call_id,
            title=title,
            kind=kind,
            status="pending",
            raw_input=arguments,
        )

        return EventMapResult(
            update=update,
            track_tool=(tool_call_id, tool_name, arguments),
        )

    def _handle_tool_post(self, props: dict[str, Any]) -> EventMapResult:
        """Handle tool call completed - ACP ToolCallUpdate."""
        update = ToolCallUpdate(
            tool_call_id=props.get("call_id", ""),
            status="completed",
            raw_output=props.get("result"),
        )
        return EventMapResult(update=update, clear_tool_tracking=True)

    def _handle_tool_error(self, props: dict[str, Any]) -> EventMapResult:
        """Handle tool call failed - ACP ToolCallUpdate with status='failed'."""
        error_info = props.get("error", "Unknown error")
        update = ToolCallUpdate(
            tool_call_id=props.get("call_id", ""),
            status="failed",
            raw_output={"error": str(error_info)},
        )
        return EventMapResult(update=update, clear_tool_tracking=True)

    # =========================================================================
    # Planning/thinking handlers
    # =========================================================================

    def _handle_todo_update(self, props: dict[str, Any]) -> EventMapResult:
        """Handle todo list update - map to ACP AgentPlanUpdate."""
        todos = props.get("todos", [])
        if not todos:
            return EventMapResult()

        entries = []
        for todo in todos:
            # Map status
            status = todo.get("status", "pending")
            if status not in ("pending", "in_progress", "completed"):
                status = "pending"

            # Map priority (default to medium if not specified)
            priority = todo.get("priority", "medium")
            if priority not in ("high", "medium", "low"):
                priority = "medium"

            # Get content - use content field or activeForm as fallback
            content = todo.get("content", "") or todo.get("activeForm", "Task")

            entries.append(
                PlanEntry(
                    content=content,
                    status=status,
                    priority=priority,
                )
            )

        update = AgentPlanUpdate(
            session_update="plan",
            entries=entries,
        )
        return EventMapResult(update=update)

    def _handle_thinking(self, props: dict[str, Any]) -> EventMapResult:
        """Handle thinking/reasoning content."""
        text = props.get("text", "") or props.get("content", "")
        if text:
            return EventMapResult(update=update_agent_thought(text_block(text)))
        return EventMapResult()
