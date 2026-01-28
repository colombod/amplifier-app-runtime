"""ACP protocol handler.

Maps ACP methods to Amplifier session operations.
This is the core bridge between ACP protocol and Amplifier internals.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from .transport import AcpTransport, JsonRpcProtocolError, create_notification
from .types import (
    PROTOCOL_VERSION,
    AgentCapabilities,
    AgentInfo,
    CancelNotification,
    ContentBlock,
    InitializeRequest,
    InitializeResponse,
    JsonRpcErrorCode,
    LoadSessionRequest,
    LoadSessionResponse,
    McpCapabilities,
    NewSessionRequest,
    NewSessionResponse,
    PromptCapabilities,
    PromptRequest,
    PromptResponse,
    SessionMode,
    SessionModes,
    SessionUpdate,
    SessionUpdateType,
    SetSessionModeRequest,
    SetSessionModeResponse,
    StopReason,
)

logger = logging.getLogger(__name__)


class AcpHandler:
    """Handles ACP protocol methods and maps to Amplifier sessions.

    This handler implements the agent side of the ACP protocol:
    - initialize: Negotiate capabilities
    - session/new: Create a new session
    - session/load: Resume an existing session
    - session/prompt: Process user prompts
    - session/cancel: Cancel ongoing operations
    - session/set_mode: Change agent modes

    It also sends notifications back to the client:
    - session/update: Stream content, tool calls, and status updates
    """

    def __init__(self, transport: AcpTransport) -> None:
        self.transport = transport
        self._initialized = False
        self._client_capabilities: dict[str, Any] = {}
        self._sessions: dict[str, AcpSession] = {}

        # Register handlers
        transport.on_request(self._handle_request)
        transport.on_notification(self._handle_notification)

    async def _handle_request(self, method: str, params: dict[str, Any] | None) -> Any:
        """Route incoming requests to appropriate handlers."""
        params = params or {}

        # Methods that don't require initialization
        if method == "initialize":
            return await self._handle_initialize(params)

        # All other methods require initialization
        if not self._initialized:
            raise JsonRpcProtocolError(
                code=JsonRpcErrorCode.INVALID_REQUEST,
                message="Not initialized. Call 'initialize' first.",
            )

        # Route to method handlers
        handlers = {
            "session/new": self._handle_session_new,
            "session/load": self._handle_session_load,
            "session/prompt": self._handle_session_prompt,
            "session/set_mode": self._handle_session_set_mode,
        }

        handler = handlers.get(method)
        if handler:
            return await handler(params)

        raise JsonRpcProtocolError(
            code=JsonRpcErrorCode.METHOD_NOT_FOUND,
            message=f"Unknown method: {method}",
        )

    async def _handle_notification(self, method: str, params: dict[str, Any] | None) -> None:
        """Route incoming notifications to appropriate handlers."""
        params = params or {}

        if method == "session/cancel":
            await self._handle_session_cancel(params)
        else:
            logger.warning(f"Unknown notification: {method}")

    # =========================================================================
    # Method Handlers
    # =========================================================================

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        request = InitializeRequest(**params)

        # Store client capabilities
        self._client_capabilities = request.clientCapabilities.model_dump()

        # Build agent capabilities
        agent_capabilities = AgentCapabilities(
            loadSession=True,  # We support session loading
            mcpCapabilities=McpCapabilities(http=False, sse=True),
            promptCapabilities=PromptCapabilities(
                audio=False,
                embeddedContext=True,
                image=False,  # TODO: Add image support
            ),
        )

        # Build response
        response = InitializeResponse(
            protocolVersion=PROTOCOL_VERSION,
            agentInfo=AgentInfo(
                name="amplifier-server",
                version="0.1.0",
            ),
            agentCapabilities=agent_capabilities,
            authMethods=[],  # No auth required for now
        )

        self._initialized = True
        logger.info(f"ACP initialized with protocol version {request.protocolVersion}")

        return response.model_dump(exclude_none=True)

    async def _handle_session_new(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/new request."""
        request = NewSessionRequest(**params)

        # Generate session ID
        session_id = f"acp_{uuid.uuid4().hex[:12]}"

        # Create session wrapper
        session = AcpSession(
            session_id=session_id,
            cwd=request.cwd,
            handler=self,
        )
        self._sessions[session_id] = session

        # Initialize the underlying Amplifier session
        await session.initialize()

        # Build response
        response = NewSessionResponse(
            sessionId=session_id,
            modes=SessionModes(
                availableModes=[
                    SessionMode(id="default", name="Default", description="Default agent mode"),
                ],
                currentMode="default",
            ),
        )

        logger.info(f"Created ACP session: {session_id}")
        return response.model_dump(exclude_none=True)

    async def _handle_session_load(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/load request."""
        request = LoadSessionRequest(**params)

        # Check if session exists
        session = self._sessions.get(request.sessionId)
        if not session:
            # Try to load from Amplifier session manager
            from ..session import session_manager

            amplifier_session = await session_manager.get(request.sessionId)
            if not amplifier_session:
                raise JsonRpcProtocolError(
                    code=JsonRpcErrorCode.SESSION_NOT_FOUND,
                    message=f"Session not found: {request.sessionId}",
                )

            # Wrap in ACP session
            session = AcpSession(
                session_id=request.sessionId,
                cwd=request.cwd,
                handler=self,
            )
            session._amplifier_session = amplifier_session
            self._sessions[request.sessionId] = session

        # Build response
        response = LoadSessionResponse(
            modes=SessionModes(
                availableModes=[
                    SessionMode(id="default", name="Default", description="Default agent mode"),
                ],
                currentMode="default",
            ),
        )

        logger.info(f"Loaded ACP session: {request.sessionId}")
        return response.model_dump(exclude_none=True)

    async def _handle_session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/prompt request."""
        request = PromptRequest(**params)

        session = self._sessions.get(request.sessionId)
        if not session:
            raise JsonRpcProtocolError(
                code=JsonRpcErrorCode.SESSION_NOT_FOUND,
                message=f"Session not found: {request.sessionId}",
            )

        # Extract text content from prompt blocks
        text_content = self._extract_text_content(request.prompt)

        # Execute prompt and stream updates
        stop_reason = await session.execute_prompt(text_content)

        # Build response
        response = PromptResponse(stopReason=stop_reason)
        return response.model_dump(exclude_none=True)

    async def _handle_session_set_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/set_mode request."""
        request = SetSessionModeRequest(**params)

        session = self._sessions.get(request.sessionId)
        if not session:
            raise JsonRpcProtocolError(
                code=JsonRpcErrorCode.SESSION_NOT_FOUND,
                message=f"Session not found: {request.sessionId}",
            )

        # For now, just acknowledge the mode change
        session.current_mode = request.modeId

        response = SetSessionModeResponse()
        return response.model_dump(exclude_none=True)

    async def _handle_session_cancel(self, params: dict[str, Any]) -> None:
        """Handle session/cancel notification."""
        notification = CancelNotification(**params)

        session = self._sessions.get(notification.sessionId)
        if session:
            await session.cancel()
            logger.info(f"Cancelled session: {notification.sessionId}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _extract_text_content(self, blocks: list[ContentBlock]) -> str:  # noqa: N802
        """Extract text content from content blocks."""
        text_parts = []
        for block in blocks:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            elif hasattr(block, "type") and block.type == "text":
                text_parts.append(block.text)
        return "\n".join(text_parts)

    async def send_session_update(
        self,
        session_id: str,
        update_type: SessionUpdateType,
        data: dict[str, Any],
    ) -> None:
        """Send a session/update notification to the client."""
        update = SessionUpdate(
            sessionId=session_id,
            type=update_type,
            data=data,
        )
        notification = create_notification(
            "session/update",
            update.model_dump(exclude_none=True),
        )
        await self.transport.send_notification(notification)


class AcpSession:
    """Wrapper around an Amplifier session for ACP protocol handling."""

    def __init__(
        self,
        session_id: str,
        cwd: str,
        handler: AcpHandler,
    ) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self.handler = handler
        self.current_mode = "default"
        self._amplifier_session: Any = None
        self._cancel_event = asyncio.Event()
        self._execution_task: asyncio.Task[Any] | None = None

    async def initialize(self) -> None:
        """Initialize the underlying Amplifier session."""
        from ..session import SessionConfig, session_manager

        # Create Amplifier session
        config = SessionConfig(
            working_directory=self.cwd,
            # Add other config as needed
        )
        self._amplifier_session = await session_manager.create(config)

    async def execute_prompt(self, content: str) -> StopReason:
        """Execute a prompt and stream updates back via ACP."""
        self._cancel_event.clear()

        try:
            # Stream events from Amplifier session
            async for event in self._amplifier_session.execute(content):
                if self._cancel_event.is_set():
                    return StopReason.CANCELLED

                # Map Amplifier events to ACP session updates
                await self._send_event_as_update(event)

            return StopReason.END_TURN

        except asyncio.CancelledError:
            return StopReason.CANCELLED
        except Exception as e:
            logger.exception(f"Error executing prompt: {e}")
            # Send error as update
            await self.handler.send_session_update(
                self.session_id,
                SessionUpdateType.AGENT_MESSAGE_CHUNK,
                {"content": [{"type": "text", "text": f"Error: {e}"}]},
            )
            return StopReason.ERROR

    async def _send_event_as_update(self, event: Any) -> None:
        """Map an Amplifier event to an ACP session update."""
        event_type = getattr(event, "type", None) or event.get("type", "")

        # Map event types to ACP update types
        if event_type in ("content", "assistant_message", "text"):
            text = getattr(event, "text", None) or event.get("text", "")
            await self.handler.send_session_update(
                self.session_id,
                SessionUpdateType.AGENT_MESSAGE_CHUNK,
                {"content": [{"type": "text", "text": text}]},
            )

        elif event_type == "tool_call_start":
            await self.handler.send_session_update(
                self.session_id,
                SessionUpdateType.TOOL_CALL_START,
                {
                    "id": event.get("id", ""),
                    "name": event.get("name", ""),
                    "arguments": event.get("arguments", {}),
                },
            )

        elif event_type == "tool_call_end":
            await self.handler.send_session_update(
                self.session_id,
                SessionUpdateType.TOOL_CALL_END,
                {
                    "id": event.get("id", ""),
                    "result": event.get("result"),
                    "error": event.get("error"),
                },
            )

        elif event_type == "thinking":
            text = getattr(event, "text", None) or event.get("text", "")
            await self.handler.send_session_update(
                self.session_id,
                SessionUpdateType.THOUGHT_CHUNK,
                {"content": [{"type": "text", "text": text}]},
            )

    async def cancel(self) -> None:
        """Cancel ongoing execution."""
        self._cancel_event.set()
        if self._execution_task and not self._execution_task.done():
            self._execution_task.cancel()
