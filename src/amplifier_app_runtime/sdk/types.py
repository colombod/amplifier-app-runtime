"""SDK type definitions."""

from typing import Any

from pydantic import BaseModel


class SessionInfo(BaseModel):
    """Session information returned from session.create and session.get."""

    session_id: str
    state: str | None = None
    bundle: str | None = None
    # Optional fields for detailed session info
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    turn_count: int = 0
    cwd: str | None = None


class MessagePart(BaseModel):
    """A part of a message (text, tool call, etc.)."""

    type: str
    text: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None


class MessageInfo(BaseModel):
    """Message information."""

    id: str
    session_id: str
    role: str
    parts: list[MessagePart]
    created_at: str
