"""Tests for Agent Client Protocol (ACP) implementation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from amplifier_server_app.acp import (
    PROTOCOL_VERSION,
    AgentCapabilities,
    AgentInfo,
    ClientCapabilities,
    ClientInfo,
    InitializeRequest,
    InitializeResponse,
    JsonRpcError,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    NewSessionRequest,
    NewSessionResponse,
    PromptRequest,
    PromptResponse,
    SessionMode,
    SessionModes,
    SessionUpdate,
    SessionUpdateType,
    StopReason,
    TextContent,
    ToolCall,
    ToolCallStatus,
)
from amplifier_server_app.acp.transport import (
    HttpAcpTransport,
    JsonRpcProcessor,
    JsonRpcProtocolError,
    WebSocketAcpTransport,
)
from amplifier_server_app.acp.types import JsonRpcErrorCode

# =============================================================================
# JSON-RPC Types Tests
# =============================================================================


class TestJsonRpcTypes:
    """Tests for JSON-RPC 2.0 types."""

    def test_request_serialization(self) -> None:
        """Request serializes to valid JSON-RPC 2.0."""
        request = JsonRpcRequest(
            id="req_1",
            method="initialize",
            params={"protocolVersion": PROTOCOL_VERSION},
        )
        data = json.loads(request.model_dump_json())

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req_1"
        assert data["method"] == "initialize"
        assert data["params"]["protocolVersion"] == PROTOCOL_VERSION

    def test_response_with_result(self) -> None:
        """Response with result serializes correctly."""
        response = JsonRpcResponse(
            id="req_1",
            result={"sessionId": "sess_123"},
        )
        data = json.loads(response.model_dump_json())

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req_1"
        assert data["result"]["sessionId"] == "sess_123"
        assert data.get("error") is None

    def test_response_with_error(self) -> None:
        """Response with error serializes correctly."""
        response = JsonRpcResponse(
            id="req_1",
            error=JsonRpcError(
                code=-32600,
                message="Invalid Request",
            ),
        )
        data = json.loads(response.model_dump_json())

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req_1"
        assert data["error"]["code"] == -32600
        assert data["error"]["message"] == "Invalid Request"

    def test_notification_no_id(self) -> None:
        """Notification has no id field."""
        notification = JsonRpcNotification(
            method="session/update",
            params={"sessionId": "sess_123"},
        )
        data = json.loads(notification.model_dump_json())

        assert data["jsonrpc"] == "2.0"
        assert "id" not in data
        assert data["method"] == "session/update"


# =============================================================================
# ACP Types Tests
# =============================================================================


class TestAcpTypes:
    """Tests for ACP-specific types."""

    def test_initialize_request(self) -> None:
        """InitializeRequest serializes with camelCase."""
        request = InitializeRequest(
            protocolVersion=PROTOCOL_VERSION,
            clientInfo=ClientInfo(name="test-client", version="1.0.0"),
            clientCapabilities=ClientCapabilities(),
        )
        data = request.model_dump(exclude_none=True)

        assert data["protocolVersion"] == PROTOCOL_VERSION
        assert data["clientInfo"]["name"] == "test-client"

    def test_initialize_response(self) -> None:
        """InitializeResponse includes agent capabilities."""
        response = InitializeResponse(
            protocolVersion=PROTOCOL_VERSION,
            agentInfo=AgentInfo(name="amplifier-server", version="0.1.0"),
            agentCapabilities=AgentCapabilities(loadSession=True),
        )
        data = response.model_dump(exclude_none=True)

        assert data["protocolVersion"] == PROTOCOL_VERSION
        assert data["agentInfo"]["name"] == "amplifier-server"
        assert data["agentCapabilities"]["loadSession"] is True

    def test_new_session_request(self) -> None:
        """NewSessionRequest includes working directory."""
        request = NewSessionRequest(cwd="/home/user/project")
        data = request.model_dump(exclude_none=True)

        assert data["cwd"] == "/home/user/project"

    def test_new_session_response(self) -> None:
        """NewSessionResponse includes session ID and modes."""
        response = NewSessionResponse(
            sessionId="acp_123456",
            modes=SessionModes(
                availableModes=[
                    SessionMode(id="default", name="Default"),
                ],
                currentMode="default",
            ),
        )
        data = response.model_dump(exclude_none=True)

        assert data["sessionId"] == "acp_123456"
        assert len(data["modes"]["availableModes"]) == 1
        assert data["modes"]["currentMode"] == "default"

    def test_prompt_request(self) -> None:
        """PromptRequest includes content blocks."""
        request = PromptRequest(
            sessionId="acp_123456",
            prompt=[TextContent(text="Hello, world!")],
        )
        data = request.model_dump(exclude_none=True)

        assert data["sessionId"] == "acp_123456"
        assert len(data["prompt"]) == 1
        assert data["prompt"][0]["type"] == "text"
        assert data["prompt"][0]["text"] == "Hello, world!"

    def test_prompt_response(self) -> None:
        """PromptResponse includes stop reason."""
        response = PromptResponse(stopReason=StopReason.END_TURN)
        data = response.model_dump(exclude_none=True)

        assert data["stopReason"] == "end_turn"

    def test_session_update(self) -> None:
        """SessionUpdate notification structure."""
        update = SessionUpdate(
            sessionId="acp_123456",
            type=SessionUpdateType.AGENT_MESSAGE_CHUNK,
            data={"content": [{"type": "text", "text": "Hello"}]},
        )
        data = update.model_dump(exclude_none=True)

        assert data["sessionId"] == "acp_123456"
        assert data["type"] == "agent_message_chunk"
        assert data["data"]["content"][0]["text"] == "Hello"

    def test_tool_call(self) -> None:
        """ToolCall includes status."""
        tool_call = ToolCall(
            id="tc_123",
            name="read_file",
            arguments={"path": "/tmp/test.txt"},
            status=ToolCallStatus.RUNNING,
        )
        data = tool_call.model_dump(exclude_none=True)

        assert data["id"] == "tc_123"
        assert data["name"] == "read_file"
        assert data["status"] == "running"


# =============================================================================
# JSON-RPC Processor Tests
# =============================================================================


class TestJsonRpcProcessor:
    """Tests for JSON-RPC message processing."""

    @pytest.fixture
    def processor(self) -> JsonRpcProcessor:
        """Create a processor instance."""
        return JsonRpcProcessor()

    @pytest.mark.asyncio
    async def test_process_valid_request(self, processor: JsonRpcProcessor) -> None:
        """Process valid request calls handler."""
        handler = AsyncMock(return_value={"result": "ok"})
        processor.set_request_handler(handler)

        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req_1",
                "method": "test",
                "params": {"key": "value"},
            }
        )

        response = await processor.process_message(message)

        assert response is not None
        assert response.id == "req_1"
        assert response.result == {"result": "ok"}
        handler.assert_called_once_with("test", {"key": "value"})

    @pytest.mark.asyncio
    async def test_process_notification(self, processor: JsonRpcProcessor) -> None:
        """Process notification calls handler, returns None."""
        handler = AsyncMock()
        processor.set_notification_handler(handler)

        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "session/cancel",
                "params": {"sessionId": "sess_123"},
            }
        )

        response = await processor.process_message(message)

        assert response is None
        handler.assert_called_once_with("session/cancel", {"sessionId": "sess_123"})

    @pytest.mark.asyncio
    async def test_process_invalid_json(self, processor: JsonRpcProcessor) -> None:
        """Invalid JSON returns parse error."""
        response = await processor.process_message("not valid json")

        assert response is not None
        assert response.error is not None
        assert response.error.code == JsonRpcErrorCode.PARSE_ERROR

    @pytest.mark.asyncio
    async def test_process_missing_method(self, processor: JsonRpcProcessor) -> None:
        """Missing method returns invalid request error."""
        message = json.dumps({"jsonrpc": "2.0", "id": "req_1"})

        response = await processor.process_message(message)

        assert response is not None
        assert response.error is not None
        assert response.error.code == JsonRpcErrorCode.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_process_handler_exception(self, processor: JsonRpcProcessor) -> None:
        """Handler exception returns error response."""
        handler = AsyncMock(
            side_effect=JsonRpcProtocolError(
                code=-32001,
                message="Session not found",
            )
        )
        processor.set_request_handler(handler)

        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req_1",
                "method": "test",
            }
        )

        response = await processor.process_message(message)

        assert response is not None
        assert response.error is not None
        assert response.error.code == -32001
        assert response.error.message == "Session not found"


# =============================================================================
# HTTP Transport Tests
# =============================================================================


class TestHttpAcpTransport:
    """Tests for HTTP ACP transport."""

    @pytest.fixture
    def transport(self) -> HttpAcpTransport:
        """Create transport instance."""
        return HttpAcpTransport()

    @pytest.mark.asyncio
    async def test_handle_request(self, transport: HttpAcpTransport) -> None:
        """Handle request returns JSON response."""
        handler = AsyncMock(return_value={"key": "value"})
        transport.on_request(handler)

        request_data = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req_1",
                "method": "test",
            }
        )

        response_data = await transport.handle_request(request_data)
        response = json.loads(response_data)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req_1"
        assert response["result"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_send_notification(self, transport: HttpAcpTransport) -> None:
        """Send notification to all connected clients."""
        notification = JsonRpcNotification(
            method="session/update",
            params={"sessionId": "sess_123"},
        )

        # Create a stream and collect notifications
        collected: list[JsonRpcNotification] = []

        async def collect_notifications():
            async for n in transport.notification_stream():
                collected.append(n)
                break  # Just collect one

        import asyncio

        task = asyncio.create_task(collect_notifications())

        # Give the stream time to register
        await asyncio.sleep(0.01)

        await transport.send_notification(notification)

        # Wait for collection
        await asyncio.wait_for(task, timeout=1.0)

        assert len(collected) == 1
        assert collected[0].method == "session/update"


# =============================================================================
# WebSocket Transport Tests
# =============================================================================


class TestWebSocketAcpTransport:
    """Tests for WebSocket ACP transport."""

    @pytest.mark.asyncio
    async def test_send_response(self) -> None:
        """Send response via WebSocket."""
        send_func = AsyncMock()
        transport = WebSocketAcpTransport(send_func)
        await transport.start()

        response = JsonRpcResponse(id="req_1", result={"ok": True})
        await transport.send_response(response)

        send_func.assert_called_once()
        sent_data = json.loads(send_func.call_args[0][0])
        assert sent_data["id"] == "req_1"
        assert sent_data["result"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_send_notification(self) -> None:
        """Send notification via WebSocket."""
        send_func = AsyncMock()
        transport = WebSocketAcpTransport(send_func)
        await transport.start()

        notification = JsonRpcNotification(
            method="session/update",
            params={"sessionId": "sess_123"},
        )
        await transport.send_notification(notification)

        send_func.assert_called_once()
        sent_data = json.loads(send_func.call_args[0][0])
        assert sent_data["method"] == "session/update"

    @pytest.mark.asyncio
    async def test_handle_message_routes_to_handler(self) -> None:
        """Handle message routes to registered handler."""
        send_func = AsyncMock()
        transport = WebSocketAcpTransport(send_func)

        handler = AsyncMock(return_value={"result": "ok"})
        transport.on_request(handler)

        await transport.start()

        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req_1",
                "method": "test",
                "params": {"key": "value"},
            }
        )

        await transport.handle_message(message)

        handler.assert_called_once_with("test", {"key": "value"})
        # Response should be sent
        assert send_func.call_count == 1

    @pytest.mark.asyncio
    async def test_stopped_transport_doesnt_send(self) -> None:
        """Stopped transport doesn't send messages."""
        send_func = AsyncMock()
        transport = WebSocketAcpTransport(send_func)
        await transport.start()
        await transport.stop()

        response = JsonRpcResponse(id="req_1", result={})
        await transport.send_response(response)

        send_func.assert_not_called()


