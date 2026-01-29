"""Unit tests for hooks protocol module.

Tests the StreamingHook for event forwarding to clients.
Minimal mocking - tests real code paths where possible.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from amplifier_app_runtime.protocols.hooks import StreamingHook

# =============================================================================
# StreamingHook Initialization Tests
# =============================================================================


class TestStreamingHookInit:
    """Tests for StreamingHook initialization."""

    def test_init_defaults(self) -> None:
        """StreamingHook initializes with defaults."""
        hook = StreamingHook()
        assert hook._send is None
        assert hook._show_thinking is True
        assert hook._include_debug is False
        assert hook._current_blocks == {}

    def test_init_with_send_function(self) -> None:
        """StreamingHook accepts send function."""
        send_fn = AsyncMock()
        hook = StreamingHook(send_fn=send_fn)
        assert hook._send is send_fn

    def test_init_show_thinking_disabled(self) -> None:
        """StreamingHook can disable thinking events."""
        hook = StreamingHook(show_thinking=False)
        assert hook._show_thinking is False

    def test_init_include_debug(self) -> None:
        """StreamingHook can enable debug events."""
        hook = StreamingHook(include_debug=True)
        assert hook._include_debug is True

    def test_hook_has_name_and_priority(self) -> None:
        """StreamingHook has name and priority attributes."""
        assert StreamingHook.name == "streaming"
        assert StreamingHook.priority == 100


# =============================================================================
# StreamingHook Configuration Tests
# =============================================================================


class TestStreamingHookConfig:
    """Tests for StreamingHook configuration methods."""

    def test_set_show_thinking(self) -> None:
        """set_show_thinking updates thinking display setting."""
        hook = StreamingHook(show_thinking=True)
        hook.set_show_thinking(False)
        assert hook._show_thinking is False

    def test_set_include_debug(self) -> None:
        """set_include_debug updates debug event inclusion."""
        hook = StreamingHook(include_debug=False)
        hook.set_include_debug(True)
        assert hook._include_debug is True

    def test_set_send_function(self) -> None:
        """set_send_function updates send function."""
        hook = StreamingHook()
        send_fn = AsyncMock()
        hook.set_send_function(send_fn)
        assert hook._send is send_fn


# =============================================================================
# StreamingHook Call Tests
# =============================================================================


class TestStreamingHookCall:
    """Tests for StreamingHook __call__ method."""

    @pytest.mark.asyncio
    async def test_call_returns_continue_action(self) -> None:
        """Calling hook returns continue action."""
        hook = StreamingHook(send_fn=AsyncMock())
        result = await hook("content_block:delta", {"delta": "test"})
        assert result == {"action": "continue"}

    @pytest.mark.asyncio
    async def test_call_without_send_fn_returns_continue(self) -> None:
        """Calling hook without send function returns continue."""
        hook = StreamingHook()
        result = await hook("content_block:delta", {"delta": "test"})
        assert result == {"action": "continue"}

    @pytest.mark.asyncio
    async def test_call_sends_event(self) -> None:
        """Calling hook sends event via send function."""
        send_fn = AsyncMock()
        hook = StreamingHook(send_fn=send_fn)

        await hook("content_block:start", {"block_type": "text", "block_index": 0})

        send_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_handles_send_error(self) -> None:
        """Calling hook handles send errors gracefully."""
        send_fn = AsyncMock(side_effect=RuntimeError("Send failed"))
        hook = StreamingHook(send_fn=send_fn)

        # Should not raise
        result = await hook("content_block:delta", {"delta": "test"})
        assert result == {"action": "continue"}


# =============================================================================
# StreamingHook Content Block Events Tests
# =============================================================================


class TestStreamingHookContentBlocks:
    """Tests for content block event handling."""

    @pytest.mark.asyncio
    async def test_content_block_start_maps_type(self) -> None:
        """content_block:start maps to content_start."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append({"type": event.type, "props": event.properties})

        hook = StreamingHook(send_fn=capture)

        await hook("content_block:start", {"block_type": "text", "block_index": 0})

        assert len(events_sent) == 1
        assert events_sent[0]["props"]["type"] == "content_start"
        assert events_sent[0]["props"]["block_type"] == "text"

    @pytest.mark.asyncio
    async def test_content_block_delta_extracts_text(self) -> None:
        """content_block:delta extracts delta text."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        # Start block first
        await hook("content_block:start", {"block_type": "text", "block_index": 0})
        events_sent.clear()

        # Then delta
        await hook("content_block:delta", {"delta": {"text": "Hello"}, "block_index": 0})

        assert len(events_sent) == 1
        assert events_sent[0]["type"] == "content_delta"
        # Note: delta contains the sanitized original data due to **sanitized spread
        assert events_sent[0]["delta"] == {"text": "Hello"}

    @pytest.mark.asyncio
    async def test_content_block_end_extracts_content(self) -> None:
        """content_block:end extracts final content."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        # Start and end block
        await hook("content_block:start", {"block_type": "text", "block_index": 0})
        events_sent.clear()

        await hook(
            "content_block:end",
            {"block": {"text": "Complete content"}, "block_index": 0},
        )

        assert len(events_sent) == 1
        assert events_sent[0]["type"] == "content_end"
        assert events_sent[0]["content"] == "Complete content"

    @pytest.mark.asyncio
    async def test_tracks_block_types(self) -> None:
        """Hook tracks block types by index."""
        hook = StreamingHook(send_fn=AsyncMock())

        await hook("content_block:start", {"block_type": "text", "block_index": 0})
        await hook("content_block:start", {"block_type": "tool_use", "block_index": 1})

        assert hook._current_blocks[0] == "text"
        assert hook._current_blocks[1] == "tool_use"

    @pytest.mark.asyncio
    async def test_clears_block_on_end(self) -> None:
        """Hook clears block tracking on end."""
        hook = StreamingHook(send_fn=AsyncMock())

        await hook("content_block:start", {"block_type": "text", "block_index": 0})
        assert 0 in hook._current_blocks

        await hook("content_block:end", {"block_index": 0})
        assert 0 not in hook._current_blocks


