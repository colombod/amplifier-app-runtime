"""End-to-end tests for ACP multi-modal content handling via stdio.

Tests that various content types flow correctly through the full ACP protocol:
1. Spawn agent as subprocess (stdio transport)
2. Initialize protocol handshake (verify image capability)
3. Create session
4. Send prompts with different content types
5. Verify responses and warnings

Content types tested:
- Text content (standard)
- Image content (with supported MIME types)
- Mixed text + image content
- Audio content (unsupported - should warn)
- Embedded resources (text and blob)
"""

import asyncio
import asyncio.subprocess as aio_subprocess
import base64
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
    image_block,
    text_block,
)
from acp.schema import (  # type: ignore[import-untyped]
    AgentMessageChunk,
    AudioContentBlock,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    Implementation,
    TextResourceContents,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Minimal 1x1 pixel PNG for testing (base64 encoded)
MINIMAL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
    "DUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# Minimal 1x1 pixel JPEG for testing
MINIMAL_JPEG_BASE64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
    "CAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAA"
    "AAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMB"
    "AAIRAxEAPwCwAB//2Q=="
)


class ContentTestClient(Client):
    """Test client that captures session updates for content verification."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.message_content: list[str] = []
        self.warnings_received: list[str] = []

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
            if hasattr(content, "text"):
                text = content.text
                update_info["text"] = text
                self.message_content.append(text)

                # Track warnings (messages starting with "Note:")
                if text.startswith("Note:"):
                    self.warnings_received.append(text)

                logger.info(f"📝 Agent message: {text[:100]}...")

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


async def create_acp_session() -> tuple[Any, Any, ContentTestClient, aio_subprocess.Process]:
    """Create an ACP session for testing.

    Returns:
        Tuple of (connection, session, client, process)
    """
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

    client = ContentTestClient()
    conn = connect_to_agent(client, proc.stdin, proc.stdout)

    # Initialize
    await asyncio.wait_for(
        conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(
                name="content-type-test",
                title="Content Type Test Client",
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
async def test_image_capability_advertised():
    """Test that the agent advertises image capability in initialize response."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "amplifier_app_runtime.acp",
        stdin=aio_subprocess.PIPE,
        stdout=aio_subprocess.PIPE,
        stderr=aio_subprocess.PIPE,
    )

    try:
        if proc.stdin is None or proc.stdout is None:
            pytest.fail("Agent process does not expose stdio pipes")

        client = ContentTestClient()
        conn = connect_to_agent(client, proc.stdin, proc.stdout)

        init_response = await asyncio.wait_for(
            conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(
                    name="capability-test",
                    title="Capability Test Client",
                    version="1.0.0",
                ),
            ),
            timeout=30.0,
        )

        # Check capabilities
        agent_caps = init_response.agent_capabilities
        prompt_caps = getattr(agent_caps, "promptCapabilities", None)

        assert prompt_caps is not None, "Agent should have promptCapabilities"

        # Verify image is True (we support images)
        image_supported = getattr(prompt_caps, "image", False)
        assert image_supported is True, "Agent should advertise image=True"

        # Verify audio is False (we don't support audio)
        audio_supported = getattr(prompt_caps, "audio", True)
        assert audio_supported is False, "Agent should advertise audio=False"

        logger.info("✅ Image capability correctly advertised")

    finally:
        await cleanup_process(proc)


