"""Amplifier Event Taxonomy.

Defines all canonical events that flow through the system.
Aligned with amplifier-core's event system for full compatibility.

Events are categorized by domain:
- session:*     - Session lifecycle
- prompt:*      - User prompt handling
- content_block:* - Streaming content
- thinking:*    - Model thinking/reasoning
- tool:*        - Tool execution
- provider:*    - LLM provider interactions
- llm:*         - Low-level LLM request/response
- approval:*    - User approval flow
- context:*     - Context management
- cancel:*      - Cancellation handling
- user:*        - User notifications
- plan:*        - Planning events
- artifact:*    - File/artifact operations
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventCategory(str, Enum):
    """Event categories for filtering and routing."""

    SESSION = "session"
    PROMPT = "prompt"
    CONTENT = "content_block"
    THINKING = "thinking"
    TOOL = "tool"
    PROVIDER = "provider"
    LLM = "llm"
    APPROVAL = "approval"
    CONTEXT = "context"
    CANCEL = "cancel"
    USER = "user"
    PLAN = "plan"
    ARTIFACT = "artifact"
    TRANSPORT = "transport"


# ============================================================================
# Canonical Event Names (aligned with amplifier-core)
# ============================================================================

# Session lifecycle
SESSION_START = "session:start"
SESSION_END = "session:end"
SESSION_FORK = "session:fork"
SESSION_RESUME = "session:resume"

# Prompt handling
PROMPT_SUBMIT = "prompt:submit"
PROMPT_COMPLETE = "prompt:complete"

# Content streaming (from LLM response)
CONTENT_BLOCK_START = "content_block:start"
CONTENT_BLOCK_DELTA = "content_block:delta"
CONTENT_BLOCK_END = "content_block:end"

# Thinking/reasoning (extended thinking, chain-of-thought)
THINKING_DELTA = "thinking:delta"
THINKING_FINAL = "thinking:final"

# Tool execution
TOOL_PRE = "tool:pre"
TOOL_POST = "tool:post"
TOOL_ERROR = "tool:error"

# Provider (high-level LLM interaction)
PROVIDER_REQUEST = "provider:request"
PROVIDER_RESPONSE = "provider:response"
PROVIDER_ERROR = "provider:error"

# LLM (low-level, for debugging)
LLM_REQUEST = "llm:request"
LLM_REQUEST_DEBUG = "llm:request:debug"
LLM_REQUEST_RAW = "llm:request:raw"
LLM_RESPONSE = "llm:response"
LLM_RESPONSE_DEBUG = "llm:response:debug"
LLM_RESPONSE_RAW = "llm:response:raw"

# Approval flow
APPROVAL_REQUIRED = "approval:required"
APPROVAL_GRANTED = "approval:granted"
APPROVAL_DENIED = "approval:denied"

# Context management
CONTEXT_COMPACTION = "context:compaction"

# Cancellation
CANCEL_REQUESTED = "cancel:requested"
CANCEL_COMPLETED = "cancel:completed"

# User notifications
USER_NOTIFICATION = "user:notification"

# Planning
PLAN_START = "plan:start"
PLAN_END = "plan:end"

# Artifacts
ARTIFACT_WRITE = "artifact:write"
ARTIFACT_READ = "artifact:read"

# Transport-specific (internal)
TRANSPORT_ERROR = "transport:error"
TRANSPORT_CONNECTED = "transport:connected"
TRANSPORT_DISCONNECTED = "transport:disconnected"


# Complete list of all events (for hook registration)
ALL_EVENTS: list[str] = [
    # Session
    SESSION_START,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    # Prompt
    PROMPT_SUBMIT,
    PROMPT_COMPLETE,
    # Content
    CONTENT_BLOCK_START,
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    # Thinking
    THINKING_DELTA,
    THINKING_FINAL,
    # Tool
    TOOL_PRE,
    TOOL_POST,
    TOOL_ERROR,
    # Provider
    PROVIDER_REQUEST,
    PROVIDER_RESPONSE,
    PROVIDER_ERROR,
    # LLM (debug)
    LLM_REQUEST,
    LLM_REQUEST_DEBUG,
    LLM_REQUEST_RAW,
    LLM_RESPONSE,
    LLM_RESPONSE_DEBUG,
    LLM_RESPONSE_RAW,
    # Approval
    APPROVAL_REQUIRED,
    APPROVAL_GRANTED,
    APPROVAL_DENIED,
    # Context
    CONTEXT_COMPACTION,
    # Cancel
    CANCEL_REQUESTED,
    CANCEL_COMPLETED,
    # User
    USER_NOTIFICATION,
    # Plan
    PLAN_START,
    PLAN_END,
    # Artifact
    ARTIFACT_WRITE,
    ARTIFACT_READ,
]

# Events safe to stream to UI (excludes debug/raw events)
UI_EVENTS: list[str] = [
    SESSION_START,
    SESSION_END,
    SESSION_FORK,
    PROMPT_COMPLETE,
    CONTENT_BLOCK_START,
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    THINKING_DELTA,
    THINKING_FINAL,
    TOOL_PRE,
    TOOL_POST,
    TOOL_ERROR,
    PROVIDER_REQUEST,
    PROVIDER_RESPONSE,
    APPROVAL_REQUIRED,
    APPROVAL_GRANTED,
    APPROVAL_DENIED,
    CONTEXT_COMPACTION,
    CANCEL_REQUESTED,
    CANCEL_COMPLETED,
    USER_NOTIFICATION,
]


# ============================================================================
# Event Data Models
# ============================================================================


class AmplifierEvent(BaseModel):
    """Base event structure."""

    type: str
    session_id: str | None = None
    timestamp: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    # Sub-session context (for nested agent delegation)
    child_session_id: str | None = None
    parent_tool_call_id: str | None = None
    nesting_depth: int = 0


class ContentBlockEvent(AmplifierEvent):
    """Content streaming event."""

    block_type: str = "text"  # text, thinking, tool_use
    block_index: int = 0
    delta: str | None = None  # For delta events
    content: str | None = None  # For end events


class ToolEvent(AmplifierEvent):
    """Tool execution event."""

    tool_name: str
    tool_call_id: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None


class ApprovalEvent(AmplifierEvent):
    """Approval request/response event."""

    request_id: str
    prompt: str | None = None
    options: list[str] = Field(default_factory=list)
    timeout: float = 30.0
    default: str | None = None
    choice: str | None = None  # For response


class ProviderEvent(AmplifierEvent):
    """Provider interaction event."""

    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


# ============================================================================
# Event Utilities
# ============================================================================


def get_event_category(event_type: str) -> EventCategory | None:
    """Get the category for an event type."""
    if ":" not in event_type:
        return None

    prefix = event_type.split(":")[0]
    try:
        return EventCategory(prefix)
    except ValueError:
        return None


def is_debug_event(event_type: str) -> bool:
    """Check if event is a debug/raw event (high volume, may contain sensitive data)."""
    return ":debug" in event_type or ":raw" in event_type


def is_ui_safe(event_type: str) -> bool:
    """Check if event is safe to stream to UI."""
    return event_type in UI_EVENTS


def filter_events(
    events: list[str],
    categories: list[EventCategory] | None = None,
    exclude_debug: bool = True,
) -> list[str]:
    """Filter events by category and debug status."""
    result = events

    if exclude_debug:
        result = [e for e in result if not is_debug_event(e)]

    if categories:
        category_prefixes = [c.value for c in categories]
        result = [e for e in result if any(e.startswith(p + ":") for p in category_prefixes)]

    return result
