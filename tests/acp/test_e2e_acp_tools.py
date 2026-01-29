"""End-to-end test for ACP client-side tools (ide_terminal, ide_read_file, ide_write_file).

Tests the full flow:
1. Client advertises terminal and filesystem capabilities
2. Agent registers ide_* tools based on capabilities
3. Prompt triggers tool usage
4. Tools call back to client methods
5. Verify complete round-trip

This test uses a REAL Amplifier session, not mocks.
"""

import asyncio
import asyncio.subprocess as aio_subprocess
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# ACP SDK imports
from acp import (  # type: ignore[import-untyped]
    PROTOCOL_VERSION,
    Client,
    connect_to_agent,
    text_block,
)
from acp.schema import (  # type: ignore[import-untyped]
    AgentMessageChunk,
    AgentThoughtChunk,
    ClientCapabilities,
    FileSystemCapability,
    Implementation,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TerminalCreateResult:
    """Result from terminal/create."""

    terminal_id: str


@dataclass
class TerminalExitResult:
    """Result from terminal/wait_for_exit."""

    exit_code: int
    signal: str | None = None


@dataclass
class TerminalOutputResult:
    """Result from terminal/output."""

    output: str
    truncated: bool = False


@dataclass
class ReadFileResult:
    """Result from fs/read_text_file."""

    content: str


class AcpToolsTestClient(Client):
    """Test client that supports terminal and filesystem capabilities.

    This client:
    1. Advertises full capabilities during initialize
    2. Implements terminal/file methods to track calls
    3. Returns realistic mock data
    """

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.message_content: list[str] = []

        # Track method calls for verification
        self.terminal_creates: list[dict[str, Any]] = []
        self.terminal_waits: list[dict[str, Any]] = []
        self.terminal_outputs: list[dict[str, Any]] = []
        self.terminal_releases: list[dict[str, Any]] = []
        self.terminal_kills: list[dict[str, Any]] = []
        self.file_reads: list[dict[str, Any]] = []
        self.file_writes: list[dict[str, Any]] = []

        self._terminal_counter = 0

        # Simulated file system
        self.mock_files: dict[str, str] = {
            "/project/README.md": "# Test Project\n\nThis is a test file.",
            "/project/src/main.py": "def main():\n    print('Hello')\n",
        }

    # ========================================================================
    # Session Update Handler
    # ========================================================================

    async def session_update(
        self,
        session_id: str,
        update: Any,
        **kwargs: Any,
    ) -> None:
        """Capture session updates for test verification."""
        update_info = {
            "session_id": session_id,
            "update_type": type(update).__name__,
        }

        if isinstance(update, AgentMessageChunk):
            content = update.content
            if isinstance(content, TextContentBlock):
                update_info["text"] = content.text
                self.message_content.append(content.text)
                logger.info(f"📝 Agent: {content.text[:80]}...")

        elif isinstance(update, AgentThoughtChunk):
            logger.info("🧠 Agent thinking...")

        elif isinstance(update, ToolCallStart):
            tool_name = getattr(update, "tool_name", None) or getattr(update, "name", "unknown")
            logger.info(f"🔧 Tool call: {tool_name}")
            update_info["tool_name"] = tool_name

        elif isinstance(update, ToolCallProgress):
            logger.info("🔧 Tool progress...")

        self.updates.append(update_info)

    # ========================================================================
    # Terminal Capability Implementation
    # ========================================================================

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> TerminalCreateResult:
        """Handle terminal/create - called by ide_terminal tool."""
        self._terminal_counter += 1
        terminal_id = f"test_term_{self._terminal_counter}"

        call_info = {
            "session_id": session_id,
            "command": command,
            "args": args or [],
            "cwd": cwd,
            "env": env,
            "terminal_id": terminal_id,
        }
        self.terminal_creates.append(call_info)
        logger.info(f"✅ terminal/create: {command} {args} -> {terminal_id}")

        return TerminalCreateResult(terminal_id=terminal_id)

    async def wait_for_terminal_exit(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> TerminalExitResult:
        """Handle terminal/wait_for_exit."""
        self.terminal_waits.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )
        logger.info(f"✅ terminal/wait_for_exit: {terminal_id}")

        # Simulate successful completion
        return TerminalExitResult(exit_code=0)

    async def terminal_output(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> TerminalOutputResult:
        """Handle terminal/output."""
        self.terminal_outputs.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )

        # Find the command that created this terminal
        for create in self.terminal_creates:
            if create["terminal_id"] == terminal_id:
                cmd = create["command"]
                args = create.get("args", [])
                output = f"Mock output for: {cmd} {' '.join(args)}\nSuccess!\n"
                logger.info(f"✅ terminal/output: {terminal_id} -> {len(output)} bytes")
                return TerminalOutputResult(output=output)

        return TerminalOutputResult(output="Unknown terminal")

    async def release_terminal(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> None:
        """Handle terminal/release."""
        self.terminal_releases.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )
        logger.info(f"✅ terminal/release: {terminal_id}")

    async def kill_terminal(
        self,
        session_id: str,
        terminal_id: str,
        **kwargs: Any,
    ) -> None:
        """Handle terminal/kill."""
        self.terminal_kills.append(
            {
                "session_id": session_id,
                "terminal_id": terminal_id,
            }
        )
        logger.info(f"✅ terminal/kill: {terminal_id}")

    # ========================================================================
    # Filesystem Capability Implementation
    # ========================================================================

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> ReadFileResult:
        """Handle fs/read_text_file - called by ide_read_file tool."""
        self.file_reads.append(
            {
                "session_id": session_id,
                "path": path,
                "line": line,
                "limit": limit,
            }
        )

        content = self.mock_files.get(path, f"File not found: {path}")
        logger.info(f"✅ fs/read_text_file: {path} -> {len(content)} bytes")

        return ReadFileResult(content=content)

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        """Handle fs/write_text_file - called by ide_write_file tool."""
        self.file_writes.append(
            {
                "session_id": session_id,
                "path": path,
                "content": content,
            }
        )

        # Actually store it
        self.mock_files[path] = content
        logger.info(f"✅ fs/write_text_file: {path} ({len(content)} bytes)")

    # ========================================================================
    # Other Required Methods
    # ========================================================================

    async def request_permission(self, **kwargs: Any) -> Any:
        """Not implemented for this test."""
        return {"granted": True}

    async def ext_method(self, method: str, params: dict) -> dict:
        """Handle extension methods."""
        return {}

    async def ext_notification(self, method: str, params: dict) -> None:
        """Handle extension notifications."""
        pass


def get_client_capabilities() -> ClientCapabilities:
    """Create ClientCapabilities advertising terminal and filesystem support."""
    return ClientCapabilities(
        terminal=True,
        fs=FileSystemCapability(
            read_text_file=True,
            write_text_file=True,
        ),
    )


async def run_acp_tools_e2e_test() -> dict[str, Any]:
    """Run end-to-end test for ACP client-side tools."""
    results: dict[str, Any] = {
        "passed": False,
        "initialize": False,
        "new_session": False,
        "capabilities_sent": False,
        "prompt_completed": False,
        "tools_registered": False,
        "terminal_called": False,
        "file_read_called": False,
        "file_write_called": False,
        "error": None,
    }

    # Path to agent module
    agent_module = (
        Path(__file__).parent.parent.parent / "src" / "amplifier_server_app" / "acp" / "agent.py"
    )

    if not agent_module.exists():
        results["error"] = f"Agent module not found: {agent_module}"
        return results

    logger.info(f"Starting agent: {agent_module}")

    # Spawn agent subprocess
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(agent_module),
        stdin=aio_subprocess.PIPE,
        stdout=aio_subprocess.PIPE,
        stderr=aio_subprocess.PIPE,
    )

    if proc.stdin is None or proc.stdout is None:
        results["error"] = "Agent process does not expose stdio pipes"
        return results

    try:
        client = AcpToolsTestClient()
        conn = connect_to_agent(client, proc.stdin, proc.stdout)

        # 1. Initialize with capabilities
        logger.info("Step 1: Initialize with terminal + fs capabilities...")
        capabilities = get_client_capabilities()
        results["capabilities_sent"] = True

        init_response = await asyncio.wait_for(
            conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=capabilities,
                client_info=Implementation(
                    name="acp-tools-test",
                    title="ACP Tools E2E Test",
                    version="1.0.0",
                ),
            ),
            timeout=30.0,
        )
        results["initialize"] = True
        logger.info(f"✅ Initialized: {init_response.agent_info.name}")

        # 2. Create session (tools should be registered based on capabilities)
        logger.info("Step 2: Create session...")
        session = await asyncio.wait_for(
            conn.new_session(
                mcp_servers=[],
                cwd=os.getcwd(),
            ),
            timeout=60.0,
        )
        results["new_session"] = True
        session_id = session.session_id
        logger.info(f"✅ Session created: {session_id}")

        # 3. Test terminal tool - ask agent to run a command
        logger.info("Step 3: Test ide_terminal tool...")
        try:
            prompt_response = await asyncio.wait_for(
                conn.prompt(
                    session_id=session_id,
                    prompt=[
                        text_block(
                            "Use the ide_terminal tool to run 'echo' with "
                            "args ['hello', 'world']. Report the output. "
                            "Do not use bash, use ide_terminal."
                        )
                    ],
                ),
                timeout=120.0,
            )
            results["prompt_completed"] = True
            logger.info(f"✅ Terminal prompt complete: {prompt_response.stop_reason}")

            # Check if terminal was called
            if client.terminal_creates:
                results["terminal_called"] = True
                logger.info(f"✅ Terminal was called {len(client.terminal_creates)} time(s)")
                for call in client.terminal_creates:
                    logger.info(f"   Command: {call['command']} {call.get('args', [])}")
            else:
                logger.warning("⚠️ Terminal was NOT called")

        except Exception as e:
            logger.error(f"Terminal test failed: {e}")
            results["terminal_test_error"] = str(e)

        # 4. Test file read tool
        logger.info("Step 4: Test ide_read_file tool...")
        try:
            prompt_response = await asyncio.wait_for(
                conn.prompt(
                    session_id=session_id,
                    prompt=[
                        text_block(
                            "Use the ide_read_file tool to read the file "
                            "at path '/project/README.md'. Report contents. "
                            "Do not use read_file, use ide_read_file."
                        )
                    ],
                ),
                timeout=120.0,
            )
            logger.info(f"✅ Read file prompt complete: {prompt_response.stop_reason}")

            if client.file_reads:
                results["file_read_called"] = True
                logger.info(f"✅ File read was called {len(client.file_reads)} time(s)")
                for call in client.file_reads:
                    logger.info(f"   Path: {call['path']}")
            else:
                logger.warning("⚠️ File read was NOT called")

        except Exception as e:
            logger.error(f"File read test failed: {e}")
            results["file_read_test_error"] = str(e)

        # 5. Test file write tool
        logger.info("Step 5: Test ide_write_file tool...")
        try:
            prompt_response = await asyncio.wait_for(
                conn.prompt(
                    session_id=session_id,
                    prompt=[
                        text_block(
                            "Use the ide_write_file tool to write a file "
                            "at path '/project/output.txt' with content "
                            "'Test output'. Use ide_write_file not write_file."
                        )
                    ],
                ),
                timeout=120.0,
            )
            logger.info(f"✅ Write file prompt complete: {prompt_response.stop_reason}")

            if client.file_writes:
                results["file_write_called"] = True
                logger.info(f"✅ File write was called {len(client.file_writes)} time(s)")
                for call in client.file_writes:
                    logger.info(f"   Path: {call['path']}, Content: {call['content'][:50]}...")
            else:
                logger.warning("⚠️ File write was NOT called")

        except Exception as e:
            logger.error(f"File write test failed: {e}")
            results["file_write_test_error"] = str(e)

        # Check if tools were seen in tool calls
        tool_calls = [u for u in client.updates if u.get("tool_name")]
        tool_names = [u["tool_name"] for u in tool_calls]
        results["tools_seen"] = tool_names
        logger.info(f"Tools called during session: {tool_names}")

        # If we see ide_* tools in the tool calls, tools were registered
        ide_tools = [t for t in tool_names if t.startswith("ide_")]
        if ide_tools:
            results["tools_registered"] = True

        # Overall pass criteria
        results["passed"] = (
            results["initialize"]
            and results["new_session"]
            and results["prompt_completed"]
            and (
                results["terminal_called"]
                or results["file_read_called"]
                or results["file_write_called"]
            )
        )

    except TimeoutError:
        results["error"] = "Test timed out"
    except Exception as e:
        results["error"] = f"Unexpected error: {e}"
        logger.exception("E2E test error")
    finally:
        # Cleanup
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()

        # Capture stderr
        if proc.stderr:
            try:
                stderr = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
                if stderr:
                    stderr_text = stderr.decode("utf-8", errors="replace")
                    results["stderr"] = stderr_text[-2000:]
                    # Check for tool registration logs
                    if "Registered ACP tool" in stderr_text:
                        results["tools_registered"] = True
                        logger.info("✅ Found tool registration in logs")
            except Exception:
                pass

    return results


