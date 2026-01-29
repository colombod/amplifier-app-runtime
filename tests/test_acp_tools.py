"""Tests for ACP client-side tools.

Tests the ide_terminal, ide_read_file, and ide_write_file tools
that execute operations on the IDE's machine via ACP protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_app_runtime.acp.tools import (
    IdeReadFileTool,
    IdeTerminalTool,
    IdeWriteFileTool,
    create_acp_tools,
    register_acp_tools,
)

# ============================================================================
# Mock Client for Testing
# ============================================================================


@dataclass
class MockTerminalResult:
    """Mock result from terminal/create."""

    terminal_id: str


@dataclass
class MockExitResult:
    """Mock result from terminal/wait_for_exit."""

    exit_code: int
    signal: str | None = None


@dataclass
class MockOutputResult:
    """Mock result from terminal/output."""

    output: str
    truncated: bool = False


@dataclass
class MockReadFileResult:
    """Mock result from fs/read_text_file."""

    content: str


class MockAcpClient:
    """Mock ACP client for testing IDE tools.

    Simulates the ACP Client's terminal and filesystem methods.
    """

    def __init__(self) -> None:
        self.terminals: dict[str, dict[str, Any]] = {}
        self.files: dict[str, str] = {}  # path -> content (simulates unsaved buffers)
        self.disk_files: dict[str, str] = {}  # path -> content (simulates disk)
        self._terminal_counter = 0

        # Track method calls for assertions
        self.create_terminal_calls: list[dict[str, Any]] = []
        self.wait_for_exit_calls: list[dict[str, Any]] = []
        self.terminal_output_calls: list[dict[str, Any]] = []
        self.release_terminal_calls: list[dict[str, Any]] = []
        self.kill_terminal_calls: list[dict[str, Any]] = []
        self.read_text_file_calls: list[dict[str, Any]] = []
        self.write_text_file_calls: list[dict[str, Any]] = []

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> MockTerminalResult:
        """Simulate terminal/create."""
        self._terminal_counter += 1
        terminal_id = f"mock_term_{self._terminal_counter}"

        self.terminals[terminal_id] = {
            "command": command,
            "args": args or [],
            "cwd": cwd,
            "env": env,
            "session_id": session_id,
            "output": f"Mock output for: {command} {' '.join(args or [])}\n",
            "exit_code": 0,
        }

        self.create_terminal_calls.append(
            {
                "session_id": session_id,
                "command": command,
                "args": args,
                "cwd": cwd,
                "env": env,
            }
        )

        return MockTerminalResult(terminal_id=terminal_id)

    async def wait_for_terminal_exit(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> MockExitResult:
        """Simulate terminal/wait_for_exit."""
        self.wait_for_exit_calls.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )

        terminal = self.terminals.get(terminal_id, {})
        return MockExitResult(
            exit_code=terminal.get("exit_code", 0),
            signal=terminal.get("signal"),
        )

    async def terminal_output(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> MockOutputResult:
        """Simulate terminal/output."""
        self.terminal_output_calls.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )

        terminal = self.terminals.get(terminal_id, {})
        return MockOutputResult(
            output=terminal.get("output", ""),
            truncated=terminal.get("truncated", False),
        )

    async def release_terminal(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> None:
        """Simulate terminal/release."""
        self.release_terminal_calls.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )
        # Remove terminal from tracking
        self.terminals.pop(terminal_id, None)

    async def kill_terminal(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> None:
        """Simulate terminal/kill."""
        self.kill_terminal_calls.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )
        # Mark as killed
        if terminal_id in self.terminals:
            self.terminals[terminal_id]["exit_code"] = -9
            self.terminals[terminal_id]["signal"] = "SIGKILL"

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> MockReadFileResult:
        """Simulate fs/read_text_file.

        Returns buffer content if exists, else disk content.
        """
        self.read_text_file_calls.append(
            {
                "session_id": session_id,
                "path": path,
                "line": line,
                "limit": limit,
            }
        )

        # Return buffer content (unsaved) if exists, else disk content
        content = self.files.get(path) or self.disk_files.get(path, "")
        return MockReadFileResult(content=content)

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        """Simulate fs/write_text_file."""
        self.write_text_file_calls.append(
            {
                "session_id": session_id,
                "path": path,
                "content": content,
            }
        )
        # Write to "disk"
        self.disk_files[path] = content

    # Helper methods for test setup

    def set_unsaved_buffer(self, path: str, content: str) -> None:
        """Simulate user editing a file without saving."""
        self.files[path] = content

    def set_disk_file(self, path: str, content: str) -> None:
        """Set file content on "disk"."""
        self.disk_files[path] = content

    def set_terminal_output(self, terminal_id: str, output: str, exit_code: int = 0) -> None:
        """Configure what a terminal will return."""
        if terminal_id in self.terminals:
            self.terminals[terminal_id]["output"] = output
            self.terminals[terminal_id]["exit_code"] = exit_code


# ============================================================================
# Mock Client Capabilities
# ============================================================================


@dataclass
class MockFsCapabilities:
    """Mock filesystem capabilities.

    Note: Field names use camelCase to match ACP protocol schema.
    """

    readTextFile: bool = False  # noqa: N815
    writeTextFile: bool = False  # noqa: N815


@dataclass
class MockClientCapabilities:
    """Mock client capabilities for testing."""

    terminal: bool = False
    fs: MockFsCapabilities | None = None


# ============================================================================
# Tests: IdeTerminalTool
# ============================================================================


class TestIdeTerminalTool:
    """Tests for IdeTerminalTool."""

    @pytest.fixture
    def mock_client(self) -> MockAcpClient:
        return MockAcpClient()

    @pytest.fixture
    def tool(self, mock_client: MockAcpClient) -> IdeTerminalTool:
        return IdeTerminalTool(
            get_client=lambda: mock_client,
            session_id="test_session",
        )

    @pytest.mark.asyncio
    async def test_execute_simple_command(
        self, tool: IdeTerminalTool, mock_client: MockAcpClient
    ) -> None:
        """Test executing a simple command."""
        result = await tool.execute({"command": "echo", "args": ["hello"]})

        assert result.success is True
        assert "echo" in result.output
        assert result.metadata["exit_code"] == 0

        # Verify protocol flow
        assert len(mock_client.create_terminal_calls) == 1
        assert mock_client.create_terminal_calls[0]["command"] == "echo"
        assert mock_client.create_terminal_calls[0]["args"] == ["hello"]

        assert len(mock_client.wait_for_exit_calls) == 1
        assert len(mock_client.terminal_output_calls) == 1
        assert len(mock_client.release_terminal_calls) == 1

    @pytest.mark.asyncio
    async def test_execute_with_cwd_and_env(
        self, tool: IdeTerminalTool, mock_client: MockAcpClient
    ) -> None:
        """Test executing with working directory and environment."""
        result = await tool.execute(
            {
                "command": "npm",
                "args": ["test"],
                "cwd": "/home/user/project",
                "env": {"NODE_ENV": "test"},
            }
        )

        assert result.success is True

        call = mock_client.create_terminal_calls[0]
        assert call["cwd"] == "/home/user/project"
        assert call["env"] == [{"name": "NODE_ENV", "value": "test"}]

    @pytest.mark.asyncio
    async def test_execute_no_client(self) -> None:
        """Test behavior when client is not connected."""
        tool = IdeTerminalTool(
            get_client=lambda: None,
            session_id="test_session",
        )

        result = await tool.execute({"command": "echo"})

        assert result.success is False
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_missing_command(
        self, tool: IdeTerminalTool, mock_client: MockAcpClient
    ) -> None:
        """Test error when command is missing."""
        result = await tool.execute({})

        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_terminal_always_released(
        self, tool: IdeTerminalTool, mock_client: MockAcpClient
    ) -> None:
        """Test that terminal is released even on error."""

        # Make wait_for_exit raise an exception
        async def failing_wait(*args: Any, **kwargs: Any) -> MockExitResult:
            raise RuntimeError("Simulated error")

        mock_client.wait_for_terminal_exit = failing_wait  # type: ignore[method-assign]

        result = await tool.execute({"command": "test"})

        assert result.success is False
        # Terminal should still be released
        assert len(mock_client.release_terminal_calls) == 1

    @pytest.mark.asyncio
    async def test_tool_has_correct_metadata(self, tool: IdeTerminalTool) -> None:
        """Test that tool has correct name and description."""
        assert tool.name == "ide_terminal"
        assert "IDE" in tool.description or "ide" in tool.description.lower()
        assert "client" in tool.description.lower() or "user" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_parameters_schema(self, tool: IdeTerminalTool) -> None:
        """Test that parameters schema is correct."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "command" in params["properties"]
        assert "command" in params["required"]


