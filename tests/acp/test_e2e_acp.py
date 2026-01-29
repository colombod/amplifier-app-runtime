"""End-to-end ACP protocol test using the official SDK client.

Tests the full ACP protocol flow:
1. Spawn agent as subprocess (stdio transport)
2. Initialize protocol handshake
3. Create session
4. Send prompt and receive streaming updates
5. Verify response

Based on: https://github.com/agentclientprotocol/python-sdk/blob/main/examples/client.py
"""

import asyncio
import asyncio.subprocess as aio_subprocess
import logging
import os
import sys
from typing import Any

import pytest

# ACP SDK imports
from acp import (  # type: ignore[import-untyped]
    PROTOCOL_VERSION,
    Client,
    RequestError,
    connect_to_agent,
    text_block,
)
from acp.schema import (  # type: ignore[import-untyped]
    AgentMessageChunk,
    AgentThoughtChunk,
    ClientCapabilities,
    Implementation,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestAcpClient(Client):
    """Test client that captures session updates for verification."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.message_content: list[str] = []

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
                logger.info(f"📝 Agent message: {content.text[:50]}...")
            else:
                update_info["content_type"] = type(content).__name__
                logger.info(f"📝 Agent content: {type(content).__name__}")

        elif isinstance(update, AgentThoughtChunk):
            logger.info("🧠 Agent thinking...")
            update_info["thinking"] = True

        elif isinstance(update, ToolCallStart):
            logger.info(f"🔧 Tool call started: {getattr(update, 'tool_name', 'unknown')}")
            update_info["tool_start"] = True

        elif isinstance(update, ToolCallProgress):
            logger.info("🔧 Tool call progress...")
            update_info["tool_progress"] = True

        elif isinstance(update, UserMessageChunk):
            logger.info("👤 User message chunk")
            update_info["user_message"] = True

        else:
            logger.info(f"📡 Update: {type(update).__name__}")

        self.updates.append(update_info)

    # Required Client methods (not used in test but must be implemented)
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


async def run_e2e_test() -> dict[str, Any]:
    """Run end-to-end ACP test and return results."""
    results = {
        "passed": False,
        "initialize": False,
        "new_session": False,
        "prompt": False,
        "updates_received": 0,
        "has_content": False,
        "error": None,
    }

    # Use the proper module entry point for stdio isolation
    # This ensures the JsonRpcStdoutFilter is active
    logger.info("Starting agent subprocess: python -m amplifier_app_runtime.acp")

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
        results["error"] = "Agent process does not expose stdio pipes"
        return results

    try:
        # Create test client
        client = TestAcpClient()

        # Connect to agent using SDK
        logger.info("Connecting to agent via stdio...")
        conn = connect_to_agent(client, proc.stdin, proc.stdout)

        # 1. Initialize
        logger.info("Step 1: Initialize protocol...")
        try:
            init_response = await asyncio.wait_for(
                conn.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(
                        name="acp-e2e-test",
                        title="ACP E2E Test Client",
                        version="1.0.0",
                    ),
                ),
                timeout=30.0,
            )
            results["initialize"] = True
            logger.info(f"✅ Initialize OK - Agent: {init_response.agent_info.name}")
        except Exception as e:
            results["error"] = f"Initialize failed: {e}"
            return results

        # 2. Create new session
        logger.info("Step 2: Create new session...")
        try:
            session = await asyncio.wait_for(
                conn.new_session(
                    mcp_servers=[],
                    cwd=os.getcwd(),
                ),
                timeout=60.0,
            )
            results["new_session"] = True
            logger.info(f"✅ Session created: {session.session_id}")
        except Exception as e:
            results["error"] = f"New session failed: {e}"
            return results

        # 3. Send prompt and get response
        logger.info("Step 3: Send prompt...")
        try:
            prompt_response = await asyncio.wait_for(
                conn.prompt(
                    session_id=session.session_id,
                    prompt=[text_block("Say exactly 'E2E Test Success' and nothing else.")],
                ),
                timeout=120.0,
            )
            results["prompt"] = True
            logger.info(f"✅ Prompt complete - Stop reason: {prompt_response.stop_reason}")
        except Exception as e:
            results["error"] = f"Prompt failed: {e}"
            return results

        # 4. Verify results
        results["updates_received"] = len(client.updates)
        results["has_content"] = len(client.message_content) > 0

        # Check if we got meaningful content
        full_response = "".join(client.message_content)
        logger.info(f"Full response: {full_response[:200]}...")

        if "E2E Test Success" in full_response or "e2e test success" in full_response.lower():
            results["response_correct"] = True
        else:
            results["response_correct"] = False
            results["actual_response"] = full_response[:500]

        # Overall pass if we got through the protocol flow
        results["passed"] = (
            results["initialize"]
            and results["new_session"]
            and results["prompt"]
            and results["updates_received"] > 0
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

        # Capture stderr for debugging
        if proc.stderr:
            try:
                stderr = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
                if stderr:
                    results["stderr"] = stderr.decode("utf-8", errors="replace")[-2000:]
            except Exception:
                pass

    return results


@pytest.mark.asyncio
async def test_acp_e2e_stdio():
    """Test ACP protocol end-to-end via stdio transport."""
    results = await run_e2e_test()

    print("\n" + "=" * 60)
    print("ACP E2E TEST RESULTS")
    print("=" * 60)

    for key, value in results.items():
        if key == "stderr":
            print(f"{key}: [see debug output]")
        elif key == "actual_response":
            print(f"{key}: {value[:100]}...")
        else:
            print(f"{key}: {value}")

    print("=" * 60)

    if results.get("error"):
        print(f"\n❌ ERROR: {results['error']}")
        if results.get("stderr"):
            print("\nAgent stderr (last 500 chars):")
            print(results["stderr"][-500:])

    assert results["passed"], f"E2E test failed: {results.get('error', 'Unknown error')}"
    assert results["updates_received"] > 0, "No session updates received"


if __name__ == "__main__":
    print("=" * 60)
    print("ACP End-to-End Test")
    print("=" * 60)
    print("\nThis test spawns the Amplifier agent as a subprocess")
    print("and communicates with it using the official ACP SDK.\n")

    results = asyncio.run(run_e2e_test())

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    for key, value in results.items():
        if key == "stderr":
            continue
        elif key == "actual_response":
            print(f"{key}: {value[:100]}...")
        else:
            status = "✅" if value else "❌" if isinstance(value, bool) else "📊"
            print(f"{status} {key}: {value}")

    print("=" * 60)

    if results["passed"]:
        print("\n✅ ACP E2E TEST PASSED")
        sys.exit(0)
    else:
        print(f"\n❌ ACP E2E TEST FAILED: {results.get('error', 'Unknown')}")
        if results.get("stderr"):
            print("\nAgent stderr:")
            print(results["stderr"][-1000:])
        sys.exit(1)