@pytest.mark.asyncio
async def test_text_only_prompt():
    """Test that text-only prompts work correctly (regression test)."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send text-only prompt
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[text_block("Say exactly 'Text prompt received' and nothing else.")],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        logger.info("✅ Text-only prompt test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_image_with_text_prompt():
    """Test that image + text prompts are processed correctly."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send image with text
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[
                    text_block("What color is this 1x1 pixel image? Just say the color."),
                    image_block(data=MINIMAL_PNG_BASE64, mime_type="image/png"),
                ],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Should not have any warnings for valid image
        assert len(client.warnings_received) == 0, (
            f"Unexpected warnings: {client.warnings_received}"
        )

        logger.info("✅ Image + text prompt test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_jpeg_image_supported():
    """Test that JPEG images are processed correctly."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[
                    text_block("Describe this image briefly."),
                    image_block(data=MINIMAL_JPEG_BASE64, mime_type="image/jpeg"),
                ],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"
        assert len(client.warnings_received) == 0, "JPEG should not generate warnings"

        logger.info("✅ JPEG image test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_audio_content_generates_warning():
    """Test that audio content generates a warning message."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send audio content (not supported)
        audio_block = AudioContentBlock(
            type="audio",
            mimeType="audio/wav",
            data=base64.b64encode(b"fake audio data").decode(),
        )

        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[
                    text_block("Process this audio."),
                    audio_block,
                ],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"

        # Should have received a warning about audio
        assert len(client.warnings_received) > 0, "Expected warning for audio content"
        assert any("Audio" in w for w in client.warnings_received), (
            f"Expected audio warning, got: {client.warnings_received}"
        )

        logger.info("✅ Audio warning test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_embedded_text_resource():
    """Test that embedded text resources are processed correctly."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Create embedded text resource
        resource = TextResourceContents(
            uri="file:///test/code.py",
            text="def hello():\n    return 'world'",
            mimeType="text/x-python",
        )
        embedded_block = EmbeddedResourceContentBlock(type="resource", resource=resource)

        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[
                    text_block("What does this function return?"),
                    embedded_block,
                ],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "No response content received"

        # Response should mention 'world' (the return value)
        assert "world" in full_response.lower(), (
            f"Expected 'world' in response: {full_response[:200]}"
        )

        logger.info("✅ Embedded text resource test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_mixed_content_with_unsupported():
    """Test mixed content where some types are unsupported."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Mix supported (text, image) with unsupported (audio)
        audio_block = AudioContentBlock(
            type="audio",
            mimeType="audio/mp3",
            data=base64.b64encode(b"fake audio").decode(),
        )

        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[
                    text_block("Describe what you can see and hear."),
                    image_block(data=MINIMAL_PNG_BASE64, mime_type="image/png"),
                    audio_block,
                ],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"

        # Should have warning for audio but still process text + image
        assert any("Audio" in w for w in client.warnings_received), (
            "Expected audio warning in mixed content"
        )

        full_response = "".join(client.message_content)
        assert len(full_response) > 0, "Should still have response despite unsupported audio"

        logger.info("✅ Mixed content test passed")

    finally:
        if proc:
            await cleanup_process(proc)


@pytest.mark.asyncio
async def test_unsupported_image_type_warning():
    """Test that unsupported image MIME types generate warnings."""
    proc = None
    try:
        conn, session, client, proc = await create_acp_session()

        # Send BMP image (not in supported list)
        response = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[
                    text_block("Describe this image."),
                    image_block(data="fakebmpdata", mime_type="image/bmp"),
                ],
            ),
            timeout=120.0,
        )

        assert response.stop_reason == "end_turn"

        # Should have warning about unsupported image type
        assert any("Unsupported image type" in w for w in client.warnings_received), (
            f"Expected image type warning, got: {client.warnings_received}"
        )

        logger.info("✅ Unsupported image type warning test passed")

    finally:
        if proc:
            await cleanup_process(proc)


if __name__ == "__main__":
    print("=" * 60)
    print("ACP Content Types End-to-End Test")
    print("=" * 60)
    print("\nThis test spawns the Amplifier agent as a subprocess")
    print("and tests multi-modal content handling via the ACP protocol.\n")

    async def run_all_tests():
        tests = [
            ("test_image_capability_advertised", test_image_capability_advertised),
            ("test_text_only_prompt", test_text_only_prompt),
            ("test_image_with_text_prompt", test_image_with_text_prompt),
            ("test_jpeg_image_supported", test_jpeg_image_supported),
            ("test_audio_content_generates_warning", test_audio_content_generates_warning),
            ("test_embedded_text_resource", test_embedded_text_resource),
            ("test_mixed_content_with_unsupported", test_mixed_content_with_unsupported),
            ("test_unsupported_image_type_warning", test_unsupported_image_type_warning),
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
