"""ACP Agent implementation using the official SDK pattern.

This module provides an ACP-compliant agent that wraps Amplifier sessions.
It uses the official ACP Python SDK's Agent interface for proper protocol handling.

Key pattern from SDK examples:
1. Agent stores connection via on_connect()
2. Agent uses conn.session_update() to stream updates
3. run_agent() handles transport setup for stdio
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from acp import (  # type: ignore[import-untyped]
    PROTOCOL_VERSION,
    Agent,
    Client,
    text_block,
    update_agent_message,
    update_agent_thought,
)
from acp.schema import (  # type: ignore[import-untyped]
    AgentCapabilities,
    AudioContentBlock,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    InitializeResponse,
    LoadSessionResponse,
    McpCapabilities,
    McpServerStdio,
    NewSessionResponse,
    PromptCapabilities,
    PromptResponse,
    ResourceContentBlock,
    SessionMode,
    SessionModeState,
    SetSessionModeResponse,
    SseMcpServer,
    TextContentBlock,
    ToolCallStart,
    ToolCallUpdate,
)

if TYPE_CHECKING:
    from ..session import ManagedSession

logger = logging.getLogger(__name__)

# Default bundle when none specified
DEFAULT_BUNDLE = "foundation"


class AmplifierAgent(Agent):
    """ACP Agent implementation backed by Amplifier sessions.

    This class implements the ACP Agent protocol using the official SDK pattern.
    It manages Amplifier sessions and streams events back to clients via
    the conn.session_update() method.

    Usage:
        # For stdio transport
        from acp import run_agent
        await run_agent(AmplifierAgent())

        # For HTTP/SSE, use with appropriate transport
    """

    def __init__(self) -> None:
        self._conn: Client | None = None
        self._sessions: dict[str, AmplifierAgentSession] = {}
        self._client_capabilities: ClientCapabilities | None = None

    def on_connect(self, conn: Client) -> None:
        """Store the connection for sending updates.

        This is called by the SDK when a client connects.
        The conn object is used to send session updates back to the client.
        """
        self._conn = conn
        logger.info("ACP client connected")

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        """Handle initialize request from client.

        This negotiates capabilities and prepares the agent for use.
        """
        self._client_capabilities = client_capabilities

        # Handle client_info as dict or object
        client_name = "unknown"
        if client_info:
            if isinstance(client_info, dict):
                client_name = client_info.get("name", "unknown")
            elif hasattr(client_info, "name"):
                client_name = client_info.name

        logger.info(f"ACP initialized: protocol_version={protocol_version}, client={client_name}")

        return InitializeResponse(
            protocolVersion=PROTOCOL_VERSION,
            agentInfo=Implementation(
                name="amplifier-server",
                version="0.1.0",
            ),
            agentCapabilities=AgentCapabilities(
                loadSession=True,
                mcpCapabilities=McpCapabilities(http=False, sse=True),
                promptCapabilities=PromptCapabilities(
                    audio=False,
                    embeddedContext=True,
                    image=False,
                ),
            ),
            authMethods=[],
        )

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio],
        **kwargs: Any,
    ) -> NewSessionResponse:
        """Create a new Amplifier session.

        This creates a real Amplifier session with a bundle and provider.
        The bundle defaults to 'foundation' if not specified.
        """
        # Generate session ID
        session_id = f"acp_{uuid.uuid4().hex[:12]}"

        # Extract bundle from kwargs (ACP extension via field_meta)
        bundle = kwargs.get("field_meta", {}).get("bundle") if kwargs.get("field_meta") else None
        bundle = bundle or DEFAULT_BUNDLE

        # Create session wrapper with client capabilities for ACP tools
        session = AmplifierAgentSession(
            session_id=session_id,
            cwd=cwd,
            bundle=bundle,
            conn=self._conn,
            client_capabilities=self._client_capabilities,
        )

        # Initialize the underlying Amplifier session
        await session.initialize()

        self._sessions[session_id] = session

        logger.info(f"Created ACP session: {session_id} with bundle '{bundle}'")

        return NewSessionResponse(
            sessionId=session_id,
            modes=SessionModeState(
                availableModes=[
                    SessionMode(id="default", name="Default", description="Default agent mode"),
                ],
                currentModeId="default",
            ),
        )

    async def load_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio],
        session_id: str,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        """Load an existing session."""
        # Check if we have it cached
        if session_id in self._sessions:
            logger.info(f"Loaded cached ACP session: {session_id}")
            return LoadSessionResponse(
                modes=SessionModeState(
                    availableModes=[
                        SessionMode(id="default", name="Default", description="Default agent mode"),
                    ],
                    currentModeId="default",
                ),
            )

        # Try to load from Amplifier session manager
        from ..session import session_manager

        amplifier_session = await session_manager.get(session_id)
        if not amplifier_session:
            logger.warning(f"Session not found: {session_id}")
            return None

        # Wrap in our session type with client capabilities
        session = AmplifierAgentSession(
            session_id=session_id,
            cwd=cwd,
            bundle=DEFAULT_BUNDLE,
            conn=self._conn,
            client_capabilities=self._client_capabilities,
        )
        session._amplifier_session = amplifier_session
        self._sessions[session_id] = session

        # Register ACP tools for loaded session
        await session._register_acp_tools()

        logger.info(f"Loaded ACP session: {session_id}")

        return LoadSessionResponse(
            modes=SessionModeState(
                availableModes=[
                    SessionMode(id="default", name="Default", description="Default agent mode"),
                ],
                currentModeId="default",
            ),
        )

    async def list_sessions(
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """List available sessions."""
        from acp.schema import ListSessionsResponse, SessionInfo  # type: ignore[import-untyped]

        sessions = []
        for sid, session in self._sessions.items():
            sessions.append(
                SessionInfo(
                    sessionId=sid,
                    cwd=session.cwd,
                )
            )

        return ListSessionsResponse(sessions=sessions)

    async def prompt(
        self,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        """Process a prompt and stream responses back.

        This is the main entry point for user prompts. It:
        1. Extracts text from the prompt blocks
        2. Executes via Amplifier
        3. Streams updates back via conn.session_update()
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            # Send error message if we have a connection
            if self._conn:
                await self._conn.session_update(
                    session_id,
                    update_agent_message(text_block(f"Error: Session not found: {session_id}")),
                )
            return PromptResponse(stopReason="error")

        # Extract text content
        text_content = self._extract_text_content(prompt)

        # Execute and stream
        stop_reason = await session.execute_prompt(text_content)

        return PromptResponse(stopReason=stop_reason)

    async def set_session_mode(
        self,
        mode_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> SetSessionModeResponse | None:
        """Change agent mode."""
        session = self._sessions.get(session_id)
        if session:
            session.current_mode = mode_id
            logger.info(f"Set mode to '{mode_id}' for session {session_id}")
        return SetSessionModeResponse()

    async def set_session_model(
        self,
        model_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> Any:
        """Change the model for a session."""
        logger.info(f"Model change requested: {model_id} for session {session_id}")
        # Model switching not yet implemented in Amplifier session
        from acp.schema import SetSessionModelResponse  # type: ignore[import-untyped]

        return SetSessionModelResponse()

    async def authenticate(
        self,
        method_id: str,
        **kwargs: Any,
    ) -> Any:
        """Handle authentication."""
        logger.info(f"Auth requested: {method_id}")
        from acp.schema import AuthenticateResponse  # type: ignore[import-untyped]

        return AuthenticateResponse()

    async def fork_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Fork an existing session."""
        from acp.schema import ForkSessionResponse  # type: ignore[import-untyped]

        # Create a new session based on the existing one
        new_session_id = f"acp_{uuid.uuid4().hex[:12]}"

        original = self._sessions.get(session_id)
        if not original:
            logger.error(f"Cannot fork: session not found: {session_id}")
            return ForkSessionResponse(sessionId=new_session_id)

        # Create new session with same bundle
        session = AmplifierAgentSession(
            session_id=new_session_id,
            cwd=cwd,
            bundle=original.bundle,
            conn=self._conn,
        )
        await session.initialize()
        self._sessions[new_session_id] = session

        logger.info(f"Forked session {session_id} -> {new_session_id}")
        return ForkSessionResponse(sessionId=new_session_id)

    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Resume a session."""
        from acp.schema import ResumeSessionResponse  # type: ignore[import-untyped]

        # Try to load the session
        result = await self.load_session(cwd, mcp_servers or [], session_id)
        if result:
            return ResumeSessionResponse()
        return None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Cancel ongoing execution."""
        session = self._sessions.get(session_id)
        if session:
            await session.cancel()
            logger.info(f"Cancelled session: {session_id}")

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle extension methods."""
        logger.info(f"Extension method: {method}")
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        """Handle extension notifications."""
        logger.info(f"Extension notification: {method}")

    def _extract_text_content(self, blocks: list[Any]) -> str:
        """Extract text content from content blocks."""
        text_parts = []
        for block in blocks:
            if isinstance(block, TextContentBlock):
                text_parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif hasattr(block, "type") and getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        return "\n".join(text_parts)


class AmplifierAgentSession:
    """Session wrapper that streams Amplifier events as ACP updates.

    This class bridges Amplifier's event system to ACP's session/update notifications.
    Events flow: Amplifier -> Hook -> _on_event() -> conn.session_update()

    ACP client-side tools (ide_terminal, ide_read_file, ide_write_file) are registered
    based on client capabilities during initialization.
    """

    def __init__(
        self,
        session_id: str,
        cwd: str,
        bundle: str,
        conn: Client | None,
        client_capabilities: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self.bundle = bundle
        self.current_mode = "default"
        self._conn = conn
        self._client_capabilities = client_capabilities
        self._amplifier_session: ManagedSession | None = None
        self._cancel_event = asyncio.Event()
        self._registered_acp_tools: list[str] = []

    async def initialize(self) -> None:
        """Initialize the underlying Amplifier session."""
        from ..bundle_manager import BundleManager
        from ..session import SessionConfig, session_manager
        from ..transport.base import Event

        # Load and prepare the bundle
        bundle_manager = BundleManager()
        try:
            prepared_bundle = await bundle_manager.load_and_prepare(
                bundle_name=self.bundle,
                working_directory=Path(self.cwd) if self.cwd else None,
            )
        except Exception as e:
            logger.error(f"Failed to load bundle '{self.bundle}': {e}")
            raise RuntimeError(
                f"Failed to load bundle '{self.bundle}'. "
                f"Ensure ANTHROPIC_API_KEY or OPENAI_API_KEY is set. Error: {e}"
            ) from e

        # Create event forwarder that uses the SDK's session_update
        async def on_amplifier_event(event: Event) -> None:
            """Forward Amplifier events to ACP via conn.session_update()."""
            await self._on_event(event)

        # Create Amplifier session
        config = SessionConfig(
            bundle=self.bundle,
            working_directory=self.cwd,
        )
        self._amplifier_session = await session_manager.create(
            config=config,
            auto_initialize=False,
            send_fn=on_amplifier_event,
        )

        # Initialize with prepared bundle
        await self._amplifier_session.initialize(prepared_bundle=prepared_bundle)
        logger.info(f"Amplifier session {self.session_id} initialized")

        # Register ACP client-side tools based on capabilities
        await self._register_acp_tools()

    async def _register_acp_tools(self) -> None:
        """Register ACP client-side tools on this session.

        Tools are registered based on client capabilities:
        - ide_terminal: requires client_capabilities.terminal
        - ide_read_file: requires client_capabilities.fs.readTextFile
        - ide_write_file: requires client_capabilities.fs.writeTextFile
        """
        if not self._amplifier_session:
            logger.warning("Cannot register ACP tools - session not initialized")
            return

        from .tools import register_acp_tools

        # Create closure for lazy client access
        def get_client() -> Client | None:
            return self._conn

        try:
            self._registered_acp_tools = await register_acp_tools(
                session=self._amplifier_session,
                get_client=get_client,
                session_id=self.session_id,
                client_capabilities=self._client_capabilities,
            )
            if self._registered_acp_tools:
                logger.info(
                    f"Registered ACP tools for session {self.session_id}: "
                    f"{self._registered_acp_tools}"
                )
            else:
                logger.debug(
                    f"No ACP tools registered for session {self.session_id} "
                    "(client may not support capabilities)"
                )
        except Exception as e:
            logger.warning(f"Failed to register ACP tools: {e}")

    async def execute_prompt(self, content: str) -> str:
        """Execute prompt and stream updates back via ACP.

        Returns stop reason: 'end_turn', 'cancelled', or 'error'.
        """
        self._cancel_event.clear()

        if not self._amplifier_session:
            logger.error("Session not initialized")
            return "error"

        try:
            # Execute and let the hook stream events
            async for event in self._amplifier_session.execute(content):
                if self._cancel_event.is_set():
                    return "cancelled"

                # The yield path events - forward them too
                await self._on_event(event)

            return "end_turn"

        except asyncio.CancelledError:
            return "cancelled"
        except Exception as e:
            logger.exception(f"Error executing prompt: {e}")
            # Send error as agent message
            if self._conn:
                await self._conn.session_update(
                    self.session_id,
                    update_agent_message(text_block(f"Error: {e}")),
                )
            return "error"

    async def _on_event(self, event: Any) -> None:
        """Map Amplifier event to ACP session update.

        This is called both from the streaming hook (during execution)
        and from the yield path (synthetic events).

        Uses the SDK's session_update() method which properly formats
        and sends the notification.
        """
        if not self._conn:
            return

        # Get event type and properties
        event_type = getattr(event, "type", None)
        if event_type is None and isinstance(event, dict):
            event_type = event.get("type", "")
        event_type = event_type or ""

        props = getattr(event, "properties", None)
        if props is None and isinstance(event, dict):
            props = event
        props = props or {}

        try:
            # Map event types to ACP updates
            if event_type == "content_block:delta":
                # Streaming text delta
                delta = props.get("delta", {})
                text = delta.get("text", "")
                if text:
                    await self._conn.session_update(
                        self.session_id,
                        update_agent_message(text_block(text)),
                    )

            elif event_type == "content_block:end":
                # Final content block - may contain the full text
                block = props.get("block", {})
                text = block.get("text", "")
                if text:
                    await self._conn.session_update(
                        self.session_id,
                        update_agent_message(text_block(text)),
                    )

            elif event_type in ("content", "assistant_message", "text"):
                # Direct text content
                text = props.get("text", "")
                if text:
                    await self._conn.session_update(
                        self.session_id,
                        update_agent_message(text_block(text)),
                    )

            elif event_type == "tool:pre":
                # Tool call starting
                tool_info = props.get("tool", {})
                tool_name = (
                    tool_info.get("name", "") if isinstance(tool_info, dict) else str(tool_info)
                )

                update = ToolCallStart(
                    sessionUpdate="tool_call",
                    id=props.get("call_id", ""),
                    name=tool_name,
                    input=props.get("arguments", {}),
                )
                await self._conn.session_update(self.session_id, update)

            elif event_type == "tool:post":
                # Tool call completed
                update = ToolCallUpdate(
                    sessionUpdate="tool_call_update",
                    id=props.get("call_id", ""),
                    status="completed",
                    output=props.get("result"),
                )
                await self._conn.session_update(self.session_id, update)

            elif event_type == "tool:error":
                # Tool call failed
                update = ToolCallUpdate(
                    sessionUpdate="tool_call_update",
                    id=props.get("call_id", ""),
                    status="error",
                    error=props.get("error"),
                )
                await self._conn.session_update(self.session_id, update)

            elif event_type in ("thinking:delta", "thinking:final", "thinking:start"):
                # Thinking/reasoning content
                text = props.get("text", "") or props.get("content", "")
                if text:
                    await self._conn.session_update(
                        self.session_id,
                        update_agent_thought(text_block(text)),
                    )

            elif event_type == "content_block:start":
                # Content block starting - check if it's thinking
                block = props.get("block", {})
                block_type = block.get("type", "")
                if block_type == "thinking":
                    # Thinking block starting - we'll get content in delta/end
                    pass
                # For text blocks, wait for delta/end to send content

            # Log unmapped events at debug level
            elif event_type and not event_type.startswith(
                ("session:", "execution:", "llm:", "provider:", "prompt:", "orchestrator:")
            ):
                logger.debug(f"Unmapped event type: {event_type}")

        except Exception as e:
            logger.warning(f"Error sending event {event_type}: {e}")

    async def cancel(self) -> None:
        """Cancel ongoing execution."""
        self._cancel_event.set()


# Entry point for stdio mode
async def run_stdio_agent() -> None:
    """Run the Amplifier agent over stdio using the official SDK.

    This is the simplest way to expose Amplifier via ACP - it handles
    all transport complexity automatically.

    Usage:
        python -m amplifier_server_app.acp.agent
    """
    from acp import run_agent  # type: ignore[import-untyped]

    agent = AmplifierAgent()
    logger.info("Starting Amplifier ACP agent (stdio mode)")
    await run_agent(agent)


if __name__ == "__main__":
    # Direct execution is deprecated. Use the package entry point instead:
    #   python -m amplifier_server_app.acp
    #
    # The package entry point properly configures logging to stderr BEFORE
    # importing any modules, which is required for stdio transport to work
    # correctly (stdout must be reserved for JSON-RPC messages only).
    import sys

    print(
        "WARNING: Direct execution of agent.py is deprecated.\n"
        "Use: python -m amplifier_server_app.acp\n"
        "This ensures proper stdio isolation for ACP protocol.",
        file=sys.stderr,
    )

    # Still run for backward compatibility, but logging may not be properly isolated
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(run_stdio_agent())
