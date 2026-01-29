"""ACP client-side tools for IDE/editor integration.

These tools execute operations on the CLIENT machine (IDE/editor),
not on the Amplifier server. They require an active ACP connection
with appropriate client capabilities.

Architecture:
- Tools take a `get_client` callable for lazy client access
- Tools check client availability before executing
- Tools are registered per-session based on client capabilities

Usage:
    from .tools import register_acp_tools

    registered = await register_acp_tools(
        session=amplifier_session,
        get_client=lambda: self._conn,
        session_id=session_id,
        client_capabilities=self._client_capabilities,
    )
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from acp import Client  # type: ignore[import-untyped]
    from acp.schema import ClientCapabilities  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool = True
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class IdeTerminalTool:
    """Execute commands on the IDE's machine via ACP terminal protocol.

    The command runs ON THE USER'S MACHINE in their IDE's terminal.
    User sees live output in their IDE's terminal panel.

    Protocol flow:
    1. terminal/create - Start command (returns immediately with terminalId)
    2. terminal/wait_for_exit - Wait for completion
    3. terminal/output - Get the output
    4. terminal/release - Cleanup resources
    """

    name = "ide_terminal"
    description = """Execute shell commands on the user's IDE/editor machine (client-side).

Use this when:
- You need to run commands where the user is working (their machine)
- The command should use the user's environment (PATH, credentials, tools)
- You want the user to see live output in their IDE's terminal

The IDE may show permission dialogs for sensitive operations.

For commands on the Amplifier server, use 'bash' instead.

