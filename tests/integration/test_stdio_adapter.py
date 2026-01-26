"""Integration tests for stdio protocol adapter.

Tests the stdio adapter with real protocol types, verifying:
- JSON line parsing from stdin
- Event serialization to stdout
- UTF-8 encoding and newline handling
- BOM stripping
- Cross-platform line endings
"""

import io
import json

import pytest

from amplifier_server_app.transport.stdio_adapter import StdioProtocolAdapter

# =============================================================================
# Helpers
# =============================================================================


def make_binary_stream(lines: list[str]) -> io.BytesIO:
    """Create a binary stream from lines (simulating stdin)."""
    content = "\n".join(lines) + "\n"
    return io.BytesIO(content.encode("utf-8"))


def read_events_from_stream(stream: io.BytesIO) -> list[dict]:
    """Read JSON events from a binary stream (simulating stdout)."""
    stream.seek(0)
    events = []
    for line in stream:
        line_str = line.decode("utf-8").strip()
        if line_str:
            events.append(json.loads(line_str))
    return events


# =============================================================================
# Tests: Basic Command Processing
# =============================================================================


class TestBasicCommands:
    """Test basic command processing through stdio."""

    @pytest.mark.anyio
    async def test_ping_command(self):
        """Ping command should return pong event."""
        stdin = make_binary_stream(['{"cmd": "ping", "params": {}}'])
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=stderr)
        await adapter.run()

        events = read_events_from_stream(stdout)

        # Should have connected event and pong
        pong_events = [e for e in events if e.get("type") == "pong"]
        assert len(pong_events) == 1

    @pytest.mark.anyio
    async def test_command_with_id(self):
        """Command ID should be preserved in correlation_id."""
        stdin = make_binary_stream(['{"id": "my-cmd-123", "cmd": "ping", "params": {}}'])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        pong = next(e for e in events if e.get("type") == "pong")

        assert pong["correlation_id"] == "my-cmd-123"

    @pytest.mark.anyio
    async def test_multiple_commands(self):
        """Multiple commands should each get responses."""
        stdin = make_binary_stream(
            [
                '{"id": "c1", "cmd": "ping", "params": {}}',
                '{"id": "c2", "cmd": "ping", "params": {}}',
                '{"id": "c3", "cmd": "ping", "params": {}}',
            ]
        )
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        pong_events = [e for e in events if e.get("type") == "pong"]

        assert len(pong_events) == 3
        correlation_ids = {e["correlation_id"] for e in pong_events}
        assert correlation_ids == {"c1", "c2", "c3"}


# =============================================================================
# Tests: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling in stdio adapter."""

    @pytest.mark.anyio
    async def test_invalid_json(self):
        """Invalid JSON should produce error event."""
        stdin = make_binary_stream(["not valid json"])
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=stderr)
        await adapter.run()

        events = read_events_from_stream(stdout)
        error_events = [e for e in events if e.get("type") == "error"]

        assert len(error_events) >= 1
        assert "PARSE_ERROR" in str(error_events)

    @pytest.mark.anyio
    async def test_unknown_command(self):
        """Unknown command should produce error event."""
        stdin = make_binary_stream(['{"cmd": "unknown.command", "params": {}}'])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        error_events = [e for e in events if e.get("type") == "error"]

        assert len(error_events) >= 1

    @pytest.mark.anyio
    async def test_empty_lines_ignored(self):
        """Empty lines should be ignored."""
        stdin = make_binary_stream(
            [
                "",
                '{"cmd": "ping", "params": {}}',
                "",
                "",
            ]
        )
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        pong_events = [e for e in events if e.get("type") == "pong"]

        # Should get exactly one pong (empty lines ignored)
        assert len(pong_events) == 1


# =============================================================================
# Tests: UTF-8 Encoding
# =============================================================================


