"""Unit tests for ACPApprovalBridge.

Tests the bridge between Amplifier's ApprovalSystem protocol and ACP's
session/request_permission method.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_app_runtime.acp.approval_bridge import (
    ACPApprovalBridge,
    ToolCallContext,
    ToolCallTracker,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockPermissionResponse:
    """Mock response from ACP request_permission."""

    outcome: Any


@dataclass
class MockOutcome:
    """Mock outcome with option_id."""

    option_id: str


def create_mock_client(response_option_id: str = "opt_0") -> MagicMock:
    """Create a mock ACP client with request_permission support."""
    client = MagicMock()
    client.request_permission = AsyncMock(
        return_value=MockPermissionResponse(outcome=MockOutcome(option_id=response_option_id))
    )
    return client


# =============================================================================
# TestToolCallTracker
# =============================================================================


class TestToolCallTracker:
    """Tests for ToolCallTracker context management."""

    def test_track_sets_context(self) -> None:
        """track() should set the current tool call context."""
        ToolCallTracker.track("call_123", "bash", {"command": "ls"})

        ctx = ToolCallTracker.get_current()
        assert ctx is not None
        assert ctx.call_id == "call_123"
        assert ctx.tool_name == "bash"
        assert ctx.arguments == {"command": "ls"}

        # Clean up
        ToolCallTracker.clear()

    def test_clear_removes_context(self) -> None:
        """clear() should remove the current context."""
        ToolCallTracker.track("call_456", "write_file", {"path": "/tmp/test"})
        ToolCallTracker.clear()

        assert ToolCallTracker.get_current() is None

    def test_get_current_returns_none_when_empty(self) -> None:
        """get_current() should return None when no context is set."""
        ToolCallTracker.clear()
        assert ToolCallTracker.get_current() is None

    @pytest.mark.asyncio
    async def test_context_isolation_across_tasks(self) -> None:
        """Context should be isolated between async tasks."""
        results: list[ToolCallContext | None] = []

        async def task1() -> None:
            ToolCallTracker.track("task1_call", "tool1", {})
            await asyncio.sleep(0.01)
            results.append(ToolCallTracker.get_current())
            ToolCallTracker.clear()

        async def task2() -> None:
            ToolCallTracker.track("task2_call", "tool2", {})
            await asyncio.sleep(0.01)
            results.append(ToolCallTracker.get_current())
            ToolCallTracker.clear()

        await asyncio.gather(task1(), task2())

        # Each task should see its own context
        assert len(results) == 2
        call_ids = {r.call_id for r in results if r is not None}
        assert call_ids == {"task1_call", "task2_call"}


# =============================================================================
# TestACPApprovalBridge - Basic Functionality
# =============================================================================


class TestACPApprovalBridgeBasic:
    """Basic tests for ACPApprovalBridge."""

    @pytest.mark.asyncio
    async def test_request_approval_success(self) -> None:
        """Bridge should call client.request_permission and map response."""
        mock_client = create_mock_client(response_option_id="opt_1")

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow bash command?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Should return the option at index 1
        assert result == "Allow always"

        # Verify request_permission was called
        mock_client.request_permission.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_approval_first_option(self) -> None:
        """Should correctly map opt_0 to first option."""
        mock_client = create_mock_client(response_option_id="opt_0")

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow file write?",
            options=["Allow", "Deny"],
            timeout=30.0,
            default="deny",
        )

        assert result == "Allow"

    @pytest.mark.asyncio
    async def test_request_approval_last_option(self) -> None:
        """Should correctly map last option."""
        mock_client = create_mock_client(response_option_id="opt_2")

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Approve action?",
            options=["Yes", "Maybe", "No"],
            timeout=30.0,
            default="deny",
        )

        assert result == "No"


# =============================================================================
# TestACPApprovalBridge - Timeout and Error Handling
# =============================================================================


class TestACPApprovalBridgeErrors:
    """Tests for error handling in ACPApprovalBridge."""

    @pytest.mark.asyncio
    async def test_timeout_returns_default_deny(self) -> None:
        """On timeout, should return the default deny option."""
        mock_client = MagicMock()

        async def slow_request(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)  # Will timeout

        mock_client.request_permission = slow_request

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow", "Deny"],
            timeout=0.01,  # Very short timeout
            default="deny",
        )

        assert result == "Deny"

    @pytest.mark.asyncio
    async def test_timeout_returns_default_allow(self) -> None:
        """On timeout with default=allow, should return allow option."""
        mock_client = MagicMock()

        async def slow_request(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)

        mock_client.request_permission = slow_request

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow", "Deny"],
            timeout=0.01,
            default="allow",
        )

        assert result == "Allow"

    @pytest.mark.asyncio
    async def test_no_client_returns_default(self) -> None:
        """Without client, should return default option."""
        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: None,  # No client
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow once", "Deny"],
            timeout=30.0,
            default="deny",
        )

        assert result == "Deny"

    @pytest.mark.asyncio
    async def test_client_error_returns_default(self) -> None:
        """On client error, should return default option."""
        mock_client = MagicMock()
        mock_client.request_permission = AsyncMock(side_effect=Exception("Connection failed"))

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow", "Deny"],
            timeout=30.0,
            default="deny",
        )

        assert result == "Deny"


# =============================================================================
# TestACPApprovalBridge - Caching
# =============================================================================


class TestACPApprovalBridgeCaching:
    """Tests for approval caching in ACPApprovalBridge."""

    @pytest.mark.asyncio
    async def test_caches_always_decisions(self) -> None:
        """'Allow always' should be cached for the session."""
        mock_client = create_mock_client(response_option_id="opt_1")

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        # First request
        result1 = await bridge.request_approval(
            prompt="Allow bash?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )
        assert result1 == "Allow always"

        # Second request with same prompt/options should use cache
        result2 = await bridge.request_approval(
            prompt="Allow bash?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )
        assert result2 == "Allow always"

        # Should only have called request_permission once
        assert mock_client.request_permission.call_count == 1

    @pytest.mark.asyncio
    async def test_does_not_cache_once_decisions(self) -> None:
        """'Allow once' should NOT be cached."""
        mock_client = create_mock_client(response_option_id="opt_0")

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        # First request
        await bridge.request_approval(
            prompt="Allow bash?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Second request should call again (not cached)
        await bridge.request_approval(
            prompt="Allow bash?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Should have called request_permission twice
        assert mock_client.request_permission.call_count == 2

    @pytest.mark.asyncio
    async def test_different_prompts_not_cached(self) -> None:
        """Different prompts should have separate cache entries."""
        mock_client = create_mock_client(response_option_id="opt_1")

        bridge = ACPApprovalBridge(
            session_id="test_session",
            get_client=lambda: mock_client,
        )

        # First prompt
        await bridge.request_approval(
            prompt="Allow bash?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Different prompt
        await bridge.request_approval(
            prompt="Allow file write?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Should have called twice (different prompts)
        assert mock_client.request_permission.call_count == 2


# =============================================================================
# TestACPApprovalBridge - Option Mapping
# =============================================================================


class TestACPApprovalBridgeOptionMapping:
    """Tests for option mapping in ACPApprovalBridge."""

    def test_build_permission_options_allow_once(self) -> None:
        """'Allow once' should map to allow_once kind."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        options = bridge._build_permission_options(["Allow once", "Deny"])

        assert options[0]["optionId"] == "opt_0"
        assert options[0]["name"] == "Allow once"
        assert options[0]["kind"] == "allow_once"

    def test_build_permission_options_allow_always(self) -> None:
        """'Allow always' should map to allow_always kind."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        options = bridge._build_permission_options(["Allow always"])

        assert options[0]["kind"] == "allow_always"

    def test_build_permission_options_deny(self) -> None:
        """'Deny' should map to reject_once kind."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        options = bridge._build_permission_options(["Deny"])

        assert options[0]["kind"] == "reject_once"

    def test_build_permission_options_deny_always(self) -> None:
        """'Deny always' should map to reject_always kind."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        options = bridge._build_permission_options(["Deny always"])

        assert options[0]["kind"] == "reject_always"

    def test_map_option_id_valid(self) -> None:
        """Should map valid option IDs correctly."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        options = ["First", "Second", "Third"]

        assert bridge._map_option_id_to_string("opt_0", options) == "First"
        assert bridge._map_option_id_to_string("opt_1", options) == "Second"
        assert bridge._map_option_id_to_string("opt_2", options) == "Third"

    def test_map_option_id_invalid_returns_first(self) -> None:
        """Invalid option ID should return first option."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        options = ["First", "Second"]

        assert bridge._map_option_id_to_string("invalid", options) == "First"
        assert bridge._map_option_id_to_string("opt_99", options) == "First"


# =============================================================================
# TestACPApprovalBridge - Tool Call Context
# =============================================================================


class TestACPApprovalBridgeToolContext:
    """Tests for tool call context in ACPApprovalBridge."""

    def test_build_tool_call_context_with_tracker(self) -> None:
        """Should include tool context when tracker has info."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        # Set tool context
        ToolCallTracker.track("call_789", "bash", {"command": "rm -rf /tmp/test"})

        try:
            ctx = bridge._build_tool_call_context("Allow dangerous command?")

            assert ctx["toolCallId"] == "call_789"
            assert "rm -rf" in ctx["title"]  # Title should include command
            assert ctx["kind"] == "execute"
            assert ctx["status"] == "pending"
            assert len(ctx["content"]) == 1
            assert ctx["content"][0]["text"] == "Allow dangerous command?"
        finally:
            ToolCallTracker.clear()

    def test_build_tool_call_context_without_tracker(self) -> None:
        """Should generate synthetic context when no tracker info."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        ToolCallTracker.clear()

        ctx = bridge._build_tool_call_context("Allow action?")

        assert ctx["toolCallId"].startswith("approval_")
        assert ctx["title"] == "Permission Required"
        assert ctx["kind"] == "other"

    def test_generate_title_bash(self) -> None:
        """Should generate readable title for bash commands."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        title = bridge._generate_title("bash", {"command": "npm install"})
        assert "npm install" in title

    def test_generate_title_file_operations(self) -> None:
        """Should generate readable titles for file operations."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        assert "config.json" in bridge._generate_title(
            "write_file", {"file_path": "/app/config.json"}
        )
        assert "main.py" in bridge._generate_title("edit_file", {"file_path": "main.py"})
        assert "README.md" in bridge._generate_title("read_file", {"file_path": "README.md"})

    def test_infer_kind(self) -> None:
        """Should infer correct ACP tool kinds."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        assert bridge._infer_kind("bash") == "execute"
        assert bridge._infer_kind("write_file") == "edit"
        assert bridge._infer_kind("edit_file") == "edit"
        assert bridge._infer_kind("read_file") == "read"
        assert bridge._infer_kind("glob") == "read"
        assert bridge._infer_kind("web_fetch") == "fetch"
        assert bridge._infer_kind("unknown_tool") == "other"


