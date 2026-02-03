"""Tests for Agent Client Protocol (ACP) implementation.

Updated to use the official ACP SDK types. Some tests have been updated
to reflect the new type structure from agent-client-protocol SDK.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from amplifier_app_runtime.acp import (
    PROTOCOL_VERSION,
    AgentCapabilities,
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResponse,
    NewSessionRequest,
    NewSessionResponse,
    PromptRequest,
    PromptResponse,
    SessionMode,
    SessionModeState,
    TextContentBlock,
)
from amplifier_app_runtime.acp.transport import (
    HttpAcpTransport,
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcNotification,
    JsonRpcProcessor,
    JsonRpcProtocolError,
    JsonRpcResponse,
    WebSocketAcpTransport,
)

# =============================================================================
# JSON-RPC Types Tests
# =============================================================================


class TestJsonRpcTypes:
    """Tests for JSON-RPC 2.0 types."""

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
    """Tests for ACP-specific types from the official SDK."""

    def test_initialize_request(self) -> None:
        """InitializeRequest serializes with camelCase."""
        # Using Implementation instead of ClientInfo (SDK change)
        request = InitializeRequest(
            protocolVersion=PROTOCOL_VERSION,
            clientInfo=Implementation(name="test-client", version="1.0.0"),
            clientCapabilities=ClientCapabilities(),
        )
        data = request.model_dump(exclude_none=True, by_alias=True)

        assert data["protocolVersion"] == PROTOCOL_VERSION
        assert data["clientInfo"]["name"] == "test-client"

    def test_initialize_response(self) -> None:
        """InitializeResponse includes agent capabilities."""
        # Using Implementation instead of AgentInfo (SDK change)
        response = InitializeResponse(
            protocolVersion=PROTOCOL_VERSION,
            agentInfo=Implementation(name="amplifier-runtime", version="0.1.0"),
            agentCapabilities=AgentCapabilities(loadSession=True),
        )
        data = response.model_dump(exclude_none=True, by_alias=True)

        assert data["protocolVersion"] == PROTOCOL_VERSION
        assert data["agentInfo"]["name"] == "amplifier-runtime"
        assert data["agentCapabilities"]["loadSession"] is True

    def test_new_session_request(self) -> None:
        """NewSessionRequest includes working directory."""
        # mcp_servers is required in the SDK
        request = NewSessionRequest(cwd="/home/user/project", mcp_servers=[])
        data = request.model_dump(exclude_none=True, by_alias=True)

        assert data["cwd"] == "/home/user/project"
        assert data["mcpServers"] == []

    def test_new_session_response(self) -> None:
        """NewSessionResponse includes session ID and modes."""
        # SessionModeState uses snake_case field names internally
        response = NewSessionResponse(
            session_id="acp_123456",
            modes=SessionModeState(
                available_modes=[
                    SessionMode(id="default", name="Default"),
                ],
                current_mode_id="default",
            ),
        )
        data = response.model_dump(exclude_none=True, by_alias=True)

        assert data["sessionId"] == "acp_123456"
        assert len(data["modes"]["availableModes"]) == 1
        assert data["modes"]["currentModeId"] == "default"

    def test_prompt_request(self) -> None:
        """PromptRequest includes content blocks."""
        # TextContentBlock replaces TextContent in the SDK
        request = PromptRequest(
            sessionId="acp_123456",
            prompt=[TextContentBlock(type="text", text="Hello, world!")],
        )
        data = request.model_dump(exclude_none=True, by_alias=True)

        assert data["sessionId"] == "acp_123456"
        assert len(data["prompt"]) == 1
        assert data["prompt"][0]["type"] == "text"
        assert data["prompt"][0]["text"] == "Hello, world!"

    def test_prompt_response(self) -> None:
        """PromptResponse includes stop reason."""
        # StopReason is a Literal type, use string value directly
        response = PromptResponse(stopReason="end_turn")
        data = response.model_dump(exclude_none=True, by_alias=True)

        assert data["stopReason"] == "end_turn"


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

    def test_text_content_block(self) -> None:
        """TextContentBlock serializes correctly."""
        content = TextContentBlock(type="text", text="Hello, world!")
        data = content.model_dump(by_alias=True)

        assert data["type"] == "text"
        assert data["text"] == "Hello, world!"

    def test_stop_reason_values(self) -> None:
        """StopReason Literal type accepts valid values."""
        # StopReason is a Literal type, not an enum
        # Valid values: 'end_turn', 'max_tokens', 'max_turn_requests', 'refusal', 'cancelled'
        response1 = PromptResponse(stopReason="end_turn")
        response2 = PromptResponse(stopReason="max_tokens")
        response3 = PromptResponse(stopReason="cancelled")

        assert response1.stopReason == "end_turn"
        assert response2.stopReason == "max_tokens"
        assert response3.stopReason == "cancelled"

    def test_tool_call_status_values(self) -> None:
        """ToolCallStatus Literal type accepts valid values."""
        # ToolCallStatus is a Literal type: 'pending', 'in_progress', 'completed', 'failed'
        from amplifier_app_runtime.acp import ToolCallStart

        # ToolCallStart requires title, tool_call_id, and session_update='tool_call'
        tc = ToolCallStart(
            title="Reading file",
            tool_call_id="tc_123",
            session_update="tool_call",
            status="pending",
        )
        assert tc.tool_call_id == "tc_123"
        assert tc.status == "pending"


# =============================================================================
# Protocol Version Tests
# =============================================================================


class TestProtocolVersion:
    """Tests for protocol version handling."""

    def test_protocol_version_is_integer(self) -> None:
        """Protocol version is an integer (ACP SDK v1)."""
        # PROTOCOL_VERSION is an int in the current SDK
        assert isinstance(PROTOCOL_VERSION, int)
        assert PROTOCOL_VERSION >= 1


# =============================================================================
# ACP Event Mapping Tests
# =============================================================================


class TestToolTitleGeneration:
    """Tests for tool title generation in ACP agent."""

    def test_read_file_title(self) -> None:
        """Read file tool generates descriptive title."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        title = session._generate_tool_title("read_file", {"file_path": "/tmp/test.py"})
        assert "Reading" in title
        assert "/tmp/test.py" in title

    def test_write_file_title(self) -> None:
        """Write file tool generates descriptive title."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        title = session._generate_tool_title("write_file", {"file_path": "/tmp/output.txt"})
        assert "Writing" in title
        assert "/tmp/output.txt" in title

    def test_bash_title(self) -> None:
        """Bash tool generates generic title."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        title = session._generate_tool_title("bash", {"command": "ls -la"})
        assert title == "Running command"

    def test_unknown_tool_title(self) -> None:
        """Unknown tools get humanized title."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        title = session._generate_tool_title("my_custom_tool", {})
        assert title == "My Custom Tool"


class TestToolKindInference:
    """Tests for inferring ACP tool kind from tool name."""

    def test_read_operations(self) -> None:
        """Read tools map to 'read' kind."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        assert session._infer_tool_kind("read_file") == "read"
        assert session._infer_tool_kind("glob") == "read"
        assert session._infer_tool_kind("load_skill") == "read"

    def test_edit_operations(self) -> None:
        """Edit tools map to 'edit' kind."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        assert session._infer_tool_kind("write_file") == "edit"
        assert session._infer_tool_kind("edit_file") == "edit"

    def test_search_operations(self) -> None:
        """Search tools map to 'search' kind."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        assert session._infer_tool_kind("grep") == "search"
        assert session._infer_tool_kind("web_search") == "search"

    def test_execute_operations(self) -> None:
        """Execute tools map to 'execute' kind."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        assert session._infer_tool_kind("bash") == "execute"
        assert session._infer_tool_kind("python_check") == "execute"

    def test_think_operations(self) -> None:
        """Think/planning tools map to 'think' kind."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        assert session._infer_tool_kind("todo") == "think"
        assert session._infer_tool_kind("task") == "think"

    def test_unknown_tools(self) -> None:
        """Unknown tools map to 'other' kind."""
        from amplifier_app_runtime.acp.agent import AmplifierAgentSession

        session = AmplifierAgentSession(
            session_id="test",
            cwd="/tmp",
            bundle="foundation",
            conn=None,
        )
        assert session._infer_tool_kind("my_custom_tool") == "other"
        assert session._infer_tool_kind("unknown") == "other"


