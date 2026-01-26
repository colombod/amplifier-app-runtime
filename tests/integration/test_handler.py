"""Integration tests for CommandHandler.

Tests the CommandHandler with real protocol types and a minimal
SessionManager stub. We test at the handler level - not mocking
the protocol types, only the session infrastructure.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from amplifier_server_app.protocol import Command, CommandHandler, CommandType, Event

# =============================================================================
# Minimal Session Stubs (not mocks - real behavior, minimal implementation)
# =============================================================================


class StubManagedSession:
    """Minimal session that yields predictable events."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.status = "idle"
        self._events: list[dict] = []

    def add_event(self, event: dict) -> None:
        """Queue an event to be yielded."""
        self._events.append(event)

    async def send_prompt(self, content: str) -> AsyncIterator[dict]:
        """Yield queued events, simulating session behavior."""
        self.status = "running"

        # Yield any queued events
        for event in self._events:
            yield event

        # Default: yield a simple content response
        if not self._events:
            yield {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
            yield {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": f"Response to: {content}"},
            }
            yield {
                "type": "content_block_stop",
                "index": 0,
            }

        self.status = "idle"
        self._events = []

    async def cancel(self) -> None:
        """Cancel execution."""
        self.status = "cancelled"


class StubSessionManager:
    """Minimal session manager for testing handler logic."""

    def __init__(self):
        self.sessions: dict[str, StubManagedSession] = {}
        self._next_id = 1

    async def create_session(self, **kwargs: Any) -> StubManagedSession:
        """Create a new stub session."""
        session_id = f"sess_{self._next_id:03d}"
        self._next_id += 1
        session = StubManagedSession(session_id)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> StubManagedSession | None:
        """Get session by ID."""
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        """List all sessions."""
        return [{"session_id": s.session_id, "status": s.status} for s in self.sessions.values()]

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def session_manager() -> StubSessionManager:
    """Create a stub session manager."""
    return StubSessionManager()


@pytest.fixture
def handler(session_manager: StubSessionManager) -> CommandHandler:
    """Create a command handler with stub session manager."""
    return CommandHandler(session_manager)


# =============================================================================
# Helper to collect all events from handler
# =============================================================================


async def collect_events(handler: CommandHandler, command: Command) -> list[Event]:
    """Collect all events from handling a command."""
    events = []
    async for event in handler.handle(command):
        events.append(event)
    return events


# =============================================================================
# Tests: Ping/Capabilities (no session needed)
# =============================================================================


class TestPingCommand:
    """Test ping command handling."""

    @pytest.mark.anyio
    async def test_ping_returns_pong(self, handler: CommandHandler):
        """Ping should return pong event."""
        cmd = Command.ping()

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "pong"
        assert events[0].correlation_id == cmd.id
        assert events[0].final is True

    @pytest.mark.anyio
    async def test_ping_correlation(self, handler: CommandHandler):
        """Pong should correlate to ping command ID."""
        cmd = Command(id="ping_custom_id", cmd="ping", params={})

        events = await collect_events(handler, cmd)

        assert events[0].correlation_id == "ping_custom_id"


class TestCapabilitiesCommand:
    """Test capabilities command handling."""

    @pytest.mark.anyio
    async def test_capabilities_returns_info(self, handler: CommandHandler):
        """Capabilities should return server info."""
        cmd = Command.create(CommandType.CAPABILITIES)

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "result"
        assert events[0].final is True
        assert "version" in events[0].data
        assert "transports" in events[0].data


# =============================================================================
# Tests: Session Lifecycle
# =============================================================================


class TestSessionCreate:
    """Test session creation command."""

    @pytest.mark.anyio
    async def test_create_session_returns_id(self, handler: CommandHandler):
        """Session create should return session_id."""
        cmd = Command.session_create(bundle="test-bundle")

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "result"
        assert events[0].correlation_id == cmd.id
        assert "session_id" in events[0].data
        assert events[0].data["session_id"].startswith("sess_")

    @pytest.mark.anyio
    async def test_create_multiple_sessions(self, handler: CommandHandler):
        """Multiple creates should return unique IDs."""
        cmd1 = Command.session_create()
        cmd2 = Command.session_create()

        events1 = await collect_events(handler, cmd1)
        events2 = await collect_events(handler, cmd2)

        id1 = events1[0].data["session_id"]
        id2 = events2[0].data["session_id"]

        assert id1 != id2


class TestSessionGet:
    """Test session get command."""

    @pytest.mark.anyio
    async def test_get_existing_session(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Get should return session info for existing session."""
        # Create a session first
        session = await session_manager.create_session()

        cmd = Command.create(CommandType.SESSION_GET, {"session_id": session.session_id})
        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "result"
        assert events[0].data["session_id"] == session.session_id

    @pytest.mark.anyio
    async def test_get_nonexistent_session(self, handler: CommandHandler):
        """Get should return error for nonexistent session."""
        cmd = Command.create(CommandType.SESSION_GET, {"session_id": "nonexistent"})

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["code"] == "SESSION_NOT_FOUND"


class TestSessionList:
    """Test session list command."""

    @pytest.mark.anyio
    async def test_list_empty(self, handler: CommandHandler):
        """List should return empty when no sessions."""
        cmd = Command.create(CommandType.SESSION_LIST)

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "result"
        assert events[0].data["sessions"] == []

    @pytest.mark.anyio
    async def test_list_with_sessions(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """List should return all sessions."""
        await session_manager.create_session()
        await session_manager.create_session()

        cmd = Command.create(CommandType.SESSION_LIST)
        events = await collect_events(handler, cmd)

        assert len(events[0].data["sessions"]) == 2


class TestSessionDelete:
    """Test session delete command."""

    @pytest.mark.anyio
    async def test_delete_existing_session(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Delete should succeed for existing session."""
        session = await session_manager.create_session()

        cmd = Command.create(CommandType.SESSION_DELETE, {"session_id": session.session_id})
        events = await collect_events(handler, cmd)

        assert events[0].type == "result"
        assert events[0].data["deleted"] is True
        assert session_manager.get_session(session.session_id) is None

    @pytest.mark.anyio
    async def test_delete_nonexistent_session(self, handler: CommandHandler):
        """Delete should return error for nonexistent session."""
        cmd = Command.create(CommandType.SESSION_DELETE, {"session_id": "nonexistent"})

        events = await collect_events(handler, cmd)

        assert events[0].type == "error"
        assert events[0].data["code"] == "SESSION_NOT_FOUND"


# =============================================================================
# Tests: Prompt Execution and Streaming
# =============================================================================


class TestPromptSend:
    """Test prompt send command with streaming."""

    @pytest.mark.anyio
    async def test_prompt_streams_content(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Prompt should stream content events."""
        session = await session_manager.create_session()

        cmd = Command.prompt_send(session_id=session.session_id, content="Hello")
        events = await collect_events(handler, cmd)

        # Should have: ack, content events, result
        assert len(events) >= 2

        # First should be ack
        assert events[0].type == "ack"
        assert events[0].correlation_id == cmd.id

        # Last should be final result
        assert events[-1].final is True

        # All events should have same correlation_id
        for event in events:
            assert event.correlation_id == cmd.id

    @pytest.mark.anyio
    async def test_prompt_nonexistent_session(self, handler: CommandHandler):
        """Prompt to nonexistent session should error."""
        cmd = Command.prompt_send(session_id="nonexistent", content="Hello")

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.anyio
    async def test_prompt_missing_content(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Prompt without content should error."""
        session = await session_manager.create_session()

        cmd = Command.create(CommandType.PROMPT_SEND, {"session_id": session.session_id})
        events = await collect_events(handler, cmd)

        assert events[0].type == "error"
        assert "content" in events[0].data["error"].lower()


class TestPromptCancel:
    """Test prompt cancel command."""

    @pytest.mark.anyio
    async def test_cancel_session(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Cancel should stop session execution."""
        session = await session_manager.create_session()

        cmd = Command.create(CommandType.PROMPT_CANCEL, {"session_id": session.session_id})
        events = await collect_events(handler, cmd)

        assert events[0].type == "result"
        assert events[0].data["cancelled"] is True


# =============================================================================
# Tests: Event Correlation and Sequencing
# =============================================================================


class TestEventCorrelation:
    """Test that events properly correlate to commands."""

    @pytest.mark.anyio
    async def test_all_events_have_correlation_id(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """All events from a command should have correlation_id."""
        session = await session_manager.create_session()

        cmd = Command.prompt_send(session_id=session.session_id, content="Test")
        events = await collect_events(handler, cmd)

        for event in events:
            assert event.correlation_id == cmd.id

    @pytest.mark.anyio
    async def test_exactly_one_final_event(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Each command should produce exactly one final event."""
        session = await session_manager.create_session()

        cmd = Command.prompt_send(session_id=session.session_id, content="Test")
        events = await collect_events(handler, cmd)

        final_events = [e for e in events if e.final]
        assert len(final_events) == 1

    @pytest.mark.anyio
    async def test_final_event_is_last(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Final event should be the last event."""
        session = await session_manager.create_session()

        cmd = Command.prompt_send(session_id=session.session_id, content="Test")
        events = await collect_events(handler, cmd)

        assert events[-1].final is True
        assert all(not e.final for e in events[:-1])


class TestEventSequencing:
    """Test event sequence numbers."""

    @pytest.mark.anyio
    async def test_content_deltas_have_sequences(
        self, handler: CommandHandler, session_manager: StubSessionManager
    ):
        """Content delta events should have sequence numbers."""
        session = await session_manager.create_session()

        cmd = Command.prompt_send(session_id=session.session_id, content="Test")
        events = await collect_events(handler, cmd)

        content_events = [e for e in events if e.type.startswith("content.")]
        sequences = [e.sequence for e in content_events if e.sequence is not None]

        # Sequences should be monotonically increasing
        if sequences:
            for i in range(1, len(sequences)):
                assert sequences[i] > sequences[i - 1]


# =============================================================================
# Tests: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling in command processing."""

    @pytest.mark.anyio
    async def test_unknown_command_error(self, handler: CommandHandler):
        """Unknown command should return error."""
        cmd = Command(cmd="unknown.command", params={})

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["code"] == "UNKNOWN_COMMAND"
        assert events[0].final is True

    @pytest.mark.anyio
    async def test_missing_required_param_error(self, handler: CommandHandler):
        """Missing required param should return error."""
        # session_id is required for SESSION_GET
        cmd = Command.create(CommandType.SESSION_GET, {})

        events = await collect_events(handler, cmd)

        assert events[0].type == "error"
        assert "session_id" in events[0].data["error"].lower()

    @pytest.mark.anyio
    async def test_error_events_are_final(self, handler: CommandHandler):
        """Error events should always be final."""
        cmd = Command(cmd="unknown", params={})

        events = await collect_events(handler, cmd)

        assert events[0].is_error()
        assert events[0].final is True
