"""SDK type definitions."""

from typing import Any

from pydantic import BaseModel


class SessionInfo(BaseModel):
    """Session information."""

    id: str
    title: str
    created_at: str
    updated_at: str


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