class TestAgentPlanMapping:
    """Tests for mapping Amplifier todos to ACP plan updates."""

    def test_plan_entry_creation(self) -> None:
        """PlanEntry can be created with required fields."""
        from acp.schema import PlanEntry

        entry = PlanEntry(
            content="Implement feature X",
            priority="high",
            status="pending",
        )
        assert entry.content == "Implement feature X"
        assert entry.priority == "high"
        assert entry.status == "pending"

    def test_agent_plan_update_creation(self) -> None:
        """AgentPlanUpdate can be created with entries."""
        from acp.schema import AgentPlanUpdate, PlanEntry

        entries = [
            PlanEntry(content="Task 1", priority="high", status="completed"),
            PlanEntry(content="Task 2", priority="medium", status="in_progress"),
            PlanEntry(content="Task 3", priority="low", status="pending"),
        ]
        plan = AgentPlanUpdate(session_update="plan", entries=entries)

        assert plan.session_update == "plan"
        assert len(plan.entries) == 3
        assert plan.entries[0].status == "completed"
        assert plan.entries[1].status == "in_progress"
        assert plan.entries[2].status == "pending"

    def test_plan_serialization(self) -> None:
        """AgentPlanUpdate serializes to correct JSON format."""
        from acp.schema import AgentPlanUpdate, PlanEntry

        plan = AgentPlanUpdate(
            session_update="plan",
            entries=[
                PlanEntry(content="Build feature", priority="high", status="in_progress"),
            ],
        )
        data = plan.model_dump(by_alias=True, exclude_none=True)

        assert data["sessionUpdate"] == "plan"
        assert len(data["entries"]) == 1
        assert data["entries"][0]["content"] == "Build feature"
        assert data["entries"][0]["priority"] == "high"
        assert data["entries"][0]["status"] == "in_progress"