Args:
    command: The command to execute (e.g., "npm", "python", "cargo")
    args: List of command arguments (e.g., ["test", "--coverage"])
    cwd: Working directory (absolute path on user's machine)
    env: Environment variables as dict (e.g., {"NODE_ENV": "test"})
    timeout: Optional timeout in seconds (command killed if exceeded)
"""

    def __init__(
        self,
        get_client: Callable[[], Client | None],
        session_id: str,
    ) -> None:
        self._get_client = get_client
        self._session_id = session_id

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments",
                    "default": [],
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (absolute path)",
                },
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Environment variables",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                },
            },
            "required": ["command"],
        }

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool parameters (Amplifier protocol)."""
        return self.parameters

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a command in the IDE's terminal."""
        client = self._get_client()
        if not client:
            return ToolResult(
                success=False,
                error="ACP client not connected - cannot execute on IDE. "
                "Use 'bash' for server-side commands.",
            )

        command = input.get("command")
        if not command:
            return ToolResult(success=False, error="command is required")

        args = input.get("args", [])
        cwd = input.get("cwd")
        env_dict = input.get("env", {})
        timeout = input.get("timeout")

        # Convert env dict to list of EnvVariable format
        env_vars = [{"name": k, "value": v} for k, v in env_dict.items()] if env_dict else None

        terminal_id = None
        try:
            # 1. Create terminal (non-blocking)
            logger.info(f"Creating IDE terminal: {command} {args}")
            create_result = await client.create_terminal(
                session_id=self._session_id,
                command=command,
                args=args,
                cwd=cwd,
                env=env_vars,
            )
            terminal_id = create_result.terminal_id
            logger.info(f"Terminal created: {terminal_id}")

            # 2. Wait for completion (with optional timeout)
            if timeout:
                exit_result = await self._wait_with_timeout(client, terminal_id, timeout)
            else:
                exit_result = await client.wait_for_terminal_exit(
                    session_id=self._session_id,
                    terminal_id=terminal_id,
                )

            # 3. Get output
            output_result = await client.terminal_output(
                session_id=self._session_id,
                terminal_id=terminal_id,
            )

            # Build result - handle both snake_case and camelCase field names
            # Note: Can't use `or` because exit_code=0 is valid but falsy
            exit_code = getattr(exit_result, "exit_code", None)
            if exit_code is None:
                exit_code = getattr(exit_result, "exitCode", None)
            output_text = getattr(output_result, "output", "")
            truncated = getattr(output_result, "truncated", False)

            return ToolResult(
                success=exit_code == 0 if exit_code is not None else True,
                output=output_text,
                metadata={
                    "exit_code": exit_code,
                    "truncated": truncated,
                    "terminal_id": terminal_id,
                },
            )

        except TimeoutError:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
                metadata={"terminal_id": terminal_id},
            )
        except Exception as e:
            logger.error(f"IDE terminal error: {e}")
            return ToolResult(success=False, error=str(e))
        finally:
            # 4. Always release terminal
            if terminal_id and client:
                try:
                    await client.release_terminal(
                        session_id=self._session_id,
                        terminal_id=terminal_id,
                    )
                    logger.debug(f"Terminal released: {terminal_id}")
                except Exception as e:
                    logger.warning(f"Failed to release terminal {terminal_id}: {e}")

    async def _wait_with_timeout(
        self,
        client: Client,
        terminal_id: str,
        timeout: int,
    ) -> Any:
        """Wait for terminal exit with timeout, killing if exceeded."""
        try:
            return await asyncio.wait_for(
                client.wait_for_terminal_exit(
                    session_id=self._session_id,
                    terminal_id=terminal_id,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            # Kill the command
            logger.warning(f"Terminal {terminal_id} timed out, killing...")
            try:
                await client.kill_terminal(
                    session_id=self._session_id,
                    terminal_id=terminal_id,
                )
            except Exception as e:
                logger.warning(f"Failed to kill terminal: {e}")
            raise


class IdeReadFileTool:
    """Read files from the IDE's file system.

    Reads files ON THE USER'S MACHINE, including unsaved editor buffers!
    This is the key differentiator from server-side read_file.
    """

    name = "ide_read_file"
    description = """Read a file from the user's IDE/editor machine (client-side).

IMPORTANT: This can read UNSAVED editor buffer content!
- If file is open in editor with unsaved changes → returns buffer content
- If file is not open → returns disk content

Use this when:
- You need to read the user's current edits (not just what's saved on disk)
- The file is on the user's machine, not the Amplifier server

For server-side files, use 'read_file' instead.

Args:
    path: Absolute path to the file on user's machine
    line: Optional line number to start reading from (1-based)
    limit: Optional maximum number of lines to read
"""

    def __init__(
        self,
        get_client: Callable[[], Client | None],
        session_id: str,
    ) -> None:
        self._get_client = get_client
        self._session_id = session_id

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                },
            },
            "required": ["path"],
        }

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool parameters (Amplifier protocol)."""
        return self.parameters

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Read a file from the IDE's file system."""
        client = self._get_client()
        if not client:
            return ToolResult(
                success=False,
                error="ACP client not connected - cannot read from IDE. "
                "Use 'read_file' for server-side files.",
            )

        path = input.get("path")
        if not path:
            return ToolResult(success=False, error="path is required")

        line = input.get("line")
        limit = input.get("limit")

        try:
            logger.info(f"Reading IDE file: {path}")
            result = await client.read_text_file(
                session_id=self._session_id,
                path=path,
                line=line,
                limit=limit,
            )

            content = getattr(result, "content", "")
            return ToolResult(
                success=True,
                output=content,
                metadata={"path": path, "line": line, "limit": limit},
            )

        except Exception as e:
            logger.error(f"IDE read file error: {e}")
            return ToolResult(success=False, error=str(e))


class IdeWriteFileTool:
    """Write files to the IDE's file system.

    Writes files ON THE USER'S MACHINE. The editor tracks the change.
    """

    name = "ide_write_file"
    description = """Write a file on the user's IDE/editor machine (client-side).

The file is written ON THE USER'S MACHINE, not the Amplifier server.
The editor will track this change and may show it as modified.

Use this when:
- You're modifying files in the user's project
- You want the editor to track the change
- The file should be on the user's machine

For server-side files, use 'write_file' instead.

Args:
    path: Absolute path to the file on user's machine
    content: The text content to write
"""

    def __init__(
        self,
        get_client: Callable[[], Client | None],
        session_id: str,
    ) -> None:
        self._get_client = get_client
        self._session_id = session_id

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write",
                },
            },
            "required": ["path", "content"],
        }

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool parameters (Amplifier protocol)."""
        return self.parameters

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Write a file to the IDE's file system."""
        client = self._get_client()
        if not client:
            return ToolResult(
                success=False,
                error="ACP client not connected - cannot write to IDE. "
                "Use 'write_file' for server-side files.",
            )

        path = input.get("path")
        content = input.get("content")

        if not path:
            return ToolResult(success=False, error="path is required")
        if content is None:
            return ToolResult(success=False, error="content is required")

        try:
            logger.info(f"Writing IDE file: {path} ({len(content)} bytes)")
            await client.write_text_file(
                session_id=self._session_id,
                path=path,
                content=content,
            )

            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes to {path}",
                metadata={"path": path, "bytes_written": len(content)},
            )

        except Exception as e:
            logger.error(f"IDE write file error: {e}")
            return ToolResult(success=False, error=str(e))


