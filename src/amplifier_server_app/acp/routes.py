"""ACP HTTP routes for remote agents.

Provides HTTP and WebSocket endpoints for ACP protocol:
- POST /acp/rpc - JSON-RPC endpoint for requests
- GET /acp/events - SSE endpoint for notifications
- WebSocket /acp/ws - Full-duplex WebSocket transport

Uses the SDK-based AmplifierAgent for proper ACP protocol handling.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from starlette.requests import Request  # type: ignore[import-untyped]
from starlette.responses import (  # type: ignore[import-untyped]
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route, WebSocketRoute  # type: ignore[import-untyped]
from starlette.websockets import WebSocket, WebSocketDisconnect  # type: ignore[import-untyped]

from .agent import AmplifierAgent
from .transport import JsonRpcNotification

logger = logging.getLogger(__name__)


class HttpAgentConnection:
    """Fake Client connection that routes session_update() to HTTP SSE.

    The ACP SDK's Agent expects a Client with session_update() method.
    This adapter captures those calls and queues them for SSE delivery.
    """

    def __init__(self, notification_queue: asyncio.Queue[JsonRpcNotification]) -> None:
        self._queue = notification_queue

    async def session_update(self, session_id: str, update: Any) -> None:
        """Send a session update notification.

        This is called by the Agent when it wants to stream updates.
        We convert it to a JSON-RPC notification and queue for SSE.
        """
        # Convert update to dict if it has model_dump
        update_dict = (
            update.model_dump(exclude_none=True, by_alias=True)
            if hasattr(update, "model_dump")
            else update
        )

        notification = JsonRpcNotification(
            method="session/update",
            params={
                "sessionId": session_id,
                "update": update_dict,
            },
        )
        await self._queue.put(notification)


class HttpAgentHandler:
    """Handles HTTP requests using the SDK-based AmplifierAgent.

    This bridges HTTP JSON-RPC requests to the Agent interface.
    """

    def __init__(self) -> None:
        self._notification_queue: asyncio.Queue[JsonRpcNotification] = asyncio.Queue()
        self._conn = HttpAgentConnection(self._notification_queue)
        self._agent = AmplifierAgent()
        self._agent.on_connect(self._conn)  # type: ignore[arg-type]
        self._initialized = False

    async def handle_request(
        self, method: str, params: dict[str, Any] | None, request_id: Any
    ) -> dict[str, Any]:
        """Route a JSON-RPC request to the appropriate Agent method."""
        params = params or {}

        try:
            result = await self._dispatch(method, params)

            # Convert result to dict if needed
            if hasattr(result, "model_dump"):
                result_dict = result.model_dump(exclude_none=True, by_alias=True)
            else:
                result_dict = result

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result_dict,
            }

        except Exception as e:
            logger.exception(f"Error handling {method}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                },
            }

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Dispatch to the appropriate Agent method."""

        if method == "initialize":
            self._initialized = True
            return await self._agent.initialize(
                protocol_version=params.get("protocolVersion", 1),
                client_capabilities=params.get("clientCapabilities"),
                client_info=params.get("clientInfo"),
            )

        if not self._initialized:
            raise RuntimeError("Not initialized. Call 'initialize' first.")

        if method == "session/new":
            return await self._agent.new_session(
                cwd=params.get("cwd", "."),
                mcp_servers=params.get("mcpServers", []),
                **{k: v for k, v in params.items() if k not in ("cwd", "mcpServers")},
            )

        if method == "session/load":
            return await self._agent.load_session(
                cwd=params.get("cwd", "."),
                mcp_servers=params.get("mcpServers", []),
                session_id=params.get("sessionId", ""),
            )

        if method == "session/prompt":
            # Import here to avoid circular imports
            from acp.schema import TextContentBlock  # type: ignore[import-untyped]

            # Convert prompt blocks
            prompt_blocks = []
            for block in params.get("prompt", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt_blocks.append(TextContentBlock(type="text", text=block.get("text", "")))
                else:
                    prompt_blocks.append(block)

            return await self._agent.prompt(
                prompt=prompt_blocks,
                session_id=params.get("sessionId", ""),
            )

        if method == "session/set_mode":
            return await self._agent.set_session_mode(
                mode_id=params.get("modeId", "default"),
                session_id=params.get("sessionId", ""),
            )

        if method == "session/cancel":
            await self._agent.cancel(session_id=params.get("sessionId", ""))
            return None

        if method == "session/list":
            return await self._agent.list_sessions(
                cursor=params.get("cursor"),
                cwd=params.get("cwd"),
            )

        if method == "session/fork":
            return await self._agent.fork_session(
                cwd=params.get("cwd", "."),
                session_id=params.get("sessionId", ""),
                mcp_servers=params.get("mcpServers", []),
            )

        if method == "session/resume":
            return await self._agent.resume_session(
                cwd=params.get("cwd", "."),
                session_id=params.get("sessionId", ""),
                mcp_servers=params.get("mcpServers", []),
            )

        raise RuntimeError(f"Unknown method: {method}")

    async def notification_stream(self):
        """Yield notifications for SSE streaming."""
        while True:
            notification = await self._notification_queue.get()
            yield notification


# Global handler instance
_http_handler: HttpAgentHandler | None = None


def get_http_handler() -> HttpAgentHandler:
    """Get or create the HTTP handler."""
    global _http_handler

    if _http_handler is None:
        _http_handler = HttpAgentHandler()

    return _http_handler


# =============================================================================
# HTTP Endpoints
# =============================================================================


async def acp_rpc_post(request: Request) -> Response:
    """Handle POST requests to the JSON-RPC endpoint."""
    handler = get_http_handler()

    try:
        body = await request.body()
        data = json.loads(body.decode("utf-8"))

        method = data.get("method", "")
        params = data.get("params")
        request_id = data.get("id")

        response_data = await handler.handle_request(method, params, request_id)

        return JSONResponse(content=response_data)

    except json.JSONDecodeError as e:
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {e}",
                },
            },
            status_code=400,
        )
    except Exception as e:
        logger.exception(f"ACP RPC error: {e}")
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": str(e),
                },
            },
            status_code=500,
        )