# =============================================================================
# StreamingHook Thinking Events Tests
# =============================================================================


class TestStreamingHookThinking:
    """Tests for thinking event handling."""

    @pytest.mark.asyncio
    async def test_thinking_block_sent_when_enabled(self) -> None:
        """Thinking blocks sent when show_thinking=True."""
        events_sent: list[str] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties.get("type"))

        hook = StreamingHook(send_fn=capture, show_thinking=True)

        await hook("content_block:start", {"block_type": "thinking", "block_index": 0})

        assert "content_start" in events_sent

    @pytest.mark.asyncio
    async def test_thinking_block_skipped_when_disabled(self) -> None:
        """Thinking blocks skipped when show_thinking=False."""
        events_sent: list[str] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties.get("type"))

        hook = StreamingHook(send_fn=capture, show_thinking=False)

        await hook("content_block:start", {"block_type": "thinking", "block_index": 0})
        await hook("content_block:delta", {"delta": {"text": "..."}, "block_index": 0})
        await hook("content_block:end", {"block_index": 0})

        # Should not send any events for thinking blocks
        assert len(events_sent) == 0

    @pytest.mark.asyncio
    async def test_thinking_delta_event(self) -> None:
        """thinking:delta event sent when enabled."""
        events_sent: list[str] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties.get("type"))

        hook = StreamingHook(send_fn=capture, show_thinking=True)

        await hook("thinking:delta", {"thinking": "I am thinking..."})

        assert "thinking_delta" in events_sent

    @pytest.mark.asyncio
    async def test_thinking_delta_skipped_when_disabled(self) -> None:
        """thinking:delta skipped when show_thinking=False."""
        events_sent: list[str] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties.get("type"))

        hook = StreamingHook(send_fn=capture, show_thinking=False)

        await hook("thinking:delta", {"thinking": "I am thinking..."})

        assert len(events_sent) == 0


# =============================================================================
# StreamingHook Tool Events Tests
# =============================================================================


