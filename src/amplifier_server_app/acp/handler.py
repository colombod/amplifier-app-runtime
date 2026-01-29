"""ACP protocol handler.

Maps ACP methods to Amplifier session operations using the official SDK types.
This is the core bridge between ACP protocol and Amplifier internals.

See: https://agentclientprotocol.com/protocol/prompt-turn
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from acp import PROTOCOL_VERSION  # type: ignore[import-untyped]
from acp.schema import (  # type: ignore[import-untyped]  # type: ignore[import-untyped]
    AgentCapabilities,
    AgentMessageChunk,
    AgentThoughtChunk,
    CancelNotification,
    Implementation,
    InitializeRequest,
    InitializeResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    McpCapabilities,
    NewSessionRequest,
    NewSessionResponse,
    PromptCapabilities,
    PromptRequest,
    PromptResponse,
    SessionMode,
    SessionModeState,
    SessionNotification,
    SetSessionModeRequest,
    SetSessionModeResponse,
    TextContentBlock,
    ToolCallStart,
    ToolCallUpdate,
)

from .transport import AcpTransport, JsonRpcProtocolError, create_notification

if TYPE_CHECKING:
    from ..session import ManagedSession

logger = logging.getLogger(__name__)


# JSON-RPC error codes
class JsonRpcErrorCode:
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    AUTH_REQUIRED = -32000
    SESSION_NOT_FOUND = -32001


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
        if request.client_capabilities:
            self._client_capabilities = request.client_capabilities.model_dump()

        # Build agent capabilities
        agent_capabilities = AgentCapabilities(
            loadSession=True,
            mcpCapabilities=McpCapabilities(http=False, sse=True),
            promptCapabilities=PromptCapabilities(
                audio=False,
                embeddedContext=True,
                image=False,
            ),
        )

        # Build response using SDK types
        response = InitializeResponse(
            protocolVersion=PROTOCOL_VERSION,
            agentInfo=Implementation(
                name="amplifier-server",
                version="0.1.0",
            ),
            agentCapabilities=agent_capabilities,
            authMethods=[],
        )

        self._initialized = True
        logger.info(f"ACP initialized with protocol version {request.protocol_version}")

        return response.model_dump(exclude_none=True, by_alias=True)

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

        # Build response using SDK types
        response = NewSessionResponse(
            sessionId=session_id,
            modes=SessionModeState(
                availableModes=[
                    SessionMode(id="default", name="Default", description="Default agent mode"),
                ],
                currentModeId="default",
            ),
        )

        logger.info(f"Created ACP session: {session_id}")
        return response.model_dump(exclude_none=True, by_alias=True)

    async def _handle_session_load(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/load request."""
        request = LoadSessionRequest(**params)

        # Check if session exists
        session = self._sessions.get(request.session_id)
        if not session:
            # Try to load from Amplifier session manager
            from ..session import session_manager

            amplifier_session = await session_manager.get(request.session_id)
            if not amplifier_session:
                raise JsonRpcProtocolError(
                    code=JsonRpcErrorCode.SESSION_NOT_FOUND,
                    message=f"Session not found: {request.session_id}",
                )

            # Wrap in ACP session
            session = AcpSession(
                session_id=request.session_id,
                cwd=request.cwd,
                handler=self,
            )
            session._amplifier_session = amplifier_session
            self._sessions[request.session_id] = session

        # Build response
        response = LoadSessionResponse(
            modes=SessionModeState(
                availableModes=[
                    SessionMode(id="default", name="Default", description="Default agent mode"),
                ],
                currentModeId="default",
            ),
        )

        logger.info(f"Loaded ACP session: {request.session_id}")
        return response.model_dump(exclude_none=True, by_alias=True)

    async def _handle_session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/prompt request.

        Follows the ACP prompt turn lifecycle:
        https://agentclientprotocol.com/protocol/prompt-turn
        """
        request = PromptRequest(**params)

        session = self._sessions.get(request.session_id)
        if not session:
            raise JsonRpcProtocolError(
                code=JsonRpcErrorCode.SESSION_NOT_FOUND,
                message=f"Session not found: {request.session_id}",
            )

        # Extract text content from prompt blocks
        text_content = self._extract_text_content(request.prompt)

        # Execute prompt and stream updates
        stop_reason = await session.execute_prompt(text_content)

        # Build response
        response = PromptResponse(stopReason=stop_reason)
        return response.model_dump(exclude_none=True, by_alias=True)

    async def _handle_session_set_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle session/set_mode request."""
        request = SetSessionModeRequest(**params)

        session = self._sessions.get(request.session_id)
        if not session:
            raise JsonRpcProtocolError(
                code=JsonRpcErrorCode.SESSION_NOT_FOUND,
                message=f"Session not found: {request.session_id}",
            )

        # For now, just acknowledge the mode change
        session.current_mode = request.mode_id

        response = SetSessionModeResponse()
        return response.model_dump(exclude_none=True, by_alias=True)

    async def _handle_session_cancel(self, params: dict[str, Any]) -> None:
        """Handle session/cancel notification."""
        notification = CancelNotification(**params)

        session = self._sessions.get(notification.session_id)
        if session:
            await session.cancel()
            logger.info(f"Cancelled session: {notification.session_id}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _extract_text_content(self, blocks: list[Any]) -> str:
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
        update: AgentMessageChunk | AgentThoughtChunk | ToolCallStart | ToolCallUpdate,
    ) -> None:
        """Send a session/update notification to the client.

        Uses the ACP session/update format:
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "...",
                "update": { ... }
            }
        }
        """
        notification_params = SessionNotification(
            sessionId=session_id,
            update=update,
        )
        notification = create_notification(
            "session/update",
            notification_params.model_dump(exclude_none=True, by_alias=True),
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
        self._amplifier_session: ManagedSession | None = None
        self._cancel_event = asyncio.Event()
        self._execution_task: asyncio.Task[Any] | None = None

    async def initialize(self) -> None:
        """Initialize the underlying Amplifier session."""
        from ..session import SessionConfig, session_manager

        # Create Amplifier session
        config = SessionConfig(
            working_directory=self.cwd,
        )
        self._amplifier_session = await session_manager.create(config)

        # Initialize the session (loads providers, bundle, etc.)
        await self._amplifier_session.initialize()

    async def execute_prompt(self, content: str) -> str:
        """Execute a prompt and stream updates back via ACP.

        Returns the stop reason as a string matching ACP StopReason literals.
        """
        self._cancel_event.clear()

        if not self._amplifier_session:
            logger.error("Session not initialized")
            return "error"

        try:
            # Stream events from Amplifier session
            async for event in self._amplifier_session.execute(content):
                if self._cancel_event.is_set():
                    return "cancelled"

                # Map Amplifier events to ACP session updates
                await self._send_event_as_update(event)

            return "end_turn"

        except asyncio.CancelledError:
            return "cancelled"
        except Exception as e:
            logger.exception(f"Error executing prompt: {e}")
            # Send error as agent message
            error_update = AgentMessageChunk(
                sessionUpdate="agent_message_chunk",
                content=TextContentBlock(type="text", text=f"Error: {e}"),
            )
            await self.handler.send_session_update(self.session_id, error_update)
            return "error"

    async def _send_event_as_update(self, event: Any) -> None:
        """Map an Amplifier event to an ACP session update."""
        event_type = getattr(event, "type", None) or event.get("type", "")

        # Map event types to ACP update types
        if event_type in ("content", "assistant_message", "text", "content_block:delta"):
            # Extract text from various event formats
            text = ""
            if event_type == "content_block:delta":
                delta = event.properties.get("delta", {})
                text = delta.get("text", "")
            else:
                text = getattr(event, "text", None) or event.get("text", "")

            if text:
                update = AgentMessageChunk(
                    sessionUpdate="agent_message_chunk",
                    content=TextContentBlock(type="text", text=text),
                )
                await self.handler.send_session_update(self.session_id, update)

        elif event_type == "tool_call_start":
            update = ToolCallStart(
                sessionUpdate="tool_call",
                id=event.get("id", ""),
                name=event.get("name", ""),
                input=event.get("arguments", {}),
            )
            await self.handler.send_session_update(self.session_id, update)

        elif event_type == "tool_call_end":
            update = ToolCallUpdate(
                sessionUpdate="tool_call_update",
                id=event.get("id", ""),
                status="completed" if not event.get("error") else "error",
                output=event.get("result"),
                error=event.get("error"),
            )
            await self.handler.send_session_update(self.session_id, update)

        elif event_type == "thinking":
            text = getattr(event, "text", None) or event.get("text", "")
            if text:
                update = AgentThoughtChunk(
                    sessionUpdate="agent_thought_chunk",
                    content=TextContentBlock(type="text", text=text),
                )
                await self.handler.send_session_update(self.session_id, update)

    async def cancel(self) -> None:
        """Cancel ongoing execution."""
        self._cancel_event.set()
        if self._execution_task and not self._execution_task.done():
            self._execution_task.cancel()