class TestToolCallProtocolAlignment:
    """Tests for ACP tool call protocol compliance."""

    def test_tool_call_start_required_fields(self) -> None:
        """ToolCallStart requires session_update, tool_call_id, and title."""
        from acp.schema import ToolCallStart

        tc = ToolCallStart(
            session_update="tool_call",
            tool_call_id="call_123",
            title="Reading configuration",
        )
        assert tc.session_update == "tool_call"
        assert tc.tool_call_id == "call_123"
        assert tc.title == "Reading configuration"

    def test_tool_call_start_with_kind_and_status(self) -> None:
        """ToolCallStart accepts kind and status."""
        from acp.schema import ToolCallStart

        tc = ToolCallStart(
            session_update="tool_call",
            tool_call_id="call_456",
            title="Editing file",
            kind="edit",
            status="pending",
            raw_input={"file_path": "/tmp/test.py", "content": "..."},
        )
        assert tc.kind == "edit"
        assert tc.status == "pending"
        assert tc.raw_input == {"file_path": "/tmp/test.py", "content": "..."}

    def test_tool_call_update_status_values(self) -> None:
        """ToolCallUpdate status uses correct values."""
        from acp.schema import ToolCallUpdate

        # Completed
        tc1 = ToolCallUpdate(tool_call_id="call_1", status="completed")
        assert tc1.status == "completed"

        # Failed (not 'error')
        tc2 = ToolCallUpdate(tool_call_id="call_2", status="failed")
        assert tc2.status == "failed"

        # In progress
        tc3 = ToolCallUpdate(tool_call_id="call_3", status="in_progress")
        assert tc3.status == "in_progress"

    def test_tool_call_serialization(self) -> None:
        """Tool calls serialize with camelCase aliases."""
        from acp.schema import ToolCallStart

        tc = ToolCallStart(
            session_update="tool_call",
            tool_call_id="call_789",
            title="Searching codebase",
            kind="search",
            status="pending",
        )
        data = tc.model_dump(by_alias=True, exclude_none=True)

        # Check camelCase serialization
        assert data["sessionUpdate"] == "tool_call"
        assert data["toolCallId"] == "call_789"
        assert data["title"] == "Searching codebase"
        assert data["kind"] == "search"
        assert data["status"] == "pending"
