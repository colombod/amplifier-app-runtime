"""Session management endpoints.

Provides CRUD operations for sessions and message handling.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..bus import Bus
from ..events import (
    SessionCreated,
    SessionCreatedProps,
    SessionDeleted,
    SessionDeletedProps,
    SessionUpdated,
    SessionUpdatedProps,
)

# =============================================================================
# Request/Response Models
# =============================================================================


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    title: str | None = None


class UpdateSessionRequest(BaseModel):
    """Request to update a session."""

    title: str | None = None


class SessionInfo(BaseModel):
    """Session information."""

    id: str
    title: str
    created_at: str
    updated_at: str


class PromptRequest(BaseModel):
    """Request to send a prompt."""

    parts: list[dict[str, Any]]
    agent: str | None = None
    model: str | None = None


# =============================================================================
# In-Memory Session Store (Phase 1)
# =============================================================================

# Simple in-memory store for Phase 1
# Will be replaced with proper storage integration
_sessions: dict[str, SessionInfo] = {}


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"ses_{uuid.uuid4().hex[:12]}"


# =============================================================================
# Route Handlers
# =============================================================================


async def list_sessions(request: Request) -> JSONResponse:
    """List all sessions."""
    sessions = list(_sessions.values())
    # Sort by updated_at descending
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return JSONResponse([s.model_dump() for s in sessions])


async def create_session(request: Request) -> JSONResponse:
    """Create a new session."""
    body = await request.json()
    req = CreateSessionRequest(**body) if body else CreateSessionRequest()

    session_id = _generate_session_id()
    now = datetime.utcnow().isoformat() + "Z"
    title = req.title or "New Session"

    session = SessionInfo(
        id=session_id,
        title=title,
        created_at=now,
        updated_at=now,
    )
    _sessions[session_id] = session

    # Publish event
    await Bus.publish(SessionCreated, SessionCreatedProps(session_id=session_id, title=title))

    return JSONResponse(session.model_dump(), status_code=201)


async def get_session(request: Request) -> JSONResponse:
    """Get a session by ID."""
    session_id = request.path_params["session_id"]
    session = _sessions.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse(session.model_dump())


async def update_session(request: Request) -> JSONResponse:
    """Update a session."""
    session_id = request.path_params["session_id"]
    session = _sessions.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    body = await request.json()
    req = UpdateSessionRequest(**body)

    # Update fields
    if req.title is not None:
        session.title = req.title
    session.updated_at = datetime.utcnow().isoformat() + "Z"

    _sessions[session_id] = session

    # Publish event
    await Bus.publish(SessionUpdated, SessionUpdatedProps(session_id=session_id, title=req.title))

    return JSONResponse(session.model_dump())


async def delete_session(request: Request) -> JSONResponse:
    """Delete a session."""
    session_id = request.path_params["session_id"]

    if session_id not in _sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    del _sessions[session_id]

    # Publish event
    await Bus.publish(SessionDeleted, SessionDeletedProps(session_id=session_id))

    return JSONResponse({"deleted": True})


async def send_prompt(request: Request) -> JSONResponse:
    """Send a prompt to a session.

    This is a placeholder - actual implementation will integrate
    with amplifier-core for session execution.
    """
    session_id = request.path_params["session_id"]
    session = _sessions.get(session_id)

    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    body = await request.json()
    prompt_req = PromptRequest(**body)

    # Update session timestamp
    session.updated_at = datetime.utcnow().isoformat() + "Z"
    _sessions[session_id] = session

    # Phase 1: Return acknowledgment (amplifier-core integration comes later)
    return JSONResponse(
        {
            "status": "accepted",
            "session_id": session_id,
            "parts_count": len(prompt_req.parts),
            "agent": prompt_req.agent,
            "model": prompt_req.model,
        }
    )


async def abort_session(request: Request) -> JSONResponse:
    """Abort an active session."""
    session_id = request.path_params["session_id"]

    if session_id not in _sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    # Phase 1: Acknowledge abort (actual cancellation logic comes later)
    return JSONResponse({"aborted": True, "session_id": session_id})


async def get_messages(request: Request) -> JSONResponse:
    """Get messages for a session."""
    session_id = request.path_params["session_id"]

    if session_id not in _sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    # Phase 1: Return empty list (message storage comes later)
    return JSONResponse({"session_id": session_id, "messages": []})


# =============================================================================
# Route Definitions
# =============================================================================


session_routes = [
    Route("/session", list_sessions, methods=["GET"]),
    Route("/session", create_session, methods=["POST"]),
    Route("/session/{session_id}", get_session, methods=["GET"]),
    Route("/session/{session_id}", update_session, methods=["PATCH"]),
    Route("/session/{session_id}", delete_session, methods=["DELETE"]),
    Route("/session/{session_id}/message", send_prompt, methods=["POST"]),
    Route("/session/{session_id}/message", get_messages, methods=["GET"]),
    Route("/session/{session_id}/abort", abort_session, methods=["POST"]),
]