def create_acp_tools(
    get_client: Callable[[], Client | None],
    session_id: str,
    client_capabilities: ClientCapabilities | None = None,
) -> list[tuple[Any, bool]]:
    """Factory to create ACP client-side tools with capability gating.

    Args:
        get_client: Callable that returns the ACP Client connection
        session_id: The ACP session ID for this session
        client_capabilities: ClientCapabilities from ACP negotiation

    Returns:
        List of (tool, should_register) tuples
    """
    tools = []

    # Determine capabilities
    has_terminal = False
    has_fs_read = False
    has_fs_write = False

    if client_capabilities:
        # Check terminal capability
        has_terminal = getattr(client_capabilities, "terminal", False)

        # Check filesystem capabilities
        fs = getattr(client_capabilities, "fs", None)
        if fs:
            has_fs_read = getattr(fs, "readTextFile", False) or getattr(fs, "read_text_file", False)
            has_fs_write = getattr(fs, "writeTextFile", False) or getattr(
                fs, "write_text_file", False
            )

    # Create tools with capability flags
    tools.append((IdeTerminalTool(get_client, session_id), has_terminal))
    tools.append((IdeReadFileTool(get_client, session_id), has_fs_read))
    tools.append((IdeWriteFileTool(get_client, session_id), has_fs_write))

    return tools


async def register_acp_tools(
    session: Any,
    get_client: Callable[[], Client | None],
    session_id: str,
    client_capabilities: ClientCapabilities | None = None,
) -> list[str]:
    """Register ACP client-side tools on an Amplifier session.

    Tools are registered based on client capabilities. If the client
    doesn't support a capability, that tool won't be registered.

    Args:
        session: AmplifierSession (or ManagedSession) to register tools on
        get_client: Callable that returns the ACP Client connection
        session_id: The ACP session ID
        client_capabilities: ClientCapabilities from ACP negotiation

    Returns:
        List of registered tool names
    """
    registered = []

    # Get coordinator from session
    # Handle both direct AmplifierSession and ManagedSession wrapper
    coordinator = None
    if hasattr(session, "coordinator"):
        # Direct AmplifierSession
        coordinator = session.coordinator
    elif hasattr(session, "_amplifier_session"):
        # ManagedSession wrapper - access underlying session
        amplifier_session = session._amplifier_session
        if amplifier_session and hasattr(amplifier_session, "coordinator"):
            coordinator = amplifier_session.coordinator

    if coordinator is None:
        logger.warning("Could not find coordinator on session - ACP tools not registered")
        return registered

    # Create tools with capability gating
    tools_with_caps = create_acp_tools(get_client, session_id, client_capabilities)

    for tool, should_register in tools_with_caps:
        if should_register:
            try:
                await coordinator.mount("tools", tool, name=tool.name)
                registered.append(tool.name)
                logger.info(f"Registered ACP tool: {tool.name}")
            except Exception as e:
                logger.error(f"Failed to register ACP tool {tool.name}: {e}")
        else:
            logger.debug(f"Skipping ACP tool {tool.name} - client doesn't support capability")

    # Register client accessor as a capability for other modules
    try:
        coordinator.register_capability("acp.client", get_client)
        coordinator.register_capability("acp.session_id", session_id)
        logger.debug("Registered ACP capabilities on coordinator")
    except Exception as e:
        logger.warning(f"Failed to register ACP capabilities: {e}")

    return registered