async def acp_events_endpoint(request: Request) -> Response:
    """SSE endpoint for ACP notifications.

    GET /acp/events

    Streams session/update notifications to the client.
    """
    handler = get_http_handler()

    async def event_stream():
        """Generate SSE events from notifications."""
        try:
            async for notification in handler.notification_stream():
                # Format as SSE
                data = notification.model_dump_json(exclude_none=True, by_alias=True)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.exception(f"SSE stream error: {e}")
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# WebSocket Endpoint
# =============================================================================


async def acp_websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for full-duplex ACP communication.

    WebSocket /acp/ws

    Supports bidirectional JSON-RPC messaging:
    - Client sends requests/notifications
    - Server sends responses/notifications
    """
    await websocket.accept()

    # Create a notification queue for this WebSocket
    notification_queue: asyncio.Queue[JsonRpcNotification] = asyncio.Queue()
    conn = HttpAgentConnection(notification_queue)
    agent = AmplifierAgent()
    agent.on_connect(conn)  # type: ignore[arg-type]

    # Create handler for this WebSocket
    handler = HttpAgentHandler()
    handler._agent = agent
    handler._conn = conn
    handler._notification_queue = notification_queue

    async def send_notifications():
        """Send notifications to WebSocket."""
        try:
            while True:
                notification = await notification_queue.get()
                data = notification.model_dump_json(exclude_none=True, by_alias=True)
                await websocket.send_text(data)
        except Exception:
            pass

    # Start notification sender
    notification_task = asyncio.create_task(send_notifications())

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            method = message.get("method", "")
            params = message.get("params")
            request_id = message.get("id")

            if request_id is not None:
                # It's a request - send response
                response = await handler.handle_request(method, params, request_id)
                await websocket.send_text(json.dumps(response))
            else:
                # It's a notification - just dispatch
                try:
                    await handler._dispatch(method, params or {})
                except Exception as e:
                    logger.warning(f"Notification error: {e}")

    except WebSocketDisconnect:
        logger.info("ACP WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"ACP WebSocket error: {e}")
    finally:
        notification_task.cancel()


# =============================================================================
# Route Definitions
# =============================================================================


acp_routes = [
    Route("/acp/rpc", acp_rpc_post, methods=["POST"]),
    Route("/acp/events", acp_events_endpoint, methods=["GET"]),
    WebSocketRoute("/acp/ws", acp_websocket_endpoint),
]


# =============================================================================
# Stdio Runner (for local agents)
# =============================================================================


async def run_acp_stdio() -> None:
    """Run ACP over stdio for local agent mode.

    This is used when the agent runs as a subprocess of the editor.
    Uses the official SDK's run_agent() for proper stdio handling.
    """
    from .agent import run_stdio_agent

    await run_stdio_agent()