# ============================================================================
# Tests: IdeReadFileTool
# ============================================================================


class TestIdeReadFileTool:
    """Tests for IdeReadFileTool."""

    @pytest.fixture
    def mock_client(self) -> MockAcpClient:
        return MockAcpClient()

    @pytest.fixture
    def tool(self, mock_client: MockAcpClient) -> IdeReadFileTool:
        return IdeReadFileTool(
            get_client=lambda: mock_client,
            session_id="test_session",
        )

    @pytest.mark.asyncio
    async def test_read_file_from_disk(
        self, tool: IdeReadFileTool, mock_client: MockAcpClient
    ) -> None:
        """Test reading a file that exists on disk."""
        mock_client.set_disk_file("/home/user/file.txt", "disk content")

        result = await tool.execute({"path": "/home/user/file.txt"})

        assert result.success is True
        assert result.output == "disk content"

    @pytest.mark.asyncio
    async def test_read_unsaved_buffer(
        self, tool: IdeReadFileTool, mock_client: MockAcpClient
    ) -> None:
        """Test that unsaved buffer content is returned over disk content."""
        mock_client.set_disk_file("/home/user/file.txt", "saved on disk")
        mock_client.set_unsaved_buffer("/home/user/file.txt", "unsaved changes!")

        result = await tool.execute({"path": "/home/user/file.txt"})

        assert result.success is True
        assert result.output == "unsaved changes!"
        assert result.output != "saved on disk"

    @pytest.mark.asyncio
    async def test_read_no_client(self) -> None:
        """Test behavior when client is not connected."""
        tool = IdeReadFileTool(
            get_client=lambda: None,
            session_id="test_session",
        )

        result = await tool.execute({"path": "/some/file"})

        assert result.success is False
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_missing_path(
        self, tool: IdeReadFileTool, mock_client: MockAcpClient
    ) -> None:
        """Test error when path is missing."""
        result = await tool.execute({})

        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tool_has_correct_metadata(self, tool: IdeReadFileTool) -> None:
        """Test that tool has correct name and description."""
        assert tool.name == "ide_read_file"
        assert "unsaved" in tool.description.lower() or "buffer" in tool.description.lower()


