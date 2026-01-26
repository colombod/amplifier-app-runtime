"""Session management endpoints.

Provides CRUD operations for sessions and streaming prompt execution.
Integrates with the session manager for full Amplifier lifecycle support.
"""

import asyncio
import json
from typing import Any

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from ..session import SessionConfig, session_manager

# =============================================================================
# Request/Response Models
# =============================================================================


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    title: str | None = None
    bundle: str | None = None
    provider: str | None = None
    model: str | None = None
    working_directory: str | None = None


class UpdateSessionRequest(BaseModel):
    """Request to update a session."""

    title: str | None = None


class PromptRequest(BaseModel):
    """Request to send a prompt."""

    content: str
    parts: list[dict[str, Any]] | None = None  # For multimodal (future)


class ApprovalRequest(BaseModel):
    """Request to respond to an approval."""

    request_id: str
    choice: str


# =============================================================================
# Route Handlers
# =============================================================================


async def list_sessions(request: Request) -> JSONResponse:
    """List all sessions."""
    sessions = await session_manager.list_sessions()
    # Sort by updated_at descending
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return JSONResponse(sessions)


async def create_session(request: Request) -> JSONResponse:
    """Create a new session."""
    body = await request.json() if await request.body() else {}
    req = CreateSessionRequest(**body)

    config = SessionConfig(
        bundle=req.bundle,
        provider=req.provider,
        model=req.model,
        working_directory=req.working_directory,
    )

    session = await session_manager.create(config=config)

    # Initialize the session (loads bundle, prepares amplifier-core)
    await session.initialize()

    return JSONResponse(session.to_dict(), status_code=201)


async def get_session(request: Request) -> JSONResponse:
    """Get a session by ID."""
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse(session.to_dict())


async def update_session(request: Request) -> JSONResponse:
    """Update a session."""
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    # Currently only metadata updates - expand as needed
    return JSONResponse(session.to_dict())


async def delete_session(request: Request) -> JSONResponse:
    """Delete a session."""
    session_id = request.path_params["session_id"]

    deleted = await session_manager.delete(session_id)

    if not deleted:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse({"deleted": True})


async def send_prompt(request: Request) -> StreamingResponse:
    """Send a prompt to a session and stream the response.

    Uses Server-Sent Events (SSE) format for streaming:
    - Each event is formatted as: data: {json}\n\n
    - Events include: content_start, content_delta, content_end, tool_call, etc.
    - Stream ends with: data: {"type": "done"}\n\n
    """
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    body = await request.json()
    prompt_req = PromptRequest(**body)

    async def event_stream():
        """Generate SSE event stream."""
        try:
            async for event in session.execute(prompt_req.content):
                # Format as SSE: data: {json}\n\n
                data = json.dumps({"type": event.type, **event.properties})
                yield f"data: {data}\n\n"

            # End marker
            yield 'data: {"type": "done"}\n\n'

        except asyncio.CancelledError:
            yield 'data: {"type": "cancelled"}\n\n'
        except Exception as e:
            error_data = json.dumps({"type": "error", "error": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def send_prompt_sync(request: Request) -> JSONResponse:
    """Send a prompt and wait for completion (non-streaming).

    For clients that don't support SSE.
    Returns the final response after execution completes.
    """
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    body = await request.json()
    prompt_req = PromptRequest(**body)

    # Collect all content
    content_blocks: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    try:
        async for event in session.execute(prompt_req.content):
            if event.type == "content_block:end":
                block = event.properties.get("block", {})
                text = block.get("text", "") if isinstance(block, dict) else str(block)
                content_blocks.append(text)
            elif event.type == "tool:post":
                tool_calls.append(event.properties)

        return JSONResponse(
            {
                "session_id": session_id,
                "content": "".join(content_blocks),
                "tool_calls": tool_calls,
                "state": session.metadata.state.value,
            }
        )

    except Exception as e:
        return JSONResponse(
            {
                "session_id": session_id,
                "error": str(e),
                "state": session.metadata.state.value,
            },
            status_code=500,
        )


async def abort_session(request: Request) -> JSONResponse:
    """Abort an active session."""
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    await session.cancel()

    return JSONResponse(
        {
            "aborted": True,
            "session_id": session_id,
            "state": session.metadata.state.value,
        }
    )


async def handle_approval(request: Request) -> JSONResponse:
    """Handle an approval response from the client."""
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    body = await request.json()
    approval_req = ApprovalRequest(**body)

    handled = await session.handle_approval(approval_req.request_id, approval_req.choice)

    if not handled:
        return JSONResponse(
            {"error": "Approval request not found or already handled"},
            status_code=404,
        )

    return JSONResponse(
        {
            "handled": True,
            "request_id": approval_req.request_id,
            "choice": approval_req.choice,
        }
    )


async def get_session_state(request: Request) -> JSONResponse:
    """Get the current state of a session."""
    session_id = request.path_params["session_id"]
    session = await session_manager.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse(
        {
            "session_id": session_id,
            "state": session.metadata.state.value,
            "turn_count": session.metadata.turn_count,
            "bundle": session.metadata.bundle_name,
            "pending_approvals": session.approval.pending_count,
            "active_spawns": session.spawn_manager.active_count,
        }
    )


async def cleanup_sessions(request: Request) -> JSONResponse:
    """Clean up old completed sessions (admin endpoint)."""
    max_age = request.query_params.get("max_age", "3600")
    try:
        max_age_seconds = float(max_age)
    except ValueError:
        return JSONResponse({"error": "Invalid max_age parameter"}, status_code=400)

    count = await session_manager.cleanup_completed(max_age_seconds)

    return JSONResponse(
        {
            "cleaned_up": count,
            "active_sessions": session_manager.active_count,
            "total_sessions": session_manager.total_count,
        }
    )


# =============================================================================
# Route Definitions
# =============================================================================


session_routes = [
    # Session CRUD
    Route("/session", list_sessions, methods=["GET"]),
    Route("/session", create_session, methods=["POST"]),
    Route("/session/cleanup", cleanup_sessions, methods=["POST"]),
    Route("/session/{session_id}", get_session, methods=["GET"]),
    Route("/session/{session_id}", update_session, methods=["PATCH"]),
    Route("/session/{session_id}", delete_session, methods=["DELETE"]),
    # Session execution
    Route("/session/{session_id}/prompt", send_prompt, methods=["POST"]),
    Route("/session/{session_id}/prompt/sync", send_prompt_sync, methods=["POST"]),
    Route("/session/{session_id}/abort", abort_session, methods=["POST"]),
    # Session state
    Route("/session/{session_id}/state", get_session_state, methods=["GET"]),
    Route("/session/{session_id}/approval", handle_approval, methods=["POST"]),
]