class TestStreamingHookTools:
    """Tests for tool event handling."""

    @pytest.mark.asyncio
    async def test_tool_pre_maps_to_tool_call(self) -> None:
        """tool:pre maps to tool_call message."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        await hook(
            "tool:pre",
            {
                "tool_name": "bash",
                "tool_call_id": "call_123",
                "tool_input": {"command": "ls"},
            },
        )

        assert len(events_sent) == 1
        assert events_sent[0]["type"] == "tool_call"
        assert events_sent[0]["tool_name"] == "bash"
        assert events_sent[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_tool_post_maps_to_tool_result(self) -> None:
        """tool:post maps to tool_result message."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        await hook(
            "tool:post",
            {
                "tool_name": "bash",
                "tool_call_id": "call_123",
                "result": {"output": "file.txt", "success": True},
            },
        )

        assert len(events_sent) == 1
        assert events_sent[0]["type"] == "tool_result"
        assert events_sent[0]["tool_name"] == "bash"
        assert events_sent[0]["success"] is True

    @pytest.mark.asyncio
    async def test_tool_error_event(self) -> None:
        """tool:error maps to tool_error message."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        await hook("tool:error", {"tool_name": "bash", "error": "Command failed"})

        assert len(events_sent) == 1
        assert events_sent[0]["type"] == "tool_error"


# =============================================================================
# StreamingHook Sanitization Tests
# =============================================================================


class TestStreamingHookSanitization:
    """Tests for data sanitization."""

    @pytest.mark.asyncio
    async def test_sanitizes_image_data(self) -> None:
        """Large image data is sanitized."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        # Send event with large base64 image
        large_image = "a" * 2000  # > 1000 chars
        await hook(
            "content_block:start",
            {
                "block_type": "text",
                "block_index": 0,
                "image": {"type": "base64", "data": large_image},
            },
        )

        # Image should be sanitized
        assert len(events_sent) == 1
        image_data = events_sent[0].get("image", {})
        if image_data:
            assert image_data.get("data") == "[image data omitted]"

    def test_sanitize_preserves_normal_data(self) -> None:
        """Sanitization preserves normal data."""
        hook = StreamingHook()

        data = {
            "text": "Hello world",
            "number": 42,
            "nested": {"key": "value"},
        }

        sanitized = hook._sanitize_for_transport(data)

        assert sanitized["text"] == "Hello world"
        assert sanitized["number"] == 42
        assert sanitized["nested"]["key"] == "value"


# =============================================================================
# StreamingHook Integration Tests
# =============================================================================


class TestStreamingHookIntegration:
    """Integration-style tests for complete flows."""

    @pytest.mark.asyncio
    async def test_full_content_stream(self) -> None:
        """Test complete content streaming flow."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        # Simulate full streaming
        await hook("content_block:start", {"block_type": "text", "block_index": 0})
        await hook("content_block:delta", {"delta": {"text": "Hello"}, "block_index": 0})
        await hook("content_block:delta", {"delta": {"text": " World"}, "block_index": 0})
        await hook("content_block:end", {"block": {"text": "Hello World"}, "block_index": 0})

        assert len(events_sent) == 4
        assert events_sent[0]["type"] == "content_start"
        assert events_sent[1]["type"] == "content_delta"
        # Note: delta contains sanitized original data due to **sanitized spread
        assert events_sent[1]["delta"] == {"text": "Hello"}
        assert events_sent[2]["type"] == "content_delta"
        assert events_sent[2]["delta"] == {"text": " World"}
        assert events_sent[3]["type"] == "content_end"
        assert events_sent[3]["content"] == "Hello World"

    @pytest.mark.asyncio
    async def test_tool_call_flow(self) -> None:
        """Test complete tool call flow."""
        events_sent: list[dict[str, Any]] = []

        async def capture(event: Any) -> None:
            events_sent.append(event.properties)

        hook = StreamingHook(send_fn=capture)

        # Tool call then result
        await hook(
            "tool:pre",
            {"tool_name": "bash", "tool_call_id": "123", "tool_input": {"command": "ls"}},
        )
        await hook(
            "tool:post",
            {"tool_name": "bash", "tool_call_id": "123", "result": {"output": "files"}},
        )

        assert len(events_sent) == 2
        assert events_sent[0]["type"] == "tool_call"
        assert events_sent[1]["type"] == "tool_result"