# ============================================================================
# Tests: IdeWriteFileTool
# ============================================================================


class TestIdeWriteFileTool:
    """Tests for IdeWriteFileTool."""

    @pytest.fixture
    def mock_client(self) -> MockAcpClient:
        return MockAcpClient()

    @pytest.fixture
    def tool(self, mock_client: MockAcpClient) -> IdeWriteFileTool:
        return IdeWriteFileTool(
            get_client=lambda: mock_client,
            session_id="test_session",
        )

    @pytest.mark.asyncio
    async def test_write_file(self, tool: IdeWriteFileTool, mock_client: MockAcpClient) -> None:
        """Test writing a file."""
        result = await tool.execute(
            {
                "path": "/home/user/new_file.txt",
                "content": "new content",
            }
        )

        assert result.success is True
        assert mock_client.disk_files["/home/user/new_file.txt"] == "new content"
        assert result.metadata["bytes_written"] == len("new content")

    @pytest.mark.asyncio
    async def test_write_no_client(self) -> None:
        """Test behavior when client is not connected."""
        tool = IdeWriteFileTool(
            get_client=lambda: None,
            session_id="test_session",
        )

        result = await tool.execute({"path": "/some/file", "content": "test"})

        assert result.success is False
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_missing_path(
        self, tool: IdeWriteFileTool, mock_client: MockAcpClient
    ) -> None:
        """Test error when path is missing."""
        result = await tool.execute({"content": "test"})

        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_missing_content(
        self, tool: IdeWriteFileTool, mock_client: MockAcpClient
    ) -> None:
        """Test error when content is missing."""
        result = await tool.execute({"path": "/some/file"})

        assert result.success is False
        assert "required" in result.error.lower()


# ============================================================================
# Tests: Tool Factory and Registration
# ============================================================================


class TestToolFactory:
    """Tests for create_acp_tools factory."""

    def test_create_tools_no_capabilities(self) -> None:
        """Test creating tools without capabilities."""
        tools = create_acp_tools(
            get_client=lambda: None,
            session_id="test",
            client_capabilities=None,
        )

        # Should return tools but none should be registered
        assert len(tools) == 3
        for _tool, should_register in tools:
            assert should_register is False

    def test_create_tools_with_terminal(self) -> None:
        """Test creating tools with terminal capability."""
        caps = MockClientCapabilities(terminal=True)
        tools = create_acp_tools(
            get_client=lambda: None,
            session_id="test",
            client_capabilities=caps,
        )

        tool_dict = {t.name: should for t, should in tools}
        assert tool_dict["ide_terminal"] is True
        assert tool_dict["ide_read_file"] is False
        assert tool_dict["ide_write_file"] is False

    def test_create_tools_with_filesystem(self) -> None:
        """Test creating tools with filesystem capabilities."""
        caps = MockClientCapabilities(
            terminal=False,
            fs=MockFsCapabilities(readTextFile=True, writeTextFile=True),
        )
        tools = create_acp_tools(
            get_client=lambda: None,
            session_id="test",
            client_capabilities=caps,
        )

        tool_dict = {t.name: should for t, should in tools}
        assert tool_dict["ide_terminal"] is False
        assert tool_dict["ide_read_file"] is True
        assert tool_dict["ide_write_file"] is True

    def test_create_tools_with_all_capabilities(self) -> None:
        """Test creating tools with all capabilities."""
        caps = MockClientCapabilities(
            terminal=True,
            fs=MockFsCapabilities(readTextFile=True, writeTextFile=True),
        )
        tools = create_acp_tools(
            get_client=lambda: None,
            session_id="test",
            client_capabilities=caps,
        )

        tool_dict = {t.name: should for t, should in tools}
        assert tool_dict["ide_terminal"] is True
        assert tool_dict["ide_read_file"] is True
        assert tool_dict["ide_write_file"] is True


