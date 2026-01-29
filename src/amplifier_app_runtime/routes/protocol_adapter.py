"""HTTP Protocol Adapter.

Thin adapter layer that maps HTTP requests to protocol commands
and protocol events to HTTP responses.

This is the ONLY place where HTTP-specific logic lives.
All business logic is in the CommandHandler.

Encoding:
- All JSON uses UTF-8 encoding (no BOM)
- Content-Type headers include charset=utf-8
- SSE streams use UTF-8 with proper event format
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..protocol import Command, CommandHandler, CommandType, Event
from ..session import session_manager

if TYPE_CHECKING:
    pass

# Global handler instance
_handler: CommandHandler | None = None


def get_handler() -> CommandHandler:
    """Get or create the command handler."""
    global _handler
    if _handler is None:
        _handler = CommandHandler(session_manager)
    return _handler


# =============================================================================
# SSE Streaming Helper
# =============================================================================


async def events_to_sse(events: AsyncIterator[Event]) -> AsyncIterator[bytes]:
    """Convert protocol events to SSE format (UTF-8 encoded).

    SSE format: data: {json}\n\n
    All output is UTF-8 encoded bytes for cross-platform consistency.
    """
    async for event in events:
        data = event.model_dump_json()
        yield f"data: {data}\n\n".encode()


async def events_to_ndjson(events: AsyncIterator[Event]) -> AsyncIterator[bytes]:
    """Convert protocol events to newline-delimited JSON (UTF-8 encoded).

    NDJSON format: {json}\n
    All output is UTF-8 encoded bytes for cross-platform consistency.
    """
    async for event in events:
        yield (event.model_dump_json() + "\n").encode("utf-8")


# =============================================================================
# Request → Command Helpers
# =============================================================================


async def request_to_command(
    request: Request,
    cmd: str | CommandType,
    extra_params: dict | None = None,
) -> Command:
    """Convert HTTP request to protocol command.

    Args:
        request: Starlette request
        cmd: Command type
        extra_params: Additional params (e.g., from path)

    Returns:
        Protocol Command
    """
    # Parse body if present
    body = {}
    if await request.body():
        body = await request.json()

    # Merge body with extra params (path params override body)
    params = {**body, **(extra_params or {})}

    return Command.create(cmd, params)


# =============================================================================
# Response Helpers
# =============================================================================


async def single_response(command: Command) -> Response:
    """Execute command expecting single result event."""
    handler = get_handler()

    async for event in handler.handle(command):
        if event.is_error():
            return JSONResponse(
                {"error": event.data.get("error"), "code": event.data.get("code")},
                status_code=400 if event.data.get("code") == "SESSION_NOT_FOUND" else 500,
            )
        if event.final:
            return JSONResponse(event.data)

    # Should not reach here
    return JSONResponse({"error": "No response"}, status_code=500)


async def streaming_response(
    command: Command,
    format: str = "sse",
) -> Response:
    """Execute command with streaming response."""
    handler = get_handler()

    if format == "ndjson":
        return StreamingResponse(
            events_to_ndjson(handler.handle(command)),
            media_type="application/x-ndjson; charset=utf-8",
            headers={"X-Accel-Buffering": "no"},
        )
    else:
        return StreamingResponse(
            events_to_sse(handler.handle(command)),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


# =============================================================================
# Route Handlers - Thin adapters to protocol
# =============================================================================


async def create_session(request: Request) -> Response:
    """POST /session - Create a new session."""
    command = await request_to_command(request, CommandType.SESSION_CREATE)
    return await single_response(command)


async def list_sessions(request: Request) -> Response:
    """GET /session - List all sessions."""
    command = Command.create(CommandType.SESSION_LIST)
    return await single_response(command)


async def get_session(request: Request) -> Response:
    """GET /session/{session_id} - Get session details."""
    session_id = request.path_params["session_id"]
    command = Command.create(CommandType.SESSION_GET, {"session_id": session_id})
    return await single_response(command)


async def delete_session(request: Request) -> Response:
    """DELETE /session/{session_id} - Delete a session."""
    session_id = request.path_params["session_id"]
    command = Command.create(CommandType.SESSION_DELETE, {"session_id": session_id})
    return await single_response(command)


async def send_prompt(request: Request) -> Response:
    """POST /session/{session_id}/prompt - Send prompt (streaming)."""
    session_id = request.path_params["session_id"]
    command = await request_to_command(
        request,
        CommandType.PROMPT_SEND,
        {"session_id": session_id},
    )

    # Check Accept header for format preference
    accept = request.headers.get("accept", "text/event-stream")
    format = "ndjson" if "ndjson" in accept else "sse"

    return await streaming_response(command, format=format)


async def send_prompt_sync(request: Request) -> Response:
    """POST /session/{session_id}/prompt/sync - Send prompt (wait for completion)."""
    session_id = request.path_params["session_id"]
    command = await request_to_command(
        request,
        CommandType.PROMPT_SEND,
        {"session_id": session_id, "stream": False},
    )

    # Collect all events and return final result
    handler = get_handler()
    content_blocks: list[str] = []
    tool_calls: list[dict] = []
    final_data: dict = {}

    async for event in handler.handle(command):
        if event.is_error():
            return JSONResponse(
                {"error": event.data.get("error"), "code": event.data.get("code")},
                status_code=500,
            )
        if event.type == "content.end":
            content_blocks.append(event.data.get("content", ""))
        elif event.type == "tool.result":
            tool_calls.append(event.data)
        elif event.final:
            final_data = event.data

    return JSONResponse(
        {
            **final_data,
            "content": "".join(content_blocks),
            "tool_calls": tool_calls,
        }
    )


async def cancel_prompt(request: Request) -> Response:
    """POST /session/{session_id}/cancel - Cancel execution."""
    session_id = request.path_params["session_id"]
    command = Command.create(CommandType.PROMPT_CANCEL, {"session_id": session_id})
    return await single_response(command)


async def respond_approval(request: Request) -> Response:
    """POST /session/{session_id}/approval - Respond to approval."""
    session_id = request.path_params["session_id"]
    command = await request_to_command(
        request,
        CommandType.APPROVAL_RESPOND,
        {"session_id": session_id},
    )
    return await single_response(command)


async def ping(request: Request) -> Response:
    """GET /ping - Health check via protocol."""
    command = Command.create(CommandType.PING)
    return await single_response(command)


async def capabilities(request: Request) -> Response:
    """GET /capabilities - Get server capabilities."""
    command = Command.create(CommandType.CAPABILITIES)
    return await single_response(command)


# =============================================================================
# Route Definitions
# =============================================================================


protocol_routes = [
    # Session CRUD
    Route("/session", list_sessions, methods=["GET"]),
    Route("/session", create_session, methods=["POST"]),
    Route("/session/{session_id}", get_session, methods=["GET"]),
    Route("/session/{session_id}", delete_session, methods=["DELETE"]),
    # Execution
    Route("/session/{session_id}/prompt", send_prompt, methods=["POST"]),
    Route("/session/{session_id}/prompt/sync", send_prompt_sync, methods=["POST"]),
    Route("/session/{session_id}/cancel", cancel_prompt, methods=["POST"]),
    # Approval
    Route("/session/{session_id}/approval", respond_approval, methods=["POST"]),
    # Server
    Route("/ping", ping, methods=["GET"]),
    Route("/capabilities", capabilities, methods=["GET"]),
]
