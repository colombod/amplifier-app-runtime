"""ACP client-side tools for IDE/editor integration.

These tools execute operations on the CLIENT machine (IDE/editor),
not on the Amplifier server. They require an active ACP connection
with appropriate client capabilities.

Architecture:
- Tools take a `get_client` callable for lazy client access
- Tools check client availability before executing
- Tools are registered per-session based on client capabilities
- Tools implement the Amplifier Tool protocol (name, description, execute, get_schema)

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
from typing import TYPE_CHECKING, Any

# Import ToolResult from amplifier_core for Amplifier protocol compliance
from amplifier_core.models import ToolResult

if TYPE_CHECKING:
    from acp import Client  # type: ignore[import-untyped]
    from acp.schema import ClientCapabilities  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class IdeTerminalTool:
    """Execute commands on the IDE's machine via ACP terminal protocol.

    The command runs ON THE USER'S MACHINE in their IDE's terminal.
    User sees live output in their IDE's terminal panel.

    Protocol flow:
    1. terminal/create - Start command (returns immediately with terminalId)
    2. terminal/wait_for_exit - Wait for completion
    3. terminal/output - Get the output
    4. terminal/release - Cleanup resources

    Implements the Amplifier Tool protocol:
    - name: str property
    - description: str property
    - input_schema: dict property
    - execute(input) -> ToolResult
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
    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for tool input (Amplifier Tool protocol)."""
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

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a command in the IDE's terminal."""
        client = self._get_client()
        if not client:
            return ToolResult(
                success=False,
                error={
                    "message": "ACP client not connected - cannot execute on IDE. "
                    "Use 'bash' for server-side commands.",
                    "type": "ConnectionError",
                },
            )

        command = input.get("command")
        if not command:
            return ToolResult(
                success=False,
                error={"message": "command is required", "type": "ValidationError"},
            )

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

            # Format output with metadata
            result_output = {
                "output": output_text,
                "exit_code": exit_code,
                "truncated": truncated,
                "terminal_id": terminal_id,
            }

            if exit_code is not None and exit_code != 0:
                return ToolResult(
                    success=False,
                    output=result_output,
                    error={
                        "message": f"Command exited with code {exit_code}",
                        "type": "CommandError",
                        "exit_code": exit_code,
                    },
                )

            return ToolResult(success=True, output=result_output)

        except TimeoutError:
            return ToolResult(
                success=False,
                output={"terminal_id": terminal_id},
                error={
                    "message": f"Command timed out after {timeout} seconds",
                    "type": "TimeoutError",
                },
            )
        except Exception as e:
            logger.error(f"IDE terminal error: {e}")
            return ToolResult(
                success=False,
                error={"message": str(e), "type": type(e).__name__},
            )
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

    Implements the Amplifier Tool protocol:
    - name: str property
    - description: str property
    - get_schema() -> dict
    - execute(input) -> ToolResult
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
    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for tool input (Amplifier Tool protocol)."""
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

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Read a file from the IDE's file system."""
        client = self._get_client()
        if not client:
            return ToolResult(
                success=False,
                error={
                    "message": "ACP client not connected - cannot read from IDE. "
                    "Use 'read_file' for server-side files.",
                    "type": "ConnectionError",
                },
            )

        path = input.get("path")
        if not path:
            return ToolResult(
                success=False,
                error={"message": "path is required", "type": "ValidationError"},
            )

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
            )

        except Exception as e:
            logger.error(f"IDE read file error: {e}")
            return ToolResult(
                success=False,
                error={"message": str(e), "type": type(e).__name__},
            )


class IdeWriteFileTool:
    """Write files to the IDE's file system.

    Writes files ON THE USER'S MACHINE. The editor tracks the change.

    Implements the Amplifier Tool protocol:
    - name: str property
    - description: str property
    - get_schema() -> dict
    - execute(input) -> ToolResult
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
    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for tool input (Amplifier Tool protocol)."""
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

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Write a file to the IDE's file system."""
        client = self._get_client()
        if not client:
            return ToolResult(
                success=False,
                error={
                    "message": "ACP client not connected - cannot write to IDE. "
                    "Use 'write_file' for server-side files.",
                    "type": "ConnectionError",
                },
            )

        path = input.get("path")
        content = input.get("content")

        if not path:
            return ToolResult(
                success=False,
                error={"message": "path is required", "type": "ValidationError"},
            )
        if content is None:
            return ToolResult(
                success=False,
                error={"message": "content is required", "type": "ValidationError"},
            )

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
            )

        except Exception as e:
            logger.error(f"IDE write file error: {e}")
            return ToolResult(
                success=False,
                error={"message": str(e), "type": type(e).__name__},
            )


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

    Tools are mounted using the Amplifier coordinator.mount() pattern,
    which stores tools by name in the session's mount_points.

    Args:
        session: AmplifierSession (or ManagedSession) to register tools on
        get_client: Callable that returns the ACP Client connection
        session_id: The ACP session ID
        client_capabilities: ClientCapabilities from ACP negotiation

    Returns:
        List of registered tool names
    """
    registered: list[str] = []

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
                # Use coordinator.mount() - the standard Amplifier pattern
                # The name parameter is optional since tool has .name property
                await coordinator.mount("tools", tool)
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