# =============================================================================
# TestACPApprovalBridge - Default Resolution
# =============================================================================


class TestACPApprovalBridgeDefaultResolution:
    """Tests for default option resolution."""

    def test_resolve_default_deny_finds_deny(self) -> None:
        """Should find 'Deny' option for default=deny."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        result = bridge._resolve_default("deny", ["Allow", "Deny"])
        assert result == "Deny"

    def test_resolve_default_allow_finds_allow(self) -> None:
        """Should find 'Allow' option for default=allow."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        result = bridge._resolve_default("allow", ["Allow", "Deny"])
        assert result == "Allow"

    def test_resolve_default_finds_yes_no(self) -> None:
        """Should recognize 'Yes' and 'No' as allow/deny."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        assert bridge._resolve_default("allow", ["Yes", "No"]) == "Yes"
        assert bridge._resolve_default("deny", ["Yes", "No"]) == "No"

    def test_resolve_default_fallback(self) -> None:
        """Should fall back to first/last option when no match."""
        bridge = ACPApprovalBridge(
            session_id="test",
            get_client=lambda: None,
        )

        # For deny, fall back to last option
        result = bridge._resolve_default("deny", ["Option A", "Option B"])
        assert result == "Option B"

        # For allow, fall back to first option
        result = bridge._resolve_default("allow", ["Option A", "Option B"])
        assert result == "Option A"
