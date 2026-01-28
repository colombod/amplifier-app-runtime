"""Unit tests for streaming protocol.

Tests the ServerStreamingHook for forwarding events to clients.
Minimal mocking - tests real code paths where possible.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_server_app.protocols.streaming import (
    DEFAULT_EVENTS_TO_CAPTURE,
    ServerStreamingHook,
    get_events_to_capture,
    register_streaming_hook,
)

# =============================================================================
# ServerStreamingHook Tests
# =============================================================================


class TestServerStreamingHook:
    """Tests for ServerStreamingHook - event forwarding."""

    def test_init_defaults(self) -> None:
        """ServerStreamingHook initializes with defaults."""
        hook = ServerStreamingHook()
        assert hook._send_fn is None
        assert hook._show_thinking is True
        assert hook._sequence == 0

    def test_init_with_send_function(self) -> None:
        """ServerStreamingHook accepts send function."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn)
        assert hook._send_fn is send_fn

    def test_init_with_show_thinking_disabled(self) -> None:
        """ServerStreamingHook can disable thinking events."""
        hook = ServerStreamingHook(show_thinking=False)
        assert hook._show_thinking is False

    def test_set_send_fn(self) -> None:
        """set_send_fn updates send function."""
        hook = ServerStreamingHook()
        assert hook._send_fn is None

        send_fn = AsyncMock()
        hook.set_send_fn(send_fn)
        assert hook._send_fn is send_fn

    def test_reset_sequence(self) -> None:
        """reset_sequence resets counter to zero."""
        hook = ServerStreamingHook()
        hook._sequence = 10
        hook.reset_sequence()
        assert hook._sequence == 0

    @pytest.mark.asyncio
    async def test_call_with_no_send_fn_returns_empty(self) -> None:
        """Calling hook without send function returns empty dict."""
        hook = ServerStreamingHook()
        result = await hook("content_block:delta", {"delta": "test"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_call_increments_sequence(self) -> None:
        """Calling hook increments sequence number."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn)

        await hook("content_block:delta", {"delta": "test"})
        assert hook._sequence == 1

        await hook("content_block:delta", {"delta": "more"})
        assert hook._sequence == 2

    @pytest.mark.asyncio
    async def test_call_sends_event_with_correct_type(self) -> None:
        """Calling hook sends event with correct type."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn)

        await hook("content_block:delta", {"delta": "hello"})

        send_fn.assert_called_once()
        event = send_fn.call_args[0][0]
        assert event.type == "content_block:delta"

    @pytest.mark.asyncio
    async def test_call_sends_event_with_sequence(self) -> None:
        """Calling hook includes sequence in event."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn)

        await hook("content_block:start", {"block_type": "text"})

        event = send_fn.call_args[0][0]
        assert event.sequence == 0

    @pytest.mark.asyncio
    async def test_call_sends_event_properties(self) -> None:
        """Calling hook passes through event properties."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn)

        await hook("content_block:delta", {"delta": "hello", "block_index": 0})

        event = send_fn.call_args[0][0]
        assert event.properties["delta"] == "hello"
        assert event.properties["block_index"] == 0

    @pytest.mark.asyncio
    async def test_call_skips_thinking_when_disabled(self) -> None:
        """Calling hook skips thinking events when show_thinking=False."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn, show_thinking=False)

        await hook("thinking:delta", {"thinking": "I am thinking..."})

        send_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_allows_thinking_when_enabled(self) -> None:
        """Calling hook allows thinking events when show_thinking=True."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn, show_thinking=True)

        await hook("thinking:delta", {"thinking": "I am thinking..."})

        send_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_handles_send_error_gracefully(self) -> None:
        """Calling hook handles send errors without raising."""
        send_fn = AsyncMock(side_effect=RuntimeError("Send failed"))
        hook = ServerStreamingHook(send_fn=send_fn)

        # Should not raise
        result = await hook("content_block:delta", {"delta": "test"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_call_returns_empty_dict(self) -> None:
        """Calling hook always returns empty dict (doesn't modify event flow)."""
        send_fn = AsyncMock()
        hook = ServerStreamingHook(send_fn=send_fn)

        result = await hook("content_block:delta", {"delta": "test"})
        assert result == {}


class TestServerStreamingHookIntegration:
    """Integration-style tests for ServerStreamingHook."""

    @pytest.mark.asyncio
    async def test_full_streaming_flow(self) -> None:
        """Test complete streaming flow with multiple events."""
        events_sent: list[dict[str, Any]] = []

        async def capture_events(event: Any) -> None:
            events_sent.append({"type": event.type, "seq": event.sequence})

        hook = ServerStreamingHook(send_fn=capture_events)

        # Simulate streaming flow
        await hook("content_block:start", {"block_type": "text", "block_index": 0})
        await hook("content_block:delta", {"delta": "Hello"})
        await hook("content_block:delta", {"delta": " World"})
        await hook("content_block:end", {"block": {"text": "Hello World"}})

        assert len(events_sent) == 4
        assert events_sent[0] == {"type": "content_block:start", "seq": 0}
        assert events_sent[1] == {"type": "content_block:delta", "seq": 1}
        assert events_sent[2] == {"type": "content_block:delta", "seq": 2}
        assert events_sent[3] == {"type": "content_block:end", "seq": 3}

    @pytest.mark.asyncio
    async def test_sequence_reset_between_prompts(self) -> None:
        """Test sequence reset for new prompts."""
        events_sent: list[int] = []

        async def capture_sequence(event: Any) -> None:
            events_sent.append(event.sequence)

        hook = ServerStreamingHook(send_fn=capture_sequence)

        # First prompt
        await hook("content_block:start", {})
        await hook("content_block:end", {})

        # Reset for new prompt
        hook.reset_sequence()

        # Second prompt
        await hook("content_block:start", {})
        await hook("content_block:end", {})

        assert events_sent == [0, 1, 0, 1]


# =============================================================================
# get_events_to_capture Tests
# =============================================================================


class TestGetEventsToCapture:
    """Tests for get_events_to_capture function."""

    def test_returns_list(self) -> None:
        """get_events_to_capture returns a list."""
        result = get_events_to_capture()
        assert isinstance(result, list)

    def test_contains_core_events(self) -> None:
        """get_events_to_capture includes core streaming events."""
        result = get_events_to_capture()

        # Must have content streaming events
        assert "content_block:start" in result
        assert "content_block:delta" in result
        assert "content_block:end" in result

        # Must have tool events
        assert "tool:pre" in result
        assert "tool:post" in result

    def test_default_list_has_events(self) -> None:
        """DEFAULT_EVENTS_TO_CAPTURE has expected events."""
        assert len(DEFAULT_EVENTS_TO_CAPTURE) > 10

        # Check categories
        assert "content_block:start" in DEFAULT_EVENTS_TO_CAPTURE
        assert "thinking:delta" in DEFAULT_EVENTS_TO_CAPTURE
        assert "tool:pre" in DEFAULT_EVENTS_TO_CAPTURE
        assert "session:start" in DEFAULT_EVENTS_TO_CAPTURE
        assert "approval:required" in DEFAULT_EVENTS_TO_CAPTURE


# =============================================================================
# register_streaming_hook Tests
# =============================================================================


class TestRegisterStreamingHook:
    """Tests for register_streaming_hook function."""

    def test_registers_hook_for_events(self) -> None:
        """register_streaming_hook registers hook for each event."""
        registered_events: list[str] = []

        mock_hook_registry = MagicMock()

        def capture_register(event, handler, priority, name):
            registered_events.append(event)

        mock_hook_registry.register = capture_register

        mock_session = MagicMock()
        mock_session.coordinator.hooks = mock_hook_registry
        mock_session.coordinator.get_capability.return_value = None

        hook = ServerStreamingHook()
        count = register_streaming_hook(mock_session, hook)

        assert count > 0
        assert len(registered_events) == count

    def test_returns_zero_with_no_hook_registry(self) -> None:
        """register_streaming_hook returns 0 if session has no hooks."""
        mock_session = MagicMock()
        mock_session.coordinator.hooks = None

        hook = ServerStreamingHook()
        count = register_streaming_hook(mock_session, hook)

        assert count == 0

    def test_includes_discovered_events(self) -> None:
        """register_streaming_hook includes auto-discovered events."""
        registered_events: list[str] = []

        mock_hook_registry = MagicMock()
        mock_hook_registry.register = (
            lambda event, handler, priority, name: registered_events.append(event)
        )

        mock_session = MagicMock()
        mock_session.coordinator.hooks = mock_hook_registry
        mock_session.coordinator.get_capability.return_value = [
            "custom:event1",
            "custom:event2",
        ]

        hook = ServerStreamingHook()
        register_streaming_hook(mock_session, hook)

        assert "custom:event1" in registered_events
        assert "custom:event2" in registered_events

    def test_registers_with_priority_100(self) -> None:
        """register_streaming_hook uses priority 100."""
        captured_priority = None

        mock_hook_registry = MagicMock()

        def capture_register(event, handler, priority, name):
            nonlocal captured_priority
            captured_priority = priority

        mock_hook_registry.register = capture_register

        mock_session = MagicMock()
        mock_session.coordinator.hooks = mock_hook_registry
        mock_session.coordinator.get_capability.return_value = None

        hook = ServerStreamingHook()
        register_streaming_hook(mock_session, hook)

        assert captured_priority == 100

    def test_uses_server_streaming_prefix(self) -> None:
        """register_streaming_hook uses 'server-streaming:' name prefix."""
        captured_names: list[str] = []

        mock_hook_registry = MagicMock()

        def capture_register(event, handler, priority, name):
            captured_names.append(name)

        mock_hook_registry.register = capture_register

        mock_session = MagicMock()
        mock_session.coordinator.hooks = mock_hook_registry
        mock_session.coordinator.get_capability.return_value = None

        hook = ServerStreamingHook()
        register_streaming_hook(mock_session, hook)

        for name in captured_names:
            assert name.startswith("server-streaming:")
