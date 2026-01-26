"""Event type definitions.

All events that flow through the system are defined here.
Provides type-safe event publishing and subscription.
"""

from pydantic import BaseModel

from .bus import Bus

# =============================================================================
# Server Lifecycle Events
# =============================================================================


class ServerConnectedProps(BaseModel):
    """Server connection established."""

    pass


class ServerHeartbeatProps(BaseModel):
    """Heartbeat to keep connection alive."""

    pass


ServerConnected = Bus.define("server.connected", ServerConnectedProps)
ServerHeartbeat = Bus.define("server.heartbeat", ServerHeartbeatProps)


# =============================================================================
# Session Events
# =============================================================================


class SessionCreatedProps(BaseModel):
    """A new session was created."""

    session_id: str
    title: str


class SessionUpdatedProps(BaseModel):
    """Session metadata was updated."""

    session_id: str
    title: str | None = None


class SessionDeletedProps(BaseModel):
    """Session was deleted."""

    session_id: str


class SessionIdleProps(BaseModel):
    """Session finished processing and is idle."""

    session_id: str


class SessionErrorProps(BaseModel):
    """An error occurred in the session."""

    session_id: str
    error: dict


SessionCreated = Bus.define("session.created", SessionCreatedProps)
SessionUpdated = Bus.define("session.updated", SessionUpdatedProps)
SessionDeleted = Bus.define("session.deleted", SessionDeletedProps)
SessionIdle = Bus.define("session.idle", SessionIdleProps)
SessionError = Bus.define("session.error", SessionErrorProps)


# =============================================================================
# Message Events
# =============================================================================


class MessageCreatedProps(BaseModel):
    """A new message was created."""

    session_id: str
    message_id: str
    role: str  # "user" | "assistant"


class MessagePartUpdatedProps(BaseModel):
    """A message part was updated (streaming)."""

    session_id: str
    message_id: str
    part: dict  # The part data (text, tool call, etc.)


MessageCreated = Bus.define("message.created", MessageCreatedProps)
MessagePartUpdated = Bus.define("message.part.updated", MessagePartUpdatedProps)


# =============================================================================
# Tool Events
# =============================================================================


class ToolStartedProps(BaseModel):
    """A tool execution started."""

    session_id: str
    tool_name: str
    tool_call_id: str
    input: dict


class ToolCompletedProps(BaseModel):
    """A tool execution completed."""

    session_id: str
    tool_name: str
    tool_call_id: str
    output: str | None = None
    error: str | None = None


ToolStarted = Bus.define("tool.started", ToolStartedProps)
ToolCompleted = Bus.define("tool.completed", ToolCompletedProps)


# =============================================================================
# Approval Events
# =============================================================================


class ApprovalRequestedProps(BaseModel):
    """An approval was requested."""

    session_id: str
    approval_id: str
    tool_name: str
    description: str
    input: dict


class ApprovalResolvedProps(BaseModel):
    """An approval was resolved."""

    session_id: str
    approval_id: str
    approved: bool
    reason: str | None = None


ApprovalRequested = Bus.define("approval.requested", ApprovalRequestedProps)
ApprovalResolved = Bus.define("approval.resolved", ApprovalResolvedProps)
