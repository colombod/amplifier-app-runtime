"""Unit tests for WebSocket transport.

Tests the WebSocket transport implementation including:
- Message serialization/deserialization
- Server transport connection handling
- Client transport operations
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_server_app.transport.websocket import (
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketServerTransport,
)

# =============================================================================
# WebSocketMessage Tests
# =============================================================================


class TestWebSocketMessage:
    """Tests for WebSocketMessage serialization."""

    def test_message_to_json_minimal(self) -> None:
        """Message serializes with type and payload."""
        msg = WebSocketMessage(
            type=WebSocketMessageType.PROMPT,
            payload={"content": "Hello"},
        )
        data = json.loads(msg.to_json())

        assert data["type"] == "prompt"
        assert data["payload"] == {"content": "Hello"}
        assert "request_id" not in data

    def test_message_to_json_with_request_id(self) -> None:
        """Message includes request_id when present."""
        msg = WebSocketMessage(
            type=WebSocketMessageType.EVENT,
            payload={"type": "content"},
            request_id="req_123",
        )
        data = json.loads(msg.to_json())

        assert data["type"] == "event"
        assert data["request_id"] == "req_123"

    def test_message_from_json(self) -> None:
        """Message deserializes from JSON."""
        data = json.dumps(
            {
                "type": "prompt",
                "payload": {"content": "Test"},
                "request_id": "req_456",
            }
        )
        msg = WebSocketMessage.from_json(data)

        assert msg.type == WebSocketMessageType.PROMPT
        assert msg.payload == {"content": "Test"}
        assert msg.request_id == "req_456"

    def test_message_from_json_minimal(self) -> None:
        """Message deserializes with missing optional fields."""
        data = json.dumps({"type": "ping"})
        msg = WebSocketMessage.from_json(data)

        assert msg.type == WebSocketMessageType.PING
        assert msg.payload == {}
        assert msg.request_id is None

    def test_message_from_json_invalid_type(self) -> None:
        """Message raises on invalid type."""
        data = json.dumps({"type": "invalid_type"})

        with pytest.raises(ValueError):
            WebSocketMessage.from_json(data)

    def test_message_from_json_invalid_json(self) -> None:
        """Message raises on invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            WebSocketMessage.from_json("not json")


class TestWebSocketMessageTypes:
    """Tests for WebSocketMessageType enum."""

    def test_client_to_server_types(self) -> None:
        """Client-to-server message types exist."""
        assert WebSocketMessageType.PROMPT.value == "prompt"
        assert WebSocketMessageType.ABORT.value == "abort"
        assert WebSocketMessageType.APPROVAL.value == "approval"
        assert WebSocketMessageType.PING.value == "ping"

    def test_server_to_client_types(self) -> None:
        """Server-to-client message types exist."""
        assert WebSocketMessageType.EVENT.value == "event"
        assert WebSocketMessageType.ERROR.value == "error"
        assert WebSocketMessageType.PONG.value == "pong"
        assert WebSocketMessageType.CONNECTED.value == "connected"


# =============================================================================
# WebSocketServerTransport Tests
# =============================================================================


