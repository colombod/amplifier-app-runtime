"""Type protocols for ACP integration.

This module defines Protocol classes that specify the interfaces expected
by ACP components, replacing heavy use of `Any` type annotations.

Using protocols improves:
- Type safety (static type checking catches interface mismatches)
- IDE support (autocomplete, go-to-definition)
- Documentation (explicit interface requirements)
- Testability (easy to create compliant mocks)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from acp.schema import SessionUpdate  # type: ignore[import-untyped]


@runtime_checkable
class AmplifierSessionProtocol(Protocol):
    """Minimal interface required by ACP components for Amplifier sessions.

    This protocol defines what ACP components (slash commands, tools, etc.)
    need from an Amplifier session, without coupling to the full implementation.
    """

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        ...

    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools in this session."""
        ...

    async def execute(self, prompt: str) -> AsyncIterator[Any]:
        """Execute a prompt and yield events."""
        ...

    async def cancel(self) -> None:
        """Cancel the current execution."""
        ...


@runtime_checkable
class ManagedSessionProtocol(Protocol):
    """Protocol for ManagedSession wrapper.

    Used by ACP agent to interact with sessions without tight coupling
    to the full ManagedSession implementation.
    """

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        ...

    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools."""
        ...

    async def execute(self, prompt: str) -> AsyncIterator[Any]:
        """Execute prompt and yield events."""
        ...


@runtime_checkable
class ACPConnectionProtocol(Protocol):
    """Protocol for ACP client connections.

    Defines the interface used to send updates back to the ACP client.
    """

    async def session_update(self, session_id: str, update: SessionUpdate) -> None:
        """Send a session update to the client.

        Args:
            session_id: The session to update
            update: The ACP session update to send
        """
        ...

    async def request_approval(
        self,
        session_id: str,
        tool_call_id: str,
        title: str,
        description: str,
        options: list[str],
    ) -> str:
        """Request approval from the client.

        Args:
            session_id: The session requesting approval
            tool_call_id: ID of the tool call needing approval
            title: Title for the approval dialog
            description: Description of what needs approval
            options: List of option strings to present

        Returns:
            The selected option string
        """
        ...


@runtime_checkable
class ToolTrackerProtocol(Protocol):
    """Protocol for tracking tool calls.

    Used to maintain context about the current tool call for approval requests.
    """

    def track(self, call_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        """Track a new tool call.

        Args:
            call_id: Unique ID for the tool call
            tool_name: Name of the tool being called
            arguments: Arguments passed to the tool
        """
        ...

    def get_current(self) -> tuple[str, str, dict[str, Any]] | None:
        """Get the current tracked tool call.

        Returns:
            Tuple of (call_id, tool_name, arguments) or None if no active call
        """
        ...

    def clear(self) -> None:
        """Clear the current tracked tool call."""
        ...


@runtime_checkable
class SlashCommandHandlerProtocol(Protocol):
    """Protocol for slash command handlers.

    Defines the interface for handling slash commands in ACP sessions.
    """

    async def execute(self, parsed: Any) -> Any:
        """Execute a parsed slash command.

        Args:
            parsed: ParsedCommand from parse_slash_command()

        Returns:
            SlashCommandResult with the command outcome
        """
        ...


@runtime_checkable
class EventMapperProtocol(Protocol):
    """Protocol for event mappers.

    Defines the interface for mapping Amplifier events to ACP updates.
    """

    def map_event(self, event: Any) -> Any:
        """Map an Amplifier event to ACP format.

        Args:
            event: Amplifier event object

        Returns:
            EventMapResult with ACP update (if any)
        """
        ...


@runtime_checkable
class ContentConverterProtocol(Protocol):
    """Protocol for content converters.

    Defines the interface for converting ACP content blocks to Amplifier format.
    """

    def convert(self, blocks: list[Any]) -> Any:
        """Convert ACP content blocks to Amplifier format.

        Args:
            blocks: List of ACP content blocks

        Returns:
            ConversionResult with converted blocks and metadata
        """
        ...
