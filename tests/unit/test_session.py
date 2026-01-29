"""Tests for session module - SessionState, SessionMetadata, ManagedSession, SessionManager."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amplifier_app_runtime.session import (
    ManagedSession,
    SessionConfig,
    SessionManager,
    SessionMetadata,
    SessionState,
)
from amplifier_app_runtime.session_store import SessionStore
from amplifier_app_runtime.transport.base import Event

# =============================================================================
# SessionState Tests
# =============================================================================


class TestSessionState:
    """Tests for SessionState enum."""

    def test_all_states_exist(self) -> None:
        """All expected states are defined."""
        expected = {
            "created",
            "ready",
            "running",
            "waiting_approval",
            "paused",
            "completed",
            "error",
            "cancelled",
        }
        actual = {s.value for s in SessionState}
        assert actual == expected

    def test_state_is_string_enum(self) -> None:
        """States can be used as strings."""
        assert SessionState.CREATED == "created"
        assert SessionState.READY == "ready"
        assert SessionState.RUNNING.value == "running"

    def test_state_from_value(self) -> None:
        """Can create state from string value."""
        assert SessionState("created") == SessionState.CREATED
        assert SessionState("running") == SessionState.RUNNING

    def test_invalid_state_raises(self) -> None:
        """Invalid state value raises ValueError."""
        with pytest.raises(ValueError):
            SessionState("invalid")


# =============================================================================
# SessionMetadata Tests
# =============================================================================


class TestSessionMetadata:
    """Tests for SessionMetadata dataclass."""

    def test_minimal_creation(self) -> None:
        """Can create with just session_id."""
        meta = SessionMetadata(session_id="test123")
        assert meta.session_id == "test123"
        assert meta.state == SessionState.CREATED
        assert meta.bundle_name is None
        assert meta.turn_count == 0
        assert meta.parent_session_id is None
        assert meta.error is None

    def test_defaults_have_timestamps(self) -> None:
        """Default timestamps are set."""
        before = datetime.now(UTC)
        meta = SessionMetadata(session_id="test123")
        after = datetime.now(UTC)

        assert before <= meta.created_at <= after
        assert before <= meta.updated_at <= after

    def test_defaults_have_cwd(self) -> None:
        """Default cwd is current working directory."""
        meta = SessionMetadata(session_id="test123")
        assert meta.cwd == str(Path.cwd())

    def test_full_creation(self) -> None:
        """Can create with all fields."""
        now = datetime.now(UTC)
        meta = SessionMetadata(
            session_id="test123",
            state=SessionState.RUNNING,
            bundle_name="my-bundle",
            created_at=now,
            updated_at=now,
            turn_count=5,
            cwd="/home/user/project",
            parent_session_id="parent456",
            error="something went wrong",
        )
        assert meta.session_id == "test123"
        assert meta.state == SessionState.RUNNING
        assert meta.bundle_name == "my-bundle"
        assert meta.turn_count == 5
        assert meta.cwd == "/home/user/project"
        assert meta.parent_session_id == "parent456"
        assert meta.error == "something went wrong"


# =============================================================================
# SessionConfig Tests
# =============================================================================


class TestSessionConfig:
    """Tests for SessionConfig dataclass."""

    def test_defaults(self) -> None:
        """Default values are sensible."""
        config = SessionConfig()
        assert config.bundle is None
        assert config.provider is None
        assert config.model is None
        assert config.max_turns == 100
        assert config.timeout == 300.0
        assert config.working_directory is None
        assert config.environment == {}

    def test_full_creation(self) -> None:
        """Can create with all fields."""
        config = SessionConfig(
            bundle="foundation",
            provider="anthropic",
            model="claude-sonnet-4",
            max_turns=50,
            timeout=600.0,
            working_directory="/home/user/project",
            environment={"DEBUG": "1"},
        )
        assert config.bundle == "foundation"
        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4"
        assert config.max_turns == 50
        assert config.timeout == 600.0
        assert config.working_directory == "/home/user/project"
        assert config.environment == {"DEBUG": "1"}

    def test_environment_is_independent(self) -> None:
        """Environment dict is independent between instances."""
        config1 = SessionConfig()
        config2 = SessionConfig()
        config1.environment["KEY"] = "value"
        assert "KEY" not in config2.environment


# =============================================================================
# ManagedSession Tests - Lifecycle
# =============================================================================


class TestManagedSessionLifecycle:
    """Tests for ManagedSession lifecycle management."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        """Create a SessionStore with temp directory."""
        return SessionStore(storage_dir=tmp_path / "sessions")

    @pytest.fixture
    def config(self) -> SessionConfig:
        """Create a basic session config."""
        return SessionConfig(bundle="test-bundle")

    def test_initial_state_is_created(self, config: SessionConfig) -> None:
        """New session starts in CREATED state."""
        session = ManagedSession("test123", config)
        assert session.metadata.state == SessionState.CREATED
        assert session.session_id == "test123"

    def test_config_is_stored(self, config: SessionConfig) -> None:
        """Config is accessible on session."""
        session = ManagedSession("test123", config)
        assert session.config is config
        assert session.config.bundle == "test-bundle"

    def test_metadata_bundle_from_config(self, config: SessionConfig) -> None:
        """Metadata bundle_name comes from config."""
        session = ManagedSession("test123", config)
        assert session.metadata.bundle_name == "test-bundle"

    def test_working_directory_from_config(self) -> None:
        """Working directory can be set via config."""
        config = SessionConfig(working_directory="/custom/path")
        session = ManagedSession("test123", config)
        assert session.metadata.cwd == "/custom/path"

    def test_working_directory_defaults_to_cwd(self) -> None:
        """Working directory defaults to current directory."""
        config = SessionConfig()
        session = ManagedSession("test123", config)
        assert session.metadata.cwd == str(Path.cwd())

    @pytest.mark.anyio
    async def test_initialize_transitions_to_ready(
        self, config: SessionConfig, store: SessionStore
    ) -> None:
        """Initialize transitions state from CREATED to READY."""
        session = ManagedSession("test123", config, store=store)
        assert session.metadata.state == SessionState.CREATED

        await session.initialize()

        assert session.metadata.state == SessionState.READY

    @pytest.mark.anyio
    async def test_initialize_cannot_be_called_twice(
        self, config: SessionConfig, store: SessionStore
    ) -> None:
        """Initialize raises if already initialized."""
        session = ManagedSession("test123", config, store=store)
        await session.initialize()

        with pytest.raises(RuntimeError, match="Cannot initialize"):
            await session.initialize()

    @pytest.mark.anyio
    async def test_initialize_persists_metadata(
        self, config: SessionConfig, store: SessionStore
    ) -> None:
        """Initialize saves metadata to store."""
        session = ManagedSession("test123", config, store=store)
        await session.initialize()

        # Check store has the metadata
        metadata = store.load_metadata("test123")
        assert metadata is not None
        assert metadata["state"] == "ready"

    @pytest.mark.anyio
    async def test_initialize_with_transcript(
        self, config: SessionConfig, store: SessionStore
    ) -> None:
        """Initialize can restore a transcript."""
        transcript = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        session = ManagedSession("test123", config, store=store)
        await session.initialize(initial_transcript=transcript)

        assert len(session.get_transcript()) == 3
        # Turn count is number of user messages
        assert session.metadata.turn_count == 2

    @pytest.mark.anyio
    async def test_initialize_emits_state_change(
        self, config: SessionConfig, store: SessionStore
    ) -> None:
        """Initialize emits state change event."""
        events: list[Event] = []

        async def capture_event(event: Event) -> None:
            events.append(event)

        session = ManagedSession("test123", config, send_fn=capture_event, store=store)
        await session.initialize()

        assert len(events) == 1
        assert events[0].type == "session:state"
        assert events[0].properties["state"] == "ready"


# =============================================================================
# ManagedSession Tests - Execution
# =============================================================================


class TestManagedSessionExecution:
    """Tests for ManagedSession prompt execution."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        """Create a SessionStore with temp directory."""
        return SessionStore(storage_dir=tmp_path / "sessions")

    @pytest.fixture
    def config(self) -> SessionConfig:
        """Create a basic session config."""
        return SessionConfig()

    @pytest.fixture
    async def ready_session(self, config: SessionConfig, store: SessionStore) -> ManagedSession:
        """Create an initialized session ready for execution."""
        session = ManagedSession("test123", config, store=store)
        await session.initialize()
        return session

    @pytest.mark.anyio
    async def test_execute_requires_ready_state(
        self, config: SessionConfig, store: SessionStore
    ) -> None:
        """Execute raises if not in READY state."""
        session = ManagedSession("test123", config, store=store)
        # Still in CREATED state

        with pytest.raises(RuntimeError, match="Cannot execute"):
            async for _ in session.execute("Hello"):
                pass

    @pytest.mark.anyio
    async def test_execute_transitions_to_running(self, ready_session: ManagedSession) -> None:
        """Execute transitions to RUNNING state."""
        # Collect events but check state during first event
        events = []
        async for event in ready_session.execute("Hello"):
            if not events:  # First event
                # State should be RUNNING during execution
                assert ready_session.metadata.state == SessionState.RUNNING
            events.append(event)

    @pytest.mark.anyio
    async def test_execute_returns_to_ready(self, ready_session: ManagedSession) -> None:
        """Execute returns to READY state after completion."""
        async for _ in ready_session.execute("Hello"):
            pass

        assert ready_session.metadata.state == SessionState.READY

    @pytest.mark.anyio
    async def test_execute_increments_turn_count(self, ready_session: ManagedSession) -> None:
        """Each execute increments turn count."""
        assert ready_session.metadata.turn_count == 0

        async for _ in ready_session.execute("First"):
            pass
        assert ready_session.metadata.turn_count == 1

        async for _ in ready_session.execute("Second"):
            pass
        assert ready_session.metadata.turn_count == 2

    @pytest.mark.anyio
    async def test_execute_emits_prompt_submit(self, ready_session: ManagedSession) -> None:
        """Execute emits prompt:submit event."""
        events = []
        async for event in ready_session.execute("Hello world"):
            events.append(event)

        submit_events = [e for e in events if e.type == "prompt:submit"]
        assert len(submit_events) == 1
        assert submit_events[0].properties["prompt"] == "Hello world"
        assert submit_events[0].properties["turn"] == 1

    @pytest.mark.anyio
    async def test_execute_emits_content_blocks(self, ready_session: ManagedSession) -> None:
        """Execute emits content block events."""
        events = []
        async for event in ready_session.execute("Hello"):
            events.append(event)

        # Should have start, delta(s), and end
        types = [e.type for e in events]
        assert "content_block:start" in types
        assert "content_block:delta" in types
        assert "content_block:end" in types

    @pytest.mark.anyio
    async def test_execute_emits_prompt_complete(self, ready_session: ManagedSession) -> None:
        """Execute emits prompt:complete event at end."""
        events = []
        async for event in ready_session.execute("Hello"):
            events.append(event)

        # Last event should be prompt:complete
        assert events[-1].type == "prompt:complete"
        assert events[-1].properties["turn"] == 1

    @pytest.mark.anyio
    async def test_execute_records_user_message(self, ready_session: ManagedSession) -> None:
        """Execute records user message in transcript."""
        async for _ in ready_session.execute("Hello world"):
            pass

        transcript = ready_session.get_transcript()
        user_msgs = [m for m in transcript if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "Hello world"

    @pytest.mark.anyio
    async def test_execute_records_assistant_message(self, ready_session: ManagedSession) -> None:
        """Execute records assistant response in transcript."""
        async for _ in ready_session.execute("Hello"):
            pass

        transcript = ready_session.get_transcript()
        assistant_msgs = [m for m in transcript if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        # Mock mode includes the prompt in response
        assert "Hello" in assistant_msgs[0]["content"]

    @pytest.mark.anyio
    async def test_execute_persists_transcript(
        self, ready_session: ManagedSession, store: SessionStore
    ) -> None:
        """Execute persists transcript to store."""
        async for _ in ready_session.execute("Hello"):
            pass

        # Check store has transcript
        transcript = store.load_transcript("test123")
        assert len(transcript) == 2  # user + assistant

    @pytest.mark.anyio
    async def test_execute_can_run_multiple_turns(self, ready_session: ManagedSession) -> None:
        """Execute can run multiple turns in sequence."""
        async for _ in ready_session.execute("First"):
            pass
        async for _ in ready_session.execute("Second"):
            pass
        async for _ in ready_session.execute("Third"):
            pass

        transcript = ready_session.get_transcript()
        assert len(transcript) == 6  # 3 user + 3 assistant
        assert ready_session.metadata.turn_count == 3


# =============================================================================
# ManagedSession Tests - Cancel
# =============================================================================


class TestManagedSessionCancel:
    """Tests for ManagedSession cancellation."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        """Create a SessionStore with temp directory."""
        return SessionStore(storage_dir=tmp_path / "sessions")

    @pytest.fixture
    def config(self) -> SessionConfig:
        """Create a basic session config."""
        return SessionConfig()

    @pytest.mark.anyio
    async def test_cancel_sets_event(self, config: SessionConfig, store: SessionStore) -> None:
        """Cancel sets the cancel event."""
        session = ManagedSession("test123", config, store=store)
        await session.initialize()

        assert not session._cancel_event.is_set()
        await session.cancel()
        assert session._cancel_event.is_set()

    @pytest.mark.anyio
    async def test_cancel_running_session(self, config: SessionConfig, store: SessionStore) -> None:
        """Cancel transitions RUNNING to CANCELLED."""
        session = ManagedSession("test123", config, store=store)
        await session.initialize()

        # Manually set to running
        session.metadata.state = SessionState.RUNNING

        await session.cancel()

        assert session.metadata.state == SessionState.CANCELLED

    @pytest.mark.anyio
    async def test_cancel_emits_event(self, config: SessionConfig, store: SessionStore) -> None:
        """Cancel emits cancel:requested event."""
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        session = ManagedSession("test123", config, send_fn=capture, store=store)
        await session.initialize()
        events.clear()

        await session.cancel()

        cancel_events = [e for e in events if e.type == "cancel:requested"]
        assert len(cancel_events) == 1


# =============================================================================
# ManagedSession Tests - Serialization
# =============================================================================


class TestManagedSessionSerialization:
    """Tests for ManagedSession serialization."""

    @pytest.fixture
    def config(self) -> SessionConfig:
        return SessionConfig(bundle="test-bundle", working_directory="/test/path")

    def test_to_dict(self, config: SessionConfig) -> None:
        """to_dict returns serializable representation."""
        session = ManagedSession("test123", config)

        result = session.to_dict()

        assert result["session_id"] == "test123"
        assert result["state"] == "created"
        assert result["bundle"] == "test-bundle"
        assert result["cwd"] == "/test/path"
        assert result["turn_count"] == 0
        assert result["parent_session_id"] is None
        assert result["error"] is None
        # Timestamps should be ISO strings
        assert "T" in result["created_at"]
        assert "T" in result["updated_at"]

    def test_to_dict_is_json_serializable(self, config: SessionConfig) -> None:
        """to_dict output can be JSON serialized."""
        import json

        session = ManagedSession("test123", config)
        result = session.to_dict()

        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_get_transcript_returns_copy(self, config: SessionConfig) -> None:
        """get_transcript returns a copy of messages."""
        session = ManagedSession("test123", config)
        session._messages = [{"role": "user", "content": "Hello"}]

        transcript = session.get_transcript()
        transcript.append({"role": "assistant", "content": "Hi"})

        # Original should be unchanged
        assert len(session._messages) == 1


# =============================================================================
# SessionManager Tests
# =============================================================================


class TestSessionManager:
    """Tests for SessionManager."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        """Create a SessionStore with temp directory."""
        return SessionStore(storage_dir=tmp_path / "sessions")

    @pytest.fixture
    def manager(self, store: SessionStore) -> SessionManager:
        """Create a SessionManager with test store."""
        return SessionManager(store=store)

    @pytest.mark.anyio
    async def test_create_returns_session(self, manager: SessionManager) -> None:
        """Create returns a ManagedSession."""
        session = await manager.create()

        assert isinstance(session, ManagedSession)
        assert session.session_id.startswith("sess_")

    @pytest.mark.anyio
    async def test_create_with_config(self, manager: SessionManager) -> None:
        """Create uses provided config."""
        config = SessionConfig(bundle="my-bundle")
        session = await manager.create(config=config)

        assert session.config.bundle == "my-bundle"

    @pytest.mark.anyio
    async def test_create_with_custom_id(self, manager: SessionManager) -> None:
        """Create can use custom session ID."""
        session = await manager.create(session_id="custom123")

        assert session.session_id == "custom123"

    @pytest.mark.anyio
    async def test_create_with_send_fn(self, manager: SessionManager) -> None:
        """Create attaches send function."""
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        session = await manager.create(send_fn=capture)
        await session.initialize()

        # Should have received state change event
        assert len(events) > 0

    @pytest.mark.anyio
    async def test_get_returns_active_session(self, manager: SessionManager) -> None:
        """Get returns an active session by ID."""
        session = await manager.create(session_id="test123")

        found = await manager.get("test123")

        assert found is session

    @pytest.mark.anyio
    async def test_get_returns_none_for_unknown(self, manager: SessionManager) -> None:
        """Get returns None for unknown session ID."""
        found = await manager.get("nonexistent")

        assert found is None

    @pytest.mark.anyio
    async def test_delete_removes_active_session(self, manager: SessionManager) -> None:
        """Delete removes session from active sessions."""
        session = await manager.create(session_id="test123")
        await session.initialize()

        result = await manager.delete("test123")

        assert result is True
        assert await manager.get("test123") is None

    @pytest.mark.anyio
    async def test_delete_returns_false_for_unknown(self, manager: SessionManager) -> None:
        """Delete returns False for unknown session."""
        result = await manager.delete("nonexistent")

        assert result is False

    @pytest.mark.anyio
    async def test_delete_with_saved_flag(
        self, manager: SessionManager, store: SessionStore
    ) -> None:
        """Delete can also delete from storage."""
        session = await manager.create(session_id="test123")
        await session.initialize()

        # Should exist in store
        assert store.session_exists("test123")

        await manager.delete("test123", delete_saved=True)

        # Should be gone from store too
        assert not store.session_exists("test123")

    @pytest.mark.anyio
    async def test_list_active(self, manager: SessionManager) -> None:
        """list_active returns all active sessions."""
        session1 = await manager.create(session_id="sess1")
        session2 = await manager.create(session_id="sess2")
        await session1.initialize()
        await session2.initialize()

        active = await manager.list_active()

        assert len(active) == 2
        ids = {s["session_id"] for s in active}
        assert ids == {"sess1", "sess2"}

    @pytest.mark.anyio
    async def test_list_saved(self, manager: SessionManager, store: SessionStore) -> None:
        """list_saved returns sessions from storage."""
        # Create and initialize some sessions
        session1 = await manager.create(session_id="sess1")
        session2 = await manager.create(session_id="sess2")
        await session1.initialize()
        await session2.initialize()

        # Execute prompts to get turn counts
        async for _ in session1.execute("Hello"):
            pass
        async for _ in session2.execute("World"):
            pass

        saved = manager.list_saved(min_turns=1)

        assert len(saved) == 2

    @pytest.mark.anyio
    async def test_get_session_info_active(self, manager: SessionManager) -> None:
        """get_session_info returns info for active session."""
        session = await manager.create(session_id="test123")
        await session.initialize()

        info = manager.get_session_info("test123")

        assert info is not None
        assert info["session_id"] == "test123"
        assert info["active"] is True

    @pytest.mark.anyio
    async def test_get_session_info_saved(
        self, manager: SessionManager, store: SessionStore
    ) -> None:
        """get_session_info returns info for saved (inactive) session."""
        # Create, initialize, execute, then remove from memory
        session = await manager.create(session_id="test123")
        await session.initialize()
        async for _ in session.execute("Hello"):
            pass

        # Remove from active but keep in storage
        await manager.delete("test123", delete_saved=False)

        info = manager.get_session_info("test123")

        assert info is not None
        assert info["session_id"] == "test123"

    @pytest.mark.anyio
    async def test_get_session_info_not_found(self, manager: SessionManager) -> None:
        """get_session_info returns None for unknown session."""
        info = manager.get_session_info("nonexistent")

        assert info is None

    @pytest.mark.anyio
    async def test_resume_active_session(self, manager: SessionManager) -> None:
        """Resume returns existing active session."""
        session = await manager.create(session_id="test123")
        await session.initialize()

        resumed = await manager.resume("test123")

        assert resumed is session

    @pytest.mark.anyio
    async def test_resume_from_storage(self, manager: SessionManager, store: SessionStore) -> None:
        """Resume loads session from storage."""
        # Create, initialize, execute
        session = await manager.create(session_id="test123")
        await session.initialize()
        async for _ in session.execute("Hello"):
            pass

        # Remove from active
        await manager.delete("test123", delete_saved=False)

        # Resume should load from storage
        resumed = await manager.resume("test123")

        assert resumed is not None
        assert resumed.session_id == "test123"
        assert len(resumed.get_transcript()) == 2  # user + assistant

    @pytest.mark.anyio
    async def test_resume_not_found(self, manager: SessionManager) -> None:
        """Resume returns None if session doesn't exist."""
        resumed = await manager.resume("nonexistent")

        assert resumed is None

    @pytest.mark.anyio
    async def test_active_count(self, manager: SessionManager) -> None:
        """active_count returns number of ready/running sessions."""
        session1 = await manager.create(session_id="sess1")
        session2 = await manager.create(session_id="sess2")
        await session1.initialize()
        await session2.initialize()

        assert manager.active_count == 2

    @pytest.mark.anyio
    async def test_total_count(self, manager: SessionManager) -> None:
        """total_count returns number of sessions in memory."""
        await manager.create(session_id="sess1")
        await manager.create(session_id="sess2")
        await manager.create(session_id="sess3")

        assert manager.total_count == 3

    @pytest.mark.anyio
    async def test_cleanup_completed(self, manager: SessionManager) -> None:
        """cleanup_completed removes old completed sessions."""
        session = await manager.create(session_id="test123")
        await session.initialize()

        # Mark as completed with old timestamp
        session.metadata.state = SessionState.COMPLETED
        session.metadata.updated_at = datetime(2020, 1, 1, tzinfo=UTC)

        count = await manager.cleanup_completed(max_age_seconds=1)

        assert count == 1
        assert manager.total_count == 0

    @pytest.mark.anyio
    async def test_cleanup_keeps_recent(self, manager: SessionManager) -> None:
        """cleanup_completed keeps recent completed sessions."""
        session = await manager.create(session_id="test123")
        await session.initialize()

        # Mark as completed with current timestamp
        session.metadata.state = SessionState.COMPLETED
        # updated_at is already current

        count = await manager.cleanup_completed(max_age_seconds=3600)

        assert count == 0
        assert manager.total_count == 1

    @pytest.mark.anyio
    async def test_store_property(self, manager: SessionManager, store: SessionStore) -> None:
        """store property returns the session store."""
        assert manager.store is store
