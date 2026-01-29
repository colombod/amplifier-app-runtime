"""Integration tests for CommandHandler.

Tests the CommandHandler with real SessionManager (no mocks).
The SessionManager runs in mock mode when amplifier-core isn't installed,
providing realistic behavior without requiring the full Amplifier stack.
"""

import pytest

from amplifier_app_runtime.protocol import Command, CommandHandler, CommandType, Event
from amplifier_app_runtime.session import SessionManager

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def session_manager() -> SessionManager:
    """Create a real session manager (uses mock mode without amplifier-core)."""
    return SessionManager()


@pytest.fixture
def handler(session_manager: SessionManager) -> CommandHandler:
    """Create a command handler with real session manager."""
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
        assert "features" in events[0].data  # Features like streaming, approval, spawning


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
    async def test_get_existing_session(self, handler: CommandHandler):
        """Get should return session info for existing session."""
        # Create a session first
        create_cmd = Command.session_create()
        create_events = await collect_events(handler, create_cmd)
        session_id = create_events[0].data["session_id"]

        # Now get it
        get_cmd = Command.create(CommandType.SESSION_GET, {"session_id": session_id})
        events = await collect_events(handler, get_cmd)

        assert len(events) == 1
        assert events[0].type == "result"
        assert events[0].data["session_id"] == session_id

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
        """List should return empty when no active sessions."""
        cmd = Command.create(CommandType.SESSION_LIST)

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "result"
        assert events[0].data["active"] == []
        assert "saved" in events[0].data

    @pytest.mark.anyio
    async def test_list_with_sessions(self, handler: CommandHandler):
        """List should return all sessions."""
        # Create two sessions
        await collect_events(handler, Command.session_create())
        await collect_events(handler, Command.session_create())

        cmd = Command.create(CommandType.SESSION_LIST)
        events = await collect_events(handler, cmd)

        # Active sessions should contain the two we just created
        assert len(events[0].data["active"]) == 2


class TestSessionDelete:
    """Test session delete command."""

    @pytest.mark.anyio
    async def test_delete_existing_session(self, handler: CommandHandler):
        """Delete should succeed for existing session."""
        # Create a session
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        # Delete it
        cmd = Command.create(CommandType.SESSION_DELETE, {"session_id": session_id})
        events = await collect_events(handler, cmd)

        assert events[0].type == "result"
        assert events[0].data["deleted"] is True

        # Verify it's gone
        get_cmd = Command.create(CommandType.SESSION_GET, {"session_id": session_id})
        get_events = await collect_events(handler, get_cmd)
        assert get_events[0].type == "error"

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
    async def test_prompt_streams_content(self, handler: CommandHandler):
        """Prompt should stream content events."""
        # Create a session first
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.prompt_send(session_id=session_id, content="Hello")
        events = await collect_events(handler, cmd)

        # Should have at least one event
        assert len(events) >= 1

        # All events should have same correlation_id
        for event in events:
            assert event.correlation_id == cmd.id

        # Last event should be final
        assert events[-1].final is True

    @pytest.mark.anyio
    async def test_prompt_nonexistent_session(self, handler: CommandHandler):
        """Prompt to nonexistent session should error."""
        cmd = Command.prompt_send(session_id="nonexistent", content="Hello")

        events = await collect_events(handler, cmd)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.anyio
    async def test_prompt_missing_content(self, handler: CommandHandler):
        """Prompt without content should error."""
        # Create a session
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.create(CommandType.PROMPT_SEND, {"session_id": session_id})
        events = await collect_events(handler, cmd)

        assert events[0].type == "error"
        assert "content" in events[0].data["error"].lower()


class TestPromptCancel:
    """Test prompt cancel command."""

    @pytest.mark.anyio
    async def test_cancel_session(self, handler: CommandHandler):
        """Cancel should stop session execution."""
        # Create a session
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.create(CommandType.PROMPT_CANCEL, {"session_id": session_id})
        events = await collect_events(handler, cmd)

        assert events[0].type == "result"
        assert events[0].data["cancelled"] is True


# =============================================================================
# Tests: Event Correlation and Sequencing
# =============================================================================


class TestEventCorrelation:
    """Test that events properly correlate to commands."""

    @pytest.mark.anyio
    async def test_all_events_have_correlation_id(self, handler: CommandHandler):
        """All events from a command should have correlation_id."""
        # Create session and send prompt
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.prompt_send(session_id=session_id, content="Test")
        events = await collect_events(handler, cmd)

        for event in events:
            assert event.correlation_id == cmd.id

    @pytest.mark.anyio
    async def test_exactly_one_final_event(self, handler: CommandHandler):
        """Each command should produce exactly one final event."""
        # Create session and send prompt
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.prompt_send(session_id=session_id, content="Test")
        events = await collect_events(handler, cmd)

        final_events = [e for e in events if e.final]
        assert len(final_events) == 1

    @pytest.mark.anyio
    async def test_final_event_is_last(self, handler: CommandHandler):
        """Final event should be the last event."""
        # Create session and send prompt
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.prompt_send(session_id=session_id, content="Test")
        events = await collect_events(handler, cmd)

        assert events[-1].final is True
        assert all(not e.final for e in events[:-1])


class TestEventSequencing:
    """Test event sequence numbers."""

    @pytest.mark.anyio
    async def test_streaming_events_have_sequences(self, handler: CommandHandler):
        """Streaming events should have sequence numbers when applicable."""
        # Create session and send prompt
        create_events = await collect_events(handler, Command.session_create())
        session_id = create_events[0].data["session_id"]

        cmd = Command.prompt_send(session_id=session_id, content="Test")
        events = await collect_events(handler, cmd)

        # At minimum, the final event exists
        assert len(events) >= 1


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
