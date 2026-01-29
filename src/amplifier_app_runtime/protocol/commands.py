"""Command definitions for the protocol layer.

Commands are requests from clients that expect responses.
Each command has a unique ID for correlation with response events.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CommandType(str, Enum):
    """All supported command types."""

    # Session lifecycle
    SESSION_CREATE = "session.create"
    SESSION_GET = "session.get"
    SESSION_LIST = "session.list"
    SESSION_DELETE = "session.delete"

    # Execution
    PROMPT_SEND = "prompt.send"
    PROMPT_CANCEL = "prompt.cancel"

    # Approval
    APPROVAL_RESPOND = "approval.respond"

    # Server
    PING = "ping"
    CAPABILITIES = "capabilities"


class Command(BaseModel):
    """A command from client to server.

    Commands are the request side of the protocol. Each command:
    - Has a unique `id` for correlation with response events
    - Has a `cmd` identifying the operation
    - Has optional `params` for operation arguments

    Example:
        {
            "id": "cmd_abc123",
            "cmd": "session.create",
            "params": {"bundle": "amplifier-dev"}
        }

    The server responds with Events that have `correlation_id` = command's `id`.
    """

    id: str = Field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:12]}")
    cmd: str
    params: dict[str, Any] = Field(default_factory=dict)

    # Optional metadata
    timestamp: str | None = None  # ISO8601, set by client or server

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get a parameter with optional default."""
        return self.params.get(key, default)

    def require_param(self, key: str) -> Any:
        """Get a required parameter, raise if missing."""
        if key not in self.params:
            raise ValueError(f"Missing required parameter: {key}")
        return self.params[key]

    @classmethod
    def create(
        cls,
        cmd: str | CommandType,
        params: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> Command:
        """Factory method for creating commands."""
        return cls(
            id=command_id or f"cmd_{uuid.uuid4().hex[:12]}",
            cmd=cmd.value if isinstance(cmd, CommandType) else cmd,
            params=params or {},
        )

    # Convenience factories for common commands
    @classmethod
    def session_create(
        cls,
        bundle: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        working_directory: str | None = None,
    ) -> Command:
        """Create a session.create command."""
        params = {}
        if bundle:
            params["bundle"] = bundle
        if provider:
            params["provider"] = provider
        if model:
            params["model"] = model
        if working_directory:
            params["working_directory"] = working_directory
        return cls.create(CommandType.SESSION_CREATE, params)

    @classmethod
    def prompt_send(
        cls,
        session_id: str,
        content: str,
        stream: bool = True,
    ) -> Command:
        """Create a prompt.send command."""
        return cls.create(
            CommandType.PROMPT_SEND,
            {
                "session_id": session_id,
                "content": content,
                "stream": stream,
            },
        )

    @classmethod
    def approval_respond(
        cls,
        session_id: str,
        request_id: str,
        choice: str,
    ) -> Command:
        """Create an approval.respond command."""
        return cls.create(
            CommandType.APPROVAL_RESPOND,
            {
                "session_id": session_id,
                "request_id": request_id,
                "choice": choice,
            },
        )

    @classmethod
    def ping(cls) -> Command:
        """Create a ping command."""
        return cls.create(CommandType.PING)