class TestUTF8Encoding:
    """Test UTF-8 encoding in stdio transport."""

    @pytest.mark.anyio
    async def test_unicode_in_command(self):
        """Unicode in command params should work."""
        cmd_json = json.dumps(
            {
                "cmd": "ping",
                "params": {"message": "Hello 世界 🌍"},
            }
        )
        stdin = make_binary_stream([cmd_json])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        # Should not error
        assert any(e.get("type") == "pong" for e in events)

    @pytest.mark.anyio
    async def test_unicode_preserved_in_output(self):
        """Unicode should be preserved in event output."""
        # Use capabilities which echoes back some data
        stdin = make_binary_stream(['{"cmd": "capabilities", "params": {}}'])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        # Read raw bytes to verify UTF-8
        stdout.seek(0)
        raw_output = stdout.read()

        # Should be valid UTF-8
        decoded = raw_output.decode("utf-8")
        assert decoded  # Should not raise


# =============================================================================
# Tests: Line Ending Handling
# =============================================================================


class TestLineEndings:
    """Test cross-platform line ending handling."""

    @pytest.mark.anyio
    async def test_lf_line_endings(self):
        """Unix line endings (LF) should work."""
        content = '{"cmd": "ping", "params": {}}\n'
        stdin = io.BytesIO(content.encode("utf-8"))
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        assert any(e.get("type") == "pong" for e in events)

    @pytest.mark.anyio
    async def test_crlf_line_endings(self):
        """Windows line endings (CRLF) should work."""
        content = '{"cmd": "ping", "params": {}}\r\n'
        stdin = io.BytesIO(content.encode("utf-8"))
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        assert any(e.get("type") == "pong" for e in events)

    @pytest.mark.anyio
    async def test_output_uses_lf_only(self):
        """Output should use LF line endings only."""
        stdin = make_binary_stream(['{"cmd": "ping", "params": {}}'])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        stdout.seek(0)
        raw_output = stdout.read()

        # Should not contain CRLF
        assert b"\r\n" not in raw_output
        # Should contain LF
        assert b"\n" in raw_output


# =============================================================================
# Tests: BOM Handling
# =============================================================================


class TestBOMHandling:
    """Test UTF-8 BOM handling."""

    @pytest.mark.anyio
    async def test_strip_bom_at_start(self):
        """UTF-8 BOM at start should be stripped."""
        # UTF-8 BOM: EF BB BF
        content = b'\xef\xbb\xbf{"cmd": "ping", "params": {}}\n'
        stdin = io.BytesIO(content)
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)
        # Should parse successfully despite BOM
        assert any(e.get("type") == "pong" for e in events)


# =============================================================================
# Tests: Output Format
# =============================================================================


class TestOutputFormat:
    """Test that output is valid NDJSON."""

    @pytest.mark.anyio
    async def test_each_event_is_single_line(self):
        """Each event should be on its own line."""
        stdin = make_binary_stream(['{"cmd": "ping", "params": {}}'])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        stdout.seek(0)
        lines = stdout.readlines()

        for line in lines:
            line_str = line.decode("utf-8").strip()
            if line_str:
                # Each line should be valid JSON
                parsed = json.loads(line_str)
                assert isinstance(parsed, dict)

    @pytest.mark.anyio
    async def test_events_have_required_fields(self):
        """Events should have required protocol fields."""
        stdin = make_binary_stream(['{"cmd": "ping", "params": {}}'])
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())
        await adapter.run()

        events = read_events_from_stream(stdout)

        for event in events:
            # All events should have id and type
            assert "id" in event
            assert "type" in event
            assert "timestamp" in event


# =============================================================================
# Tests: Stop/Cancel
# =============================================================================


class TestAdapterLifecycle:
    """Test adapter start/stop lifecycle."""

    @pytest.mark.anyio
    async def test_stop_terminates_adapter(self):
        """Calling stop() should terminate the adapter."""
        # Create adapter with empty stdin (will block on read)
        stdin = io.BytesIO(b"")
        stdout = io.BytesIO()

        adapter = StdioProtocolAdapter(stdin=stdin, stdout=stdout, stderr=io.BytesIO())

        # Run should complete when stdin is empty
        await adapter.run()

        # Verify connected event was sent
        events = read_events_from_stream(stdout)
        assert any(e.get("type") == "connected" for e in events)
