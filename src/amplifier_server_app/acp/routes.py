"""ACP HTTP routes for remote agents.

Provides HTTP and WebSocket endpoints for ACP protocol:
- POST /acp/rpc - JSON-RPC endpoint for requests
- GET /acp/events - SSE endpoint for notifications
- WebSocket /acp/ws - Full-duplex WebSocket transport
"""

from __future__ import annotations

import asyncio
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .handler import AcpHandler
from .transport import HttpAcpTransport, WebSocketAcpTransport

logger = logging.getLogger(__name__)

# Global handler instances per transport
_http_transport: HttpAcpTransport | None = None
_http_handler: AcpHandler | None = None


def get_http_handler() -> tuple[HttpAcpTransport, AcpHandler]:
    """Get or create the HTTP transport and handler."""
    global _http_transport, _http_handler

    if _http_transport is None or _http_handler is None:
        _http_transport = HttpAcpTransport()
        _http_handler = AcpHandler(_http_transport)

    return _http_transport, _http_handler


# =============================================================================
# HTTP Endpoints
# =============================================================================


async def acp_rpc_post(request: Request) -> Response:
    """Handle POST requests to the JSON-RPC endpoint."""
    transport, _ = get_http_handler()

    try:
        body = await request.body()
        data = body.decode("utf-8")

        response_data = await transport.handle_request(data)

        return Response(
            content=response_data,
            media_type="application/json",
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
    transport, _ = get_http_handler()

    async def event_stream():
        """Generate SSE events from notifications."""
        try:
            async for notification in transport.notification_stream():
                # Format as SSE
                data = notification.model_dump_json()
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

    # Create WebSocket transport
    async def send_func(data: str) -> None:
        await websocket.send_text(data)

    transport = WebSocketAcpTransport(send_func)
    _ = AcpHandler(transport)  # Handler registers itself with transport

    await transport.start()

    try:
        while True:
            data = await websocket.receive_text()
            await transport.handle_message(data)

    except WebSocketDisconnect:
        logger.info("ACP WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"ACP WebSocket error: {e}")
    finally:
        await transport.stop()


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
    """
    from .transport import StdioAcpTransport

    transport = StdioAcpTransport()
    _ = AcpHandler(transport)  # Handler registers itself with transport

    logger.info("Starting ACP stdio transport")
    await transport.start()

    # Keep running until stdin closes
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        await transport.stop()
        logger.info("ACP stdio transport stopped")
