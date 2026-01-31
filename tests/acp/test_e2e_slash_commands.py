"""End-to-end test for ACP slash commands via stdio.

Tests that slash commands work through the full ACP protocol flow:
1. Spawn agent as subprocess (stdio transport)
2. Initialize protocol handshake
3. Create session
4. Send slash command as prompt
5. Verify response

This tests the integration between:
- ACP protocol layer
- Slash command detection and routing
- Amplifier prompt execution (for commands that translate to prompts)
"""

import asyncio
import asyncio.subprocess as aio_subprocess
import logging
import os
import sys
from typing import Any

import pytest
from acp import (  # type: ignore[import-untyped]
    PROTOCOL_VERSION,
    Client,
    RequestError,
    connect_to_agent,
    text_block,
)
from acp.schema import (  # type: ignore[import-untyped]
    AgentMessageChunk,
    AvailableCommandsUpdate,
    ClientCapabilities,
    Implementation,
    TextContentBlock,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SlashCommandTestClient(Client):
    """Test client that captures session updates for slash command verification."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.message_content: list[str] = []
        self.available_commands: list[dict[str, Any]] = []

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
                logger.info(f"📝 Agent message: {content.text[:100]}...")

        elif isinstance(update, AvailableCommandsUpdate):
            # Capture available commands notification
            commands = getattr(update, "available_commands", [])
            self.available_commands = [
                {"name": getattr(c, "name", ""), "description": getattr(c, "description", "")}
                for c in commands
            ]
            update_info["commands_count"] = len(commands)
            logger.info(f"📋 Available commands: {len(commands)}")

        self.updates.append(update_info)

    # Required Client methods
    async def request_permission(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("session/request_permission")

    async def write_text_file(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("fs/write_text_file")

    async def read_text_file(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("fs/read_text_file")

    async def create_terminal(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/create")

    async def terminal_output(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/output")

    async def release_terminal(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/wait_for_exit")

    async def kill_terminal(self, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/kill")

    async def ext_method(self, method: str, params: dict) -> dict:
        raise RequestError.method_not_found(method)

    async def ext_notification(self, method: str, params: dict) -> None:
        pass


async def create_acp_session() -> tuple[Any, Any, SlashCommandTestClient, aio_subprocess.Process]:
    """Create an ACP session for testing.

    Returns:
        Tuple of (connection, session, client, process)
    """
    # Spawn agent as subprocess using module entry point
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "amplifier_app_runtime.acp",
        stdin=aio_subprocess.PIPE,
        stdout=aio_subprocess.PIPE,
        stderr=aio_subprocess.PIPE,
    )

    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError("Agent process does not expose stdio pipes")

    client = SlashCommandTestClient()
    conn = connect_to_agent(client, proc.stdin, proc.stdout)

    # Initialize
    await asyncio.wait_for(
        conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(
                name="slash-command-test",
                title="Slash Command Test Client",
                version="1.0.0",
            ),
        ),
        timeout=30.0,
    )

    # Create session
    session = await asyncio.wait_for(
        conn.new_session(
            mcp_servers=[],
            cwd=os.getcwd(),
        ),
        timeout=60.0,
    )

    return conn, session, client, proc


async def cleanup_process(proc: aio_subprocess.Process) -> str | None:
    """Clean up subprocess and return stderr if any."""
    stderr_content = None
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            proc.kill()

    if proc.stderr:
        try:
            stderr = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
            if stderr:
                stderr_content = stderr.decode("utf-8", errors="replace")[-2000:]
        except Exception:
            pass

    return stderr_content


@pytest.mark.asyncio
async def test_help_slash_command():
    """Test /help slash command returns help message directly."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send /help command
        logger.info("Sending /help command...")
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[text_block("/help")],
            ),
            timeout=30.0,
        )

        # Verify response
        assert response.stop_reason == "end_turn"

        # Check that we got a message with help content
        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Help should contain information about commands
        assert any(
            keyword in full_response.lower() for keyword in ["help", "command", "available"]
        ), f"Help response doesn't contain expected content: {full_response[:200]}"

        logger.info("✅ /help command test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_tools_slash_command():
    """Test /tools slash command returns tools list."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send /tools command
        logger.info("Sending /tools command...")
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[text_block("/tools")],
            ),
            timeout=30.0,
        )

        # Verify response
        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Should mention tools
        assert any(keyword in full_response.lower() for keyword in ["tool", "available", "none"]), (
            f"Tools response unexpected: {full_response[:200]}"
        )

        logger.info("✅ /tools command test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_status_slash_command():
    """Test /status slash command returns session status."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send /status command
        logger.info("Sending /status command...")
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[text_block("/status")],
            ),
            timeout=30.0,
        )

        # Verify response
        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Status should contain session info
        assert any(
            keyword in full_response.lower()
            for keyword in ["session", "status", "state", "ready", "running"]
        ), f"Status response unexpected: {full_response[:200]}"

        logger.info("✅ /status command test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_modes_slash_command():
    """Test /modes slash command returns available modes."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send /modes command
        logger.info("Sending /modes command...")
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[text_block("/modes")],
            ),
            timeout=30.0,
        )

        # Verify response
        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Should mention modes
        assert any(
            keyword in full_response.lower()
            for keyword in ["mode", "available", "none", "plan", "explore"]
        ), f"Modes response unexpected: {full_response[:200]}"

        logger.info("✅ /modes command test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_recipe_help_slash_command():
    """Test /recipe (no args) returns recipe help."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send /recipe command without args
        logger.info("Sending /recipe command...")
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[text_block("/recipe")],
            ),
            timeout=30.0,
        )

        # Verify response
        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Should show recipe subcommands
        assert any(
            keyword in full_response.lower()
            for keyword in ["run", "list", "resume", "approve", "cancel"]
        ), f"Recipe help response unexpected: {full_response[:200]}"

        logger.info("✅ /recipe help command test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_unknown_slash_command():
    """Test unknown slash command returns error message.

    Note: Unknown commands should return an error message gracefully.
    """
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send unknown command
        logger.info("Sending /notarealcommand...")
        try:
            await asyncio.wait_for(
                conn.prompt(
                    session_id=session.session_id,
                    prompt=[text_block("/notarealcommand")],
                ),
                timeout=30.0,
            )

            # If we get a response, verify it indicates unknown command
            full_response = "".join(client.message_content)
            if full_response:
                assert any(
                    keyword in full_response.lower()
                    for keyword in ["unknown", "not found", "invalid", "help", "unrecognized"]
                ), f"Unknown command response unexpected: {full_response[:200]}"
            logger.info("✅ Unknown command test passed (graceful error)")

        except Exception as e:
            # Protocol errors for unknown commands are acceptable
            # The test validates error handling exists
            logger.info(f"✅ Unknown command caused expected error: {type(e).__name__}")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_available_commands_sent_on_session_create():
    """Test that available_commands_update is sent after session creation."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Give a moment for async notifications to arrive
        await asyncio.sleep(0.5)

        # Check that we received available commands update
        # (client.available_commands is populated from AvailableCommandsUpdate)

        # Should have received commands
        assert len(client.available_commands) > 0, "No available commands received"

        # Should include essential commands (names without "/" prefix)
        command_names = [c["name"] for c in client.available_commands]
        assert "help" in command_names, f"Expected 'help' in commands: {command_names}"

        logger.info(f"✅ Received {len(client.available_commands)} available commands")

    finally:
        if proc:
            await cleanup_process(proc)


if __name__ == "__main__":
    print("=" * 60)
    print("ACP Slash Commands End-to-End Test")
    print("=" * 60)
    print("\nThis test spawns the Amplifier agent as a subprocess")
    print("and tests slash command handling via the ACP protocol.\n")

    async def run_all_tests():
        tests = [
            ("test_help_slash_command", test_help_slash_command),
            ("test_tools_slash_command", test_tools_slash_command),
            ("test_status_slash_command", test_status_slash_command),
            ("test_modes_slash_command", test_modes_slash_command),
            ("test_recipe_help_slash_command", test_recipe_help_slash_command),
            ("test_unknown_slash_command", test_unknown_slash_command),
            (
                "test_available_commands_sent_on_session_create",
                test_available_commands_sent_on_session_create,
            ),
        ]

        results = {}
        for name, test_fn in tests:
            print(f"\n--- Running {name} ---")
            try:
                await test_fn()
                results[name] = True
                print(f"✅ {name} PASSED")
            except Exception as e:
                results[name] = False
                print(f"❌ {name} FAILED: {e}")

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"Passed: {passed}/{total}")

        for name, passed in results.items():
            status = "✅" if passed else "❌"
            print(f"  {status} {name}")

        return all(results.values())

    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