# =============================================================================
# Content Types Tests
# =============================================================================


class TestContentTypes:
    """Tests for ACP content types."""

    def test_text_content(self) -> None:
        """TextContent serializes correctly."""
        content = TextContent(text="Hello, world!")
        data = content.model_dump()

        assert data["type"] == "text"
        assert data["text"] == "Hello, world!"

    def test_stop_reason_enum(self) -> None:
        """StopReason enum values match protocol."""
        assert StopReason.END_TURN.value == "end_turn"
        assert StopReason.MAX_TOKENS.value == "max_tokens"
        assert StopReason.TOOL_USE.value == "tool_use"
        assert StopReason.CANCELLED.value == "cancelled"
        assert StopReason.ERROR.value == "error"

    def test_tool_call_status_enum(self) -> None:
        """ToolCallStatus enum values match protocol."""
        assert ToolCallStatus.PENDING.value == "pending"
        assert ToolCallStatus.RUNNING.value == "running"
        assert ToolCallStatus.COMPLETED.value == "completed"
        assert ToolCallStatus.FAILED.value == "failed"
        assert ToolCallStatus.CANCELLED.value == "cancelled"

    def test_session_update_type_enum(self) -> None:
        """SessionUpdateType enum values match protocol."""
        assert SessionUpdateType.AGENT_MESSAGE_CHUNK.value == "agent_message_chunk"
        assert SessionUpdateType.TOOL_CALL_START.value == "tool_call_start"
        assert SessionUpdateType.TOOL_CALL_END.value == "tool_call_end"
        assert SessionUpdateType.THOUGHT_CHUNK.value == "thought_chunk"


# =============================================================================
# Protocol Version Tests
# =============================================================================


class TestProtocolVersion:
    """Tests for protocol version handling."""

    def test_protocol_version_format(self) -> None:
        """Protocol version follows date format."""
        # Should be in YYYY-MM-DD format
        parts = PROTOCOL_VERSION.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # Year
        assert len(parts[1]) == 2  # Month
        assert len(parts[2]) == 2  # Day
