"""Command Handler - Transport-agnostic business logic.

Processes commands and yields correlated events.
All transports (HTTP, WebSocket, stdio) use this same handler.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from .commands import Command, CommandType
from .events import Event, EventType

if TYPE_CHECKING:
    from ..session import SessionManager

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles protocol commands and yields correlated events.

    This is the central business logic layer. All transports delegate
    command processing here, ensuring consistent behavior regardless
    of how commands arrive (HTTP, WebSocket, stdio, etc.).

    Usage:
        handler = CommandHandler(session_manager)

        # Process a command
        async for event in handler.handle(command):
            transport.send(event)

    Correlation:
        Every yielded event has `correlation_id` set to the command's `id`,
        enabling clients to match responses with requests.

    Streaming:
        Commands like `prompt.send` yield multiple events with increasing
        `sequence` numbers. The final event has `final=True`.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        """Initialize handler with session manager.

        Args:
            session_manager: Manager for session CRUD and execution
        """
        self._sessions = session_manager

    async def handle(self, command: Command) -> AsyncIterator[Event]:
        """Process a command and yield correlated events.

        Args:
            command: The command to process

        Yields:
            Events correlated to the command
        """
        logger.debug(f"Handling command: {command.cmd} (id={command.id})")

        try:
            # Dispatch to handler method
            match command.cmd:
                # Session lifecycle
                case CommandType.SESSION_CREATE.value:
                    async for event in self._session_create(command):
                        yield event

                case CommandType.SESSION_GET.value:
                    async for event in self._session_get(command):
                        yield event

                case CommandType.SESSION_LIST.value:
                    async for event in self._session_list(command):
                        yield event

                case CommandType.SESSION_DELETE.value:
                    async for event in self._session_delete(command):
                        yield event

                # Execution
                case CommandType.PROMPT_SEND.value:
                    async for event in self._prompt_send(command):
                        yield event

                case CommandType.PROMPT_CANCEL.value:
                    async for event in self._prompt_cancel(command):
                        yield event

                # Approval
                case CommandType.APPROVAL_RESPOND.value:
                    async for event in self._approval_respond(command):
                        yield event

                # Server
                case CommandType.PING.value:
                    yield Event.pong(command.id)

                case CommandType.CAPABILITIES.value:
                    async for event in self._capabilities(command):
                        yield event

                case _:
                    yield Event.error(
                        command.id,
                        error=f"Unknown command: {command.cmd}",
                        code="UNKNOWN_COMMAND",
                    )

        except Exception as e:
            logger.exception(f"Error handling command {command.id}: {e}")
            yield Event.error(
                command.id,
                error=str(e),
                code="HANDLER_ERROR",
            )

    # =========================================================================
    # Session Commands
    # =========================================================================

    async def _session_create(self, command: Command) -> AsyncIterator[Event]:
        """Handle session.create command."""
        from ..session import SessionConfig

        # Extract config from params
        config = SessionConfig(
            bundle=command.get_param("bundle"),
            provider=command.get_param("provider"),
            model=command.get_param("model"),
            working_directory=command.get_param("working_directory"),
        )

        # Create and initialize session
        session = await self._sessions.create(config=config)
        await session.initialize()

        # Return session info
        yield Event.result(
            command.id,
            data={
                "session_id": session.session_id,
                "state": session.metadata.state.value,
                "bundle": session.metadata.bundle_name,
            },
        )

    async def _session_get(self, command: Command) -> AsyncIterator[Event]:
        """Handle session.get command."""
        session_id = command.require_param("session_id")
        session = await self._sessions.get(session_id)

        if not session:
            yield Event.error(
                command.id,
                error=f"Session not found: {session_id}",
                code="SESSION_NOT_FOUND",
            )
            return

        yield Event.result(command.id, data=session.to_dict())

    async def _session_list(self, command: Command) -> AsyncIterator[Event]:
        """Handle session.list command."""
        sessions = await self._sessions.list_sessions()
        yield Event.result(command.id, data={"sessions": sessions})

    async def _session_delete(self, command: Command) -> AsyncIterator[Event]:
        """Handle session.delete command."""
        session_id = command.require_param("session_id")
        deleted = await self._sessions.delete(session_id)

        if not deleted:
            yield Event.error(
                command.id,
                error=f"Session not found: {session_id}",
                code="SESSION_NOT_FOUND",
            )
            return

        yield Event.result(command.id, data={"deleted": True, "session_id": session_id})

    # =========================================================================
    # Execution Commands
    # =========================================================================

    async def _prompt_send(self, command: Command) -> AsyncIterator[Event]:
        """Handle prompt.send command.

        This is a streaming command - yields multiple events with
        increasing sequence numbers, all correlated to the command.
        """
        session_id = command.require_param("session_id")
        content = command.require_param("content")
        _stream = command.get_param("stream", True)  # Reserved for future non-streaming mode

        session = await self._sessions.get(session_id)
        if not session:
            yield Event.error(
                command.id,
                error=f"Session not found: {session_id}",
                code="SESSION_NOT_FOUND",
            )
            return

        # Acknowledge receipt
        yield Event.ack(command.id, message="Processing prompt")

        # Execute and stream events
        sequence = 0
        try:
            async for session_event in session.execute(content):
                # Map session events to protocol events with correlation
                protocol_event = self._map_session_event(
                    session_event,
                    command.id,
                    sequence,
                )
                if protocol_event:
                    yield protocol_event
                    sequence += 1

            # Final completion event
            yield Event.create(
                EventType.RESULT,
                data={
                    "session_id": session_id,
                    "state": session.metadata.state.value,
                    "turn": session.metadata.turn_count,
                },
                correlation_id=command.id,
                sequence=sequence,
                final=True,
            )

        except Exception as e:
            yield Event.error(
                command.id,
                error=str(e),
                code="EXECUTION_ERROR",
            )

    async def _prompt_cancel(self, command: Command) -> AsyncIterator[Event]:
        """Handle prompt.cancel command."""
        session_id = command.require_param("session_id")
        session = await self._sessions.get(session_id)

        if not session:
            yield Event.error(
                command.id,
                error=f"Session not found: {session_id}",
                code="SESSION_NOT_FOUND",
            )
            return

        await session.cancel()

        yield Event.result(
            command.id,
            data={
                "cancelled": True,
                "session_id": session_id,
                "state": session.metadata.state.value,
            },
        )

    # =========================================================================
    # Approval Commands
    # =========================================================================

    async def _approval_respond(self, command: Command) -> AsyncIterator[Event]:
        """Handle approval.respond command."""
        session_id = command.require_param("session_id")
        request_id = command.require_param("request_id")
        choice = command.require_param("choice")

        session = await self._sessions.get(session_id)
        if not session:
            yield Event.error(
                command.id,
                error=f"Session not found: {session_id}",
                code="SESSION_NOT_FOUND",
            )
            return

        handled = await session.handle_approval(request_id, choice)

        if not handled:
            yield Event.error(
                command.id,
                error=f"Approval request not found: {request_id}",
                code="APPROVAL_NOT_FOUND",
            )
            return

        yield Event.result(
            command.id,
            data={
                "resolved": True,
                "request_id": request_id,
                "choice": choice,
            },
        )

    # =========================================================================
    # Server Commands
    # =========================================================================

    async def _capabilities(self, command: Command) -> AsyncIterator[Event]:
        """Handle capabilities command."""
        yield Event.result(
            command.id,
            data={
                "version": "0.1.0",
                "protocol_version": "1.0",
                "commands": [cmd.value for cmd in CommandType],
                "events": [evt.value for evt in EventType],
                "features": {
                    "streaming": True,
                    "approval": True,
                    "spawning": True,
                },
            },
        )

    # =========================================================================
    # Event Mapping
    # =========================================================================

    def _map_session_event(
        self,
        session_event: Any,
        correlation_id: str,
        sequence: int,
    ) -> Event | None:
        """Map a session event to a protocol event.

        Args:
            session_event: Event from ManagedSession.execute()
            correlation_id: Command ID for correlation
            sequence: Current sequence number

        Returns:
            Protocol Event or None if event should be skipped
        """
        # Session events have .type and .properties
        event_type = session_event.type
        props = session_event.properties

        match event_type:
            case "content_block:start":
                return Event.create(
                    EventType.CONTENT_START,
                    data={
                        "block_type": props.get("block_type", "text"),
                        "block_index": props.get("index", 0),
                    },
                    correlation_id=correlation_id,
                    sequence=sequence,
                )

            case "content_block:delta":
                delta = props.get("delta", {})
                delta_text = delta.get("text", "") if isinstance(delta, dict) else str(delta)
                return Event.content_delta(
                    correlation_id=correlation_id,
                    delta=delta_text,
                    sequence=sequence,
                    block_index=props.get("index", 0),
                )

            case "content_block:end":
                block = props.get("block", {})
                content = block.get("text", "") if isinstance(block, dict) else str(block)
                return Event.create(
                    EventType.CONTENT_END,
                    data={
                        "content": content,
                        "block_index": props.get("index", 0),
                    },
                    correlation_id=correlation_id,
                    sequence=sequence,
                )

            case "tool:pre":
                return Event.tool_call(
                    correlation_id=correlation_id,
                    tool_name=props.get("tool_name", "unknown"),
                    tool_call_id=props.get("tool_call_id", ""),
                    arguments=props.get("tool_input", {}),
                    sequence=sequence,
                )

            case "tool:post":
                result = props.get("result", {})
                output = result.get("output", "") if isinstance(result, dict) else str(result)
                return Event.tool_result(
                    correlation_id=correlation_id,
                    tool_call_id=props.get("tool_call_id", ""),
                    output=output,
                    sequence=sequence,
                )

            case "approval:required":
                return Event.approval_required(
                    correlation_id=correlation_id,
                    request_id=props.get("request_id", ""),
                    prompt=props.get("prompt", ""),
                    options=props.get("options", ["yes", "no"]),
                    timeout=props.get("timeout", 30.0),
                    sequence=sequence,
                )

            case "prompt:submit" | "prompt:complete":
                # Skip these - handled at higher level
                return None

            case "error":
                return Event.error(
                    correlation_id,
                    error=props.get("error", "Unknown error"),
                    code=props.get("error_type", "UNKNOWN"),
                )

            case _:
                # Pass through other events with raw data
                return Event.create(
                    event_type.replace(":", "."),
                    data=props,
                    correlation_id=correlation_id,
                    sequence=sequence,
                )
