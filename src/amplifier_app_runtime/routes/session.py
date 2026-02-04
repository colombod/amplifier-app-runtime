"""Session management endpoints.

Provides CRUD operations for sessions and streaming prompt execution.
Integrates with the session manager for full Amplifier lifecycle support.
"""

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from ..session import SessionConfig, session_manager

logger = logging.getLogger(__name__)

# =============================================================================
# Request/Response Models
# =============================================================================


class CreateSessionRequest(BaseModel):
    """Request to create a new session.

    Supports two ways to specify a bundle:
    - bundle: str - Reference a pre-existing bundle by name (e.g., "foundation")
    - bundle_definition: dict - Define a bundle at runtime with full configuration

    Example bundle_definition:
        {
            "name": "my-agent",
            "providers": [{"module": "provider-anthropic"}],
            "tools": [{"module": "tool-filesystem"}],
            "instructions": "You are a helpful assistant."
        }
    """

    title: str | None = None
    bundle: str | None = None
    bundle_definition: dict[str, Any] | None = None  # Runtime bundle definition
    provider: str | None = None
    model: str | None = None
    working_directory: str | None = None
    behaviors: list[str] | None = None


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
    """Create a new session.

    Supports two modes:
    1. Named bundle: {"bundle": "foundation"}
    2. Runtime bundle: {"bundle_definition": {"name": "...", "tools": [...]}}
    """
    body = await request.json() if await request.body() else {}
    req = CreateSessionRequest(**body)

    prepared_bundle = None
    client_tools_to_register: list[dict[str, Any]] = []

    # Handle runtime bundle definition
    if req.bundle_definition:
        try:
            from amplifier_foundation import Bundle

            # Create Bundle from definition
            defn = req.bundle_definition
            bundle = Bundle(
                name=defn.get("name", "runtime-bundle"),
                version=defn.get("version", "1.0.0"),
                description=defn.get("description", ""),
                providers=defn.get("providers", []),
                tools=defn.get("tools", []),
                hooks=defn.get("hooks", []),
                agents=defn.get("agents", {}),
                instruction=defn.get("instructions") or defn.get("instruction"),
                session=defn.get("session", {}),
                includes=defn.get("includes", []),
            )

            # Store client tools for later registration (after session init)
            client_tools_to_register = defn.get("clientTools", [])
            logger.info(
                f"DEBUG: Extracted {len(client_tools_to_register)} client tools from bundle"
            )

            # Auto-detect and inject provider if not specified
            from ..bundle_manager import BundleManager

            manager = BundleManager()
            await manager.initialize()

            # Check if providers were specified in definition
            if not req.bundle_definition.get("providers"):
                provider_bundle = await manager._auto_detect_provider()
                if provider_bundle:
                    bundle = bundle.compose(provider_bundle)

            # Prepare the bundle
            prepared_bundle = await bundle.prepare()

        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to create runtime bundle: {e}", "code": "BUNDLE_ERROR"},
                status_code=400,
            )

    config = SessionConfig(
        bundle=req.bundle if not prepared_bundle else None,
        provider=req.provider,
        model=req.model,
        working_directory=req.working_directory,
        behaviors=req.behaviors or [],
    )

    session = await session_manager.create(config=config)

    # Initialize the session (loads bundle, prepares amplifier-core)
    await session.initialize(prepared_bundle=prepared_bundle)

    # Register client-side tools if any were provided in bundle_definition
    logger.info(
        f"DEBUG: About to check client tools registration. bundle_def={bool(req.bundle_definition)}, tools={len(client_tools_to_register)}"
    )

    if req.bundle_definition and client_tools_to_register:
        logger.info("DEBUG: Client tools registration condition passed")
        from ..client_tools import register_client_tools

        # Use _amplifier_session which is the actual AmplifierSession instance
        logger.info(
            f"DEBUG: Session has _amplifier_session: {hasattr(session, '_amplifier_session')}"
        )
        if session._amplifier_session:
            logger.info(
                f"DEBUG: Calling register_client_tools with {len(client_tools_to_register)} tools"
            )
            registered = await register_client_tools(
                session._amplifier_session, client_tools_to_register
            )
            logger.info(f"✅ Registered {len(registered)} client-side tools: {registered}")
        else:
            logger.warning("Session._amplifier_session not available")
    else:
        logger.info(
            f"DEBUG: Skipping client tools (bundle_def={bool(req.bundle_definition)}, tools_count={len(client_tools_to_register)})"
        )

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
