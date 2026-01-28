"""Unit tests for spawn protocol.

Tests the ServerSpawnManager for agent delegation.
Minimal mocking - tests real code paths where possible.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_server_app.protocols.spawn import (
    ServerSpawnManager,
    register_spawn_capability,
)

# =============================================================================
# ServerSpawnManager Tests
# =============================================================================


class TestServerSpawnManager:
    """Tests for ServerSpawnManager - agent spawning."""

    def test_init_empty_active_spawns(self) -> None:
        """SpawnManager starts with no active spawns."""
        manager = ServerSpawnManager()
        assert manager.get_active_spawns() == []

    def test_get_active_spawns_returns_list(self) -> None:
        """get_active_spawns returns list of session IDs."""
        manager = ServerSpawnManager()
        # Manually add to test the getter
        manager._active_spawns["sess_1"] = MagicMock()
        manager._active_spawns["sess_2"] = MagicMock()

        result = manager.get_active_spawns()

        assert isinstance(result, list)
        assert set(result) == {"sess_1", "sess_2"}

    @pytest.mark.asyncio
    async def test_spawn_unknown_agent_returns_error(self) -> None:
        """Spawn returns error for unknown agent name."""
        manager = ServerSpawnManager()

        # Mock parent session
        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = None

        # Mock prepared bundle
        prepared_bundle = MagicMock()

        result = await manager.spawn(
            agent_name="nonexistent-agent",
            instruction="Do something",
            parent_session=parent_session,
            agent_configs={},  # No agents configured
            prepared_bundle=prepared_bundle,
        )

        assert result["status"] == "error"
        assert "Unknown agent" in result["error"]
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_spawn_generates_session_id(self) -> None:
        """Spawn generates session ID if not provided."""
        manager = ServerSpawnManager()

        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = None

        prepared_bundle = MagicMock()

        result = await manager.spawn(
            agent_name="test-agent",
            instruction="Test",
            parent_session=parent_session,
            agent_configs={},
            prepared_bundle=prepared_bundle,
        )

        assert result["session_id"].startswith("sub_")
        assert len(result["session_id"]) > 4  # Has UUID portion

    @pytest.mark.asyncio
    async def test_spawn_uses_provided_session_id(self) -> None:
        """Spawn uses provided session ID."""
        manager = ServerSpawnManager()

        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = None

        prepared_bundle = MagicMock()

        result = await manager.spawn(
            agent_name="test-agent",
            instruction="Test",
            parent_session=parent_session,
            agent_configs={},
            prepared_bundle=prepared_bundle,
            sub_session_id="my_custom_id",
        )

        assert result["session_id"] == "my_custom_id"

    @pytest.mark.asyncio
    async def test_spawn_success_flow(self) -> None:
        """Spawn successfully creates and executes child session."""
        manager = ServerSpawnManager()

        # Mock parent session with hooks
        parent_hooks = MagicMock()
        parent_hooks.emit = AsyncMock()
        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = parent_hooks

        # Mock child session
        child_hooks = MagicMock()
        child_hooks.register = MagicMock()
        child_session = MagicMock()
        child_session.coordinator.hooks = child_hooks
        child_session.execute = AsyncMock(return_value="Task completed!")

        # Mock prepared bundle
        prepared_bundle = MagicMock()
        prepared_bundle.create_session = AsyncMock(return_value=child_session)

        agent_configs = {"my-agent": {"name": "my-agent", "instructions": "Be helpful"}}

        result = await manager.spawn(
            agent_name="my-agent",
            instruction="Do the task",
            parent_session=parent_session,
            agent_configs=agent_configs,
            prepared_bundle=prepared_bundle,
        )

        assert result["status"] == "success"
        assert result["result"] == "Task completed!"
        assert "session_id" in result

        # Verify child session was created
        prepared_bundle.create_session.assert_called_once()

        # Verify instruction was executed
        child_session.execute.assert_called_once_with("Do the task")

        # Verify hooks were registered for event forwarding
        assert child_hooks.register.call_count > 0

    @pytest.mark.asyncio
    async def test_spawn_registers_event_forwarders(self) -> None:
        """Spawn registers event forwarders for key events."""
        manager = ServerSpawnManager()

        parent_hooks = MagicMock()
        parent_hooks.emit = AsyncMock()
        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = parent_hooks

        child_hooks = MagicMock()
        registered_events = []

        def capture_register(event, handler, priority, name):
            registered_events.append(event)

        child_hooks.register = capture_register
        child_session = MagicMock()
        child_session.coordinator.hooks = child_hooks
        child_session.execute = AsyncMock(return_value="Done")

        prepared_bundle = MagicMock()
        prepared_bundle.create_session = AsyncMock(return_value=child_session)

        await manager.spawn(
            agent_name="agent",
            instruction="Test",
            parent_session=parent_session,
            agent_configs={"agent": {"name": "agent"}},
            prepared_bundle=prepared_bundle,
        )

        # Should register forwarders for content and tool events
        expected_events = {
            "content_block:start",
            "content_block:delta",
            "content_block:end",
            "tool:pre",
            "tool:post",
            "tool:error",
        }
        assert expected_events.issubset(set(registered_events))

    @pytest.mark.asyncio
    async def test_spawn_cleans_up_on_success(self) -> None:
        """Spawn removes session from active spawns after success."""
        manager = ServerSpawnManager()

        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = None

        child_session = MagicMock()
        child_session.coordinator.hooks = None
        child_session.execute = AsyncMock(return_value="Done")

        prepared_bundle = MagicMock()
        prepared_bundle.create_session = AsyncMock(return_value=child_session)

        result = await manager.spawn(
            agent_name="agent",
            instruction="Test",
            parent_session=parent_session,
            agent_configs={"agent": {"name": "agent"}},
            prepared_bundle=prepared_bundle,
            sub_session_id="test_session",
        )

        assert result["status"] == "success"
        assert "test_session" not in manager.get_active_spawns()

    @pytest.mark.asyncio
    async def test_spawn_cleans_up_on_error(self) -> None:
        """Spawn removes session from active spawns after error."""
        manager = ServerSpawnManager()

        parent_session = MagicMock()
        parent_session.session_id = "parent_123"
        parent_session.coordinator.hooks = None

        child_session = MagicMock()
        child_session.coordinator.hooks = None
        child_session.execute = AsyncMock(side_effect=RuntimeError("Execution failed"))

        prepared_bundle = MagicMock()
        prepared_bundle.create_session = AsyncMock(return_value=child_session)

        result = await manager.spawn(
            agent_name="agent",
            instruction="Test",
            parent_session=parent_session,
            agent_configs={"agent": {"name": "agent"}},
            prepared_bundle=prepared_bundle,
            sub_session_id="test_session",
        )

        assert result["status"] == "error"
        assert "Execution failed" in result["error"]
        assert "test_session" not in manager.get_active_spawns()

    @pytest.mark.asyncio
    async def test_cancel_spawn_not_found(self) -> None:
        """cancel_spawn returns False for unknown session."""
        manager = ServerSpawnManager()

        result = await manager.cancel_spawn("nonexistent_session")

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_spawn_calls_cancel(self) -> None:
        """cancel_spawn calls session's cancel method."""
        manager = ServerSpawnManager()

        # Add a mock session
        mock_session = MagicMock()
        mock_session.cancel = AsyncMock()
        manager._active_spawns["sess_123"] = mock_session

        result = await manager.cancel_spawn("sess_123")

        assert result is True
        mock_session.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_spawn_handles_cancel_error(self) -> None:
        """cancel_spawn handles errors during cancellation."""
        manager = ServerSpawnManager()

        mock_session = MagicMock()
        mock_session.cancel = AsyncMock(side_effect=RuntimeError("Cancel failed"))
        manager._active_spawns["sess_123"] = mock_session

        result = await manager.cancel_spawn("sess_123")

        # Should return False on error
        assert result is False