@pytest.mark.asyncio
async def test_acp_tools_e2e():
    """Test ACP client-side tools end-to-end."""
    results = await run_acp_tools_e2e_test()

    print("\n" + "=" * 70)
    print("ACP TOOLS E2E TEST RESULTS")
    print("=" * 70)

    for key, value in results.items():
        if key == "stderr":
            print(f"{key}: [see debug output]")
        elif key == "tools_seen":
            print(f"{key}: {value}")
        elif isinstance(value, bool):
            status = "✅" if value else "❌"
            print(f"{status} {key}: {value}")
        else:
            print(f"  {key}: {value}")

    print("=" * 70)

    if results.get("error"):
        print(f"\n❌ ERROR: {results['error']}")

    if results.get("stderr") and not results["passed"]:
        print("\nAgent stderr (last 500 chars):")
        print(results["stderr"][-500:])

    # Assertions
    assert results["initialize"], "Failed to initialize"
    assert results["new_session"], "Failed to create session"
    assert results["prompt_completed"], "Prompts did not complete"

    # At least one tool should have been called
    tools_called = (
        results.get("terminal_called")
        or results.get("file_read_called")
        or results.get("file_write_called")
    )
    assert tools_called, (
        "No ACP tools were called! "
        f"Tools seen: {results.get('tools_seen', [])}. "
        "Check that tools are registered based on capabilities."
    )


if __name__ == "__main__":
    print("=" * 70)
    print("ACP Client-Side Tools E2E Test")
    print("=" * 70)
    print("\nThis test verifies that ide_terminal, ide_read_file, and ide_write_file")
    print("tools are registered based on client capabilities and work correctly.\n")

    results = asyncio.run(run_acp_tools_e2e_test())

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    for key, value in results.items():
        if key == "stderr":
            continue
        elif isinstance(value, bool):
            status = "✅" if value else "❌"
            print(f"{status} {key}")
        elif isinstance(value, list):
            print(f"📋 {key}: {value}")
        elif value:
            print(f"  {key}: {value}")

    print("=" * 70)

    if results["passed"]:
        print("\n✅ ACP TOOLS E2E TEST PASSED")
        sys.exit(0)
    else:
        print(f"\n❌ ACP TOOLS E2E TEST FAILED: {results.get('error', 'Tools not called')}")
        if results.get("stderr"):
            print("\nAgent stderr:")
            print(results["stderr"][-1000:])
        sys.exit(1)