class TestToolRegistration:
    """Tests for register_acp_tools function."""

    @pytest.mark.asyncio
    async def test_register_with_mock_coordinator(self) -> None:
        """Test registering tools with a mock coordinator."""
        # Create mock session with coordinator
        mock_coordinator = MagicMock()
        mock_coordinator.mount = AsyncMock()
        mock_coordinator.register_capability = MagicMock()

        mock_session = MagicMock()
        mock_session.coordinator = mock_coordinator

        caps = MockClientCapabilities(
            terminal=True,
            fs=MockFsCapabilities(readTextFile=True, writeTextFile=False),
        )

        registered = await register_acp_tools(
            session=mock_session,
            get_client=lambda: None,
            session_id="test",
            client_capabilities=caps,
        )

        # Should register terminal and read, but not write
        assert "ide_terminal" in registered
        assert "ide_read_file" in registered
        assert "ide_write_file" not in registered

        # Verify mount was called for each registered tool
        assert mock_coordinator.mount.call_count == 2

    @pytest.mark.asyncio
    async def test_register_no_capabilities(self) -> None:
        """Test that no tools are registered without capabilities."""
        mock_coordinator = MagicMock()
        mock_coordinator.mount = AsyncMock()
        mock_coordinator.register_capability = MagicMock()

        mock_session = MagicMock()
        mock_session.coordinator = mock_coordinator

        registered = await register_acp_tools(
            session=mock_session,
            get_client=lambda: None,
            session_id="test",
            client_capabilities=None,
        )

        assert len(registered) == 0
        mock_coordinator.mount.assert_not_called()


# ============================================================================
# Integration-style Tests
# ============================================================================


class TestToolIntegration:
    """Integration-style tests for the complete tool flow."""

    @pytest.fixture
    def mock_client(self) -> MockAcpClient:
        return MockAcpClient()

    @pytest.mark.asyncio
    async def test_terminal_full_workflow(self, mock_client: MockAcpClient) -> None:
        """Test the full terminal workflow: create -> wait -> output -> release."""
        tool = IdeTerminalTool(
            get_client=lambda: mock_client,
            session_id="integration_test",
        )

        result = await tool.execute(
            {
                "command": "npm",
                "args": ["test", "--coverage"],
                "cwd": "/project",
                "env": {"CI": "true"},
            }
        )

        # Verify success
        assert result.success is True

        # Verify complete protocol flow
        assert len(mock_client.create_terminal_calls) == 1
        assert len(mock_client.wait_for_exit_calls) == 1
        assert len(mock_client.terminal_output_calls) == 1
        assert len(mock_client.release_terminal_calls) == 1

        # Verify terminal was cleaned up
        assert len(mock_client.terminals) == 0

    @pytest.mark.asyncio
    async def test_file_read_write_workflow(self, mock_client: MockAcpClient) -> None:
        """Test reading and writing files through IDE."""
        read_tool = IdeReadFileTool(
            get_client=lambda: mock_client,
            session_id="integration_test",
        )
        write_tool = IdeWriteFileTool(
            get_client=lambda: mock_client,
            session_id="integration_test",
        )

        # Write a file
        write_result = await write_tool.execute(
            {
                "path": "/project/src/main.py",
                "content": "def main():\n    print('hello')\n",
            }
        )
        assert write_result.success is True

        # Read it back
        read_result = await read_tool.execute(
            {
                "path": "/project/src/main.py",
            }
        )
        assert read_result.success is True
        assert "def main" in read_result.output

    @pytest.mark.asyncio
    async def test_unsaved_buffer_priority(self, mock_client: MockAcpClient) -> None:
        """Test that unsaved buffer content takes priority over disk."""
        read_tool = IdeReadFileTool(
            get_client=lambda: mock_client,
            session_id="integration_test",
        )

        # Set disk content
        mock_client.set_disk_file("/project/file.py", "# Old version")

        # Simulate user editing without saving
        mock_client.set_unsaved_buffer("/project/file.py", "# New version with edits")

        # Read should return unsaved content
        result = await read_tool.execute({"path": "/project/file.py"})

        assert result.success is True
        assert "New version" in result.output
        assert "Old version" not in result.output
