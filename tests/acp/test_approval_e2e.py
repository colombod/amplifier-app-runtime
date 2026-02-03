"""End-to-end tests for ACP request_permission flow.

Tests the complete integration between:
- ACP Client (IDE) sending request_permission
- ACPApprovalBridge receiving and mapping requests
- Amplifier's ApprovalSystem protocol

These tests use mock ACP clients to simulate IDE interactions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_app_runtime.acp.approval_bridge import ACPApprovalBridge, ToolCallTracker

# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockPermissionOutcome:
    """Mock outcome from ACP request_permission."""

    option_id: str


@dataclass
class MockPermissionResponse:
    """Mock response from ACP request_permission."""

    outcome: MockPermissionOutcome


class MockACPClient:
    """Mock ACP Client that simulates IDE behavior.

    This simulates what an IDE like VS Code or JetBrains would do
    when receiving a request_permission call.
    """

    def __init__(self, auto_response: str | None = None) -> None:
        """Initialize mock client.

        Args:
            auto_response: If set, automatically respond with this option ID.
                          If None, requires manual response via respond().
        """
        self._auto_response = auto_response
        self._pending_requests: list[dict[str, Any]] = []
        self._responses: dict[int, asyncio.Future[MockPermissionResponse]] = {}
        self._request_count = 0
        self.request_permission_calls: list[dict[str, Any]] = []

    async def request_permission(
        self,
        session_id: str,
        tool_call: dict[str, Any],
        options: list[dict[str, Any]],
    ) -> MockPermissionResponse:
        """Simulate IDE permission dialog.

        Args:
            session_id: The ACP session ID
            tool_call: Tool call context
            options: Available permission options

        Returns:
            User's selected option
        """
        request = {
            "session_id": session_id,
            "tool_call": tool_call,
            "options": options,
            "request_id": self._request_count,
        }
        self.request_permission_calls.append(request)
        self._request_count += 1

        if self._auto_response:
            return MockPermissionResponse(
                outcome=MockPermissionOutcome(option_id=self._auto_response)
            )

        # Wait for manual response
        future: asyncio.Future[MockPermissionResponse] = asyncio.Future()
        self._responses[request["request_id"]] = future
        self._pending_requests.append(request)
        return await future

    def respond(self, request_id: int, option_id: str) -> None:
        """Manually respond to a pending permission request.

        Args:
            request_id: The request to respond to
            option_id: The selected option ID
        """
        if request_id in self._responses:
            self._responses[request_id].set_result(
                MockPermissionResponse(outcome=MockPermissionOutcome(option_id=option_id))
            )

    @property
    def pending_requests(self) -> list[dict[str, Any]]:
        """Get list of pending permission requests."""
        return self._pending_requests


# =============================================================================
# E2E Test: Full Permission Flow
# =============================================================================


class TestApprovalE2EFlow:
    """End-to-end tests for the full permission request flow."""

    @pytest.mark.asyncio
    async def test_full_permission_flow_allow(self) -> None:
        """Test complete flow: tool triggers approval -> IDE shows dialog -> user allows."""
        # Setup: Create mock IDE client that auto-allows
        mock_client = MockACPClient(auto_response="opt_0")

        # Create approval bridge (simulating AmplifierAgentSession setup)
        bridge = ACPApprovalBridge(
            session_id="e2e_test_session",
            get_client=lambda: mock_client,
        )

        # Simulate tool context (as would happen in tool:pre event)
        ToolCallTracker.track("call_e2e_001", "bash", {"command": "rm -rf /tmp/test"})

        try:
            # Simulate Amplifier's coordinator calling request_approval
            # (this would happen when a hook returns HookResult(action="ask_user"))
            result = await bridge.request_approval(
                prompt="Allow dangerous command: rm -rf /tmp/test?",
                options=["Allow once", "Allow always", "Deny"],
                timeout=30.0,
                default="deny",
            )

            # Verify: User allowed
            assert result == "Allow once"

            # Verify: IDE received proper permission request
            assert len(mock_client.request_permission_calls) == 1
            call = mock_client.request_permission_calls[0]

            assert call["session_id"] == "e2e_test_session"
            assert call["tool_call"]["toolCallId"] == "call_e2e_001"
            assert "rm -rf" in call["tool_call"]["title"]
            assert call["tool_call"]["kind"] == "execute"
            assert len(call["options"]) == 3

        finally:
            ToolCallTracker.clear()

    @pytest.mark.asyncio
    async def test_full_permission_flow_deny(self) -> None:
        """Test complete flow: tool triggers approval -> IDE shows dialog -> user denies."""
        # Setup: Create mock IDE client that auto-denies
        mock_client = MockACPClient(auto_response="opt_2")  # "Deny" is opt_2

        bridge = ACPApprovalBridge(
            session_id="e2e_test_session",
            get_client=lambda: mock_client,
        )

        ToolCallTracker.track("call_e2e_002", "write_file", {"file_path": "/etc/passwd"})

        try:
            result = await bridge.request_approval(
                prompt="Allow write to /etc/passwd?",
                options=["Allow once", "Allow always", "Deny"],
                timeout=30.0,
                default="deny",
            )

            # Verify: User denied
            assert result == "Deny"

            # Verify: IDE received proper request
            assert len(mock_client.request_permission_calls) == 1
            call = mock_client.request_permission_calls[0]
            assert call["tool_call"]["kind"] == "edit"

        finally:
            ToolCallTracker.clear()

    @pytest.mark.asyncio
    async def test_full_permission_flow_allow_always_cached(self) -> None:
        """Test that 'Allow always' is cached for subsequent requests."""
        mock_client = MockACPClient(auto_response="opt_1")  # "Allow always"

        bridge = ACPApprovalBridge(
            session_id="e2e_test_session",
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

        # Second request with same prompt/options - should use cache
        result2 = await bridge.request_approval(
            prompt="Allow bash?",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )
        assert result2 == "Allow always"

        # Verify: IDE only received ONE request (second was cached)
        assert len(mock_client.request_permission_calls) == 1


# =============================================================================
# E2E Test: IDE Interaction Simulation
# =============================================================================


class TestIDEInteractionSimulation:
    """Tests simulating realistic IDE interactions."""

    @pytest.mark.asyncio
    async def test_ide_shows_correct_options(self) -> None:
        """Verify IDE receives correctly formatted permission options."""
        mock_client = MockACPClient(auto_response="opt_0")

        bridge = ACPApprovalBridge(
            session_id="ide_test",
            get_client=lambda: mock_client,
        )

        await bridge.request_approval(
            prompt="Test prompt",
            options=["Allow once", "Allow always", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Verify options format for IDE
        call = mock_client.request_permission_calls[0]
        options = call["options"]

        assert options[0] == {"optionId": "opt_0", "name": "Allow once", "kind": "allow_once"}
        assert options[1] == {
            "optionId": "opt_1",
            "name": "Allow always",
            "kind": "allow_always",
        }
        assert options[2] == {"optionId": "opt_2", "name": "Deny", "kind": "reject_once"}

    @pytest.mark.asyncio
    async def test_ide_shows_tool_context(self) -> None:
        """Verify IDE receives tool context for permission dialog."""
        mock_client = MockACPClient(auto_response="opt_0")

        bridge = ACPApprovalBridge(
            session_id="ide_test",
            get_client=lambda: mock_client,
        )

        # Set tool context
        ToolCallTracker.track("tool_ctx_test", "web_fetch", {"url": "https://example.com"})

        try:
            await bridge.request_approval(
                prompt="Allow fetching external URL?",
                options=["Allow", "Deny"],
                timeout=30.0,
                default="deny",
            )

            call = mock_client.request_permission_calls[0]
            tool_call = call["tool_call"]

            # Verify tool context is passed to IDE
            assert tool_call["toolCallId"] == "tool_ctx_test"
            assert "example.com" in tool_call["title"]
            assert tool_call["kind"] == "fetch"
            assert tool_call["status"] == "pending"

            # Verify prompt is in content
            assert len(tool_call["content"]) == 1
            assert tool_call["content"][0]["text"] == "Allow fetching external URL?"

        finally:
            ToolCallTracker.clear()

    @pytest.mark.asyncio
    async def test_ide_delayed_response(self) -> None:
        """Test handling of delayed IDE responses (user thinking)."""
        mock_client = MockACPClient()  # No auto-response

        bridge = ACPApprovalBridge(
            session_id="delayed_test",
            get_client=lambda: mock_client,
        )

        # Start approval request (will wait for response)
        approval_task = asyncio.create_task(
            bridge.request_approval(
                prompt="Thinking...",
                options=["Yes", "No"],
                timeout=30.0,
                default="deny",
            )
        )

        # Give task time to send request
        await asyncio.sleep(0.01)

        # Verify request is pending
        assert len(mock_client.pending_requests) == 1

        # Simulate user finally responding after delay
        mock_client.respond(request_id=0, option_id="opt_0")

        # Get result
        result = await approval_task
        assert result == "Yes"


# =============================================================================
# E2E Test: Error Scenarios
# =============================================================================


class TestApprovalE2EErrors:
    """End-to-end tests for error scenarios."""

    @pytest.mark.asyncio
    async def test_ide_disconnected_uses_default(self) -> None:
        """When IDE disconnects, should use default action."""
        bridge = ACPApprovalBridge(
            session_id="disconnected_test",
            get_client=lambda: None,  # No client (disconnected)
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Should use default (deny)
        assert result == "Deny"

    @pytest.mark.asyncio
    async def test_ide_error_uses_default(self) -> None:
        """When IDE returns error, should use default action."""
        mock_client = MagicMock()
        mock_client.request_permission = AsyncMock(side_effect=Exception("IDE crashed"))

        bridge = ACPApprovalBridge(
            session_id="error_test",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Should use default (deny) on error
        assert result == "Deny"

    @pytest.mark.asyncio
    async def test_ide_timeout_uses_default(self) -> None:
        """When IDE times out, should use default action."""
        mock_client = MagicMock()

        async def slow_response(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)  # Very slow

        mock_client.request_permission = slow_response

        bridge = ACPApprovalBridge(
            session_id="timeout_test",
            get_client=lambda: mock_client,
        )

        result = await bridge.request_approval(
            prompt="Allow action?",
            options=["Allow", "Deny"],
            timeout=0.01,  # Very short timeout
            default="deny",
        )

        # Should use default (deny) on timeout
        assert result == "Deny"


# =============================================================================
# E2E Test: Session Integration
# =============================================================================


class TestSessionIntegration:
    """Tests for integration with AmplifierAgentSession."""

    @pytest.mark.asyncio
    async def test_approval_bridge_wired_correctly(self) -> None:
        """Verify ACPApprovalBridge is properly wired in session config."""
        # This tests the integration point in session.py
        from amplifier_app_runtime.session import SessionConfig

        mock_bridge = ACPApprovalBridge(
            session_id="integration_test",
            get_client=lambda: None,
        )

        config = SessionConfig(
            bundle="foundation",
            approval_system=mock_bridge,
        )

        # Verify approval_system is set
        assert config.approval_system is mock_bridge

    @pytest.mark.asyncio
    async def test_tool_tracking_in_event_flow(self) -> None:
        """Test that tool tracking works across the event flow."""
        # Simulate the flow that happens in AmplifierAgentSession._on_event

        # 1. tool:pre event fires, we track the tool
        ToolCallTracker.track("flow_test_001", "edit_file", {"file_path": "main.py"})

        # 2. Approval is requested (during tool execution)
        ctx = ToolCallTracker.get_current()
        assert ctx is not None
        assert ctx.call_id == "flow_test_001"
        assert ctx.tool_name == "edit_file"

        # 3. tool:post event fires, we clear tracking
        ToolCallTracker.clear()

        # 4. Context should be gone
        assert ToolCallTracker.get_current() is None


# =============================================================================
# E2E Test: Multiple Concurrent Approvals
# =============================================================================


class TestConcurrentApprovals:
    """Tests for concurrent approval requests."""

    @pytest.mark.asyncio
    async def test_concurrent_approvals_independent(self) -> None:
        """Multiple concurrent approval requests should be independent."""
        mock_client = MockACPClient()

        bridge = ACPApprovalBridge(
            session_id="concurrent_test",
            get_client=lambda: mock_client,
        )

        # Start two approval requests concurrently
        task1 = asyncio.create_task(
            bridge.request_approval(
                prompt="Request 1",
                options=["Yes", "No"],
                timeout=30.0,
                default="deny",
            )
        )
        task2 = asyncio.create_task(
            bridge.request_approval(
                prompt="Request 2",
                options=["Allow", "Deny"],
                timeout=30.0,
                default="deny",
            )
        )

        # Give tasks time to send requests
        await asyncio.sleep(0.01)

        # Both requests should be pending
        assert len(mock_client.pending_requests) == 2

        # Respond to them in reverse order
        mock_client.respond(request_id=1, option_id="opt_0")  # "Allow" for request 2
        mock_client.respond(request_id=0, option_id="opt_1")  # "No" for request 1

        result1 = await task1
        result2 = await task2

        # Each should get its own response
        assert result1 == "No"
        assert result2 == "Allow"