class TestWebSocketServerTransport:
    """Tests for server-side WebSocket transport."""

    def test_initial_state(self) -> None:
        """Transport starts disconnected."""
        mock_ws = MagicMock()
        transport = WebSocketServerTransport(mock_ws)

        assert transport._connected is False

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self) -> None:
        """Connect accepts the WebSocket connection."""
        mock_ws = MagicMock()
        mock_ws.accept = AsyncMock()
        mock_ws.send_text = AsyncMock()
        mock_ws.client_state = MagicMock()
        mock_ws.client_state.name = "CONNECTED"

        # Mock WebSocketState.CONNECTED
        with patch("amplifier_server_app.transport.websocket.WebSocketState") as mock_state:
            mock_state.CONNECTED = mock_ws.client_state

            transport = WebSocketServerTransport(mock_ws)
            await transport.connect()

            mock_ws.accept.assert_called_once()
            assert transport._connected is True

    @pytest.mark.asyncio
    async def test_connect_sends_connected_message(self) -> None:
        """Connect sends connected message with protocol version."""
        mock_ws = MagicMock()
        mock_ws.accept = AsyncMock()
        mock_ws.send_text = AsyncMock()
        mock_ws.client_state = MagicMock()

        with patch("amplifier_server_app.transport.websocket.WebSocketState") as mock_state:
            mock_state.CONNECTED = mock_ws.client_state

            transport = WebSocketServerTransport(mock_ws)
            await transport.connect()

            # Verify connected message was sent
            mock_ws.send_text.assert_called_once()
            sent_data = json.loads(mock_ws.send_text.call_args[0][0])
            assert sent_data["type"] == "connected"
            assert "protocol_version" in sent_data["payload"]

    @pytest.mark.asyncio
    async def test_send_message(self) -> None:
        """send_message sends JSON to WebSocket."""
        mock_ws = MagicMock()
        mock_ws.send_text = AsyncMock()
        mock_ws.client_state = MagicMock()

        with patch("amplifier_server_app.transport.websocket.WebSocketState") as mock_state:
            mock_state.CONNECTED = mock_ws.client_state

            transport = WebSocketServerTransport(mock_ws)
            transport._connected = True

            msg = WebSocketMessage(
                type=WebSocketMessageType.EVENT,
                payload={"type": "content", "text": "Hello"},
            )
            await transport.send_message(msg)

            mock_ws.send_text.assert_called_once()
            sent_data = json.loads(mock_ws.send_text.call_args[0][0])
            assert sent_data["type"] == "event"
            assert sent_data["payload"]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_send_error(self) -> None:
        """send_error sends error message."""
        mock_ws = MagicMock()
        mock_ws.send_text = AsyncMock()
        mock_ws.client_state = MagicMock()

        with patch("amplifier_server_app.transport.websocket.WebSocketState") as mock_state:
            mock_state.CONNECTED = mock_ws.client_state

            transport = WebSocketServerTransport(mock_ws)
            transport._connected = True

            await transport.send_error("Something went wrong", request_id="req_1")

            mock_ws.send_text.assert_called_once()
            sent_data = json.loads(mock_ws.send_text.call_args[0][0])
            assert sent_data["type"] == "error"
            assert sent_data["payload"]["error"] == "Something went wrong"
            assert sent_data["request_id"] == "req_1"

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        """Disconnect closes the WebSocket."""
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        mock_ws.client_state = MagicMock()

        with patch("amplifier_server_app.transport.websocket.WebSocketState") as mock_state:
            mock_state.CONNECTED = mock_ws.client_state

            transport = WebSocketServerTransport(mock_ws)
            transport._connected = True

            await transport.disconnect()

            assert transport._connected is False
            mock_ws.close.assert_called_once()


# =============================================================================
# WebSocket Route Handler Tests
# =============================================================================


class TestWebSocketSessionHandler:
    """Tests for WebSocket session handler."""

    @pytest.mark.asyncio
    async def test_handler_closes_on_missing_session(self) -> None:
        """Handler closes connection if session not found."""
        from amplifier_server_app.routes.websocket import WebSocketSessionHandler

        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()

        handler = WebSocketSessionHandler(mock_ws, "nonexistent_session")

        with patch("amplifier_server_app.routes.websocket.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=None)

            await handler.handle()

            mock_ws.close.assert_called_once()
            args = mock_ws.close.call_args
            assert args[1]["code"] == 4004
            assert "not found" in args[1]["reason"].lower()


class TestWebSocketEndpoints:
    """Tests for WebSocket endpoint functions."""

    @pytest.mark.asyncio
    async def test_session_endpoint_missing_session_id(self) -> None:
        """Session endpoint closes on missing session_id."""
        from amplifier_server_app.routes.websocket import websocket_session_endpoint

        mock_ws = MagicMock()
        mock_ws.path_params = {}
        mock_ws.close = AsyncMock()

        await websocket_session_endpoint(mock_ws)

        mock_ws.close.assert_called_once()
        args = mock_ws.close.call_args
        assert args[1]["code"] == 4000

    @pytest.mark.asyncio
    async def test_session_endpoint_creates_handler(self) -> None:
        """Session endpoint creates handler for valid session_id."""
        from amplifier_server_app.routes.websocket import websocket_session_endpoint

        mock_ws = MagicMock()
        mock_ws.path_params = {"session_id": "sess_123"}
        mock_ws.close = AsyncMock()

        with patch(
            "amplifier_server_app.routes.websocket.WebSocketSessionHandler"
        ) as mock_handler_cls:
            mock_handler = MagicMock()
            mock_handler.handle = AsyncMock()
            mock_handler_cls.return_value = mock_handler

            await websocket_session_endpoint(mock_ws)

            mock_handler_cls.assert_called_once_with(mock_ws, "sess_123")
            mock_handler.handle.assert_called_once()


# =============================================================================
# WebSocket Route Integration Tests
# =============================================================================


class TestWebSocketRoutes:
    """Tests for WebSocket route definitions."""

    def test_websocket_routes_defined(self) -> None:
        """WebSocket routes are properly defined."""
        from amplifier_server_app.routes.websocket import websocket_routes

        assert len(websocket_routes) == 2

        # Check route paths
        paths = [r.path for r in websocket_routes]
        assert "/ws" in paths
        assert "/ws/sessions/{session_id}" in paths

    def test_websocket_routes_exported(self) -> None:
        """WebSocket routes are exported from routes package."""
        from amplifier_server_app.routes import websocket_routes

        assert websocket_routes is not None
        assert len(websocket_routes) >= 2