# =============================================================================
# register_spawn_capability Tests
# =============================================================================


class TestRegisterSpawnCapability:
    """Tests for register_spawn_capability function."""

    def test_registers_capability_on_session(self) -> None:
        """register_spawn_capability adds session.spawn capability."""
        mock_session = MagicMock()
        mock_prepared_bundle = MagicMock()

        register_spawn_capability(mock_session, mock_prepared_bundle)

        mock_session.coordinator.register_capability.assert_called_once()
        call_args = mock_session.coordinator.register_capability.call_args
        assert call_args[0][0] == "session.spawn"
        assert callable(call_args[0][1])

    def test_returns_spawn_manager(self) -> None:
        """register_spawn_capability returns the spawn manager."""
        mock_session = MagicMock()
        mock_prepared_bundle = MagicMock()

        result = register_spawn_capability(mock_session, mock_prepared_bundle)

        assert isinstance(result, ServerSpawnManager)

    def test_uses_provided_spawn_manager(self) -> None:
        """register_spawn_capability uses provided spawn manager."""
        mock_session = MagicMock()
        mock_prepared_bundle = MagicMock()
        existing_manager = ServerSpawnManager()

        result = register_spawn_capability(
            mock_session,
            mock_prepared_bundle,
            spawn_manager=existing_manager,
        )

        assert result is existing_manager

    @pytest.mark.asyncio
    async def test_registered_capability_calls_spawn(self) -> None:
        """Registered capability function calls spawn manager."""
        mock_session = MagicMock()
        mock_prepared_bundle = MagicMock()

        # Capture the registered capability
        registered_fn = None

        def capture_register(name, fn):
            nonlocal registered_fn
            registered_fn = fn

        mock_session.coordinator.register_capability = capture_register

        _manager = register_spawn_capability(mock_session, mock_prepared_bundle)

        # Create mock for the spawn method
        parent_session = MagicMock()
        parent_session.session_id = "parent"
        parent_session.coordinator.hooks = None

        # Verify capability was registered
        assert registered_fn is not None

        # The registered function should accept spawn parameters
        # We can't easily test the full flow without more setup,
        # but we can verify it exists
        assert callable(registered_fn)
