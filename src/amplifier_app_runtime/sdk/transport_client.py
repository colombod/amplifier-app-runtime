"""Transport-aware SDK Client.

Uses the ClientTransport abstraction for transport-agnostic communication.
Works with stdio (subprocess), HTTP, WebSocket, or mock transports.

This is the recommended client for new integrations like TUI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..protocol.commands import Command
from ..protocol.events import Event
from .transport import (
    ClientTransport,
    MockClientTransport,
    create_http_transport,
    create_mock_transport,
    create_stdio_transport,
)
from .types import MessagePart, SessionInfo


@dataclass
class TransportSessionAPI:
    """Session operations via transport."""

    _client: TransportAmplifierClient

    async def list(self) -> list[SessionInfo]:
        """List all sessions."""
        command = Command.create("session.list")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                # Data contains "sessions" key with list of session dicts
                sessions = event.data.get("sessions", [])
                return [SessionInfo(**s) for s in sessions]
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return []

    async def create(
        self,
        bundle: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        working_directory: str | None = None,
    ) -> SessionInfo:
        """Create a new session.

        Args:
            bundle: Bundle to use for the session (e.g., "foundation", "amplifier-dev")
            provider: Default provider to use (e.g., "anthropic", "openai")
            model: Default model to use
            working_directory: Working directory for the session
        """
        params: dict[str, Any] = {}
        if bundle:
            params["bundle"] = bundle
        if provider:
            params["provider"] = provider
        if model:
            params["model"] = model
        if working_directory:
            params["working_directory"] = working_directory

        command = Command.create("session.create", params if params else None)
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return SessionInfo(**event.data)
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        raise RuntimeError("No response received")

    async def get(self, session_id: str) -> SessionInfo:
        """Get a session by ID."""
        command = Command.create("session.get", {"session_id": session_id})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return SessionInfo(**event.data)
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        raise RuntimeError("No response received")

    async def info(self, session_id: str) -> dict[str, Any]:
        """Get detailed session information.

        Returns more detail than get(), including message_count, tools, etc.
        """
        command = Command.create("session.info", {"session_id": session_id})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {}

    async def delete(self, session_id: str) -> bool:
        """Delete a session."""
        command = Command.create("session.delete", {"session_id": session_id})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("deleted", False)
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return False

    async def reset(
        self,
        session_id: str,
        bundle: str | None = None,
        preserve_history: bool = False,
    ) -> AsyncIterator[Event]:
        """Reset a session with optional new bundle.

        Streams progress events during reset:
        - session.reset.started
        - session.reset.completed

        Args:
            session_id: Session to reset
            bundle: Optional new bundle (keeps current if not provided)
            preserve_history: Whether to preserve conversation history
        """
        params: dict[str, Any] = {
            "session_id": session_id,
            "preserve_history": preserve_history,
        }
        if bundle:
            params["bundle"] = bundle

        command = Command.create("session.reset", params)
        async for event in self._client._transport.send_command(command):
            yield event

    async def prompt(
        self,
        session_id: str,
        content: str | list[MessagePart],
        agent: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[Event]:
        """Send a prompt and stream response events.

        Unlike the HTTP client which returns a single response,
        this yields all events during prompt processing (streaming).

        Args:
            session_id: Session to send prompt to
            content: Either a string or list of MessagePart objects.
                     If list, text parts are concatenated.
            agent: Optional agent to use
            model: Optional model to use
        """
        # Convert parts list to content string if needed
        if isinstance(content, list):
            # Extract text from parts
            text_parts = [p.text for p in content if p.type == "text" and p.text]
            content_str = "\n".join(text_parts) if text_parts else ""
        else:
            content_str = content

        params: dict[str, Any] = {
            "session_id": session_id,
            "content": content_str,
        }
        if agent:
            params["agent"] = agent
        if model:
            params["model"] = model

        command = Command.create("prompt.send", params)
        async for event in self._client._transport.send_command(command):
            yield event

    async def abort(self, session_id: str) -> bool:
        """Abort an active session."""
        command = Command.create("prompt.cancel", {"session_id": session_id})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("aborted", False)
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return False


@dataclass
class TransportEventAPI:
    """Event subscription via transport."""

    _client: TransportAmplifierClient

    async def subscribe(self) -> AsyncIterator[Event]:
        """Subscribe to uncorrelated events.

        Yields events not tied to a specific command:
        - approval.requested
        - session.idle
        - session.error
        - heartbeat
        """
        async for event in self._client._transport.events():
            yield event


@dataclass
class TransportBundleAPI:
    """Bundle management operations via transport."""

    _client: TransportAmplifierClient

    async def list(self) -> list[dict[str, Any]]:
        """List available bundles."""
        command = Command.create("bundle.list")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("bundles", [])
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return []

    async def install(
        self,
        source: str,
        name: str | None = None,
    ) -> AsyncIterator[Event]:
        """Install a bundle from source.

        Streams progress events during installation:
        - bundle.install.started
        - bundle.install.progress (multiple)
        - result (final)

        Args:
            source: Git URL or local path
            name: Optional name (derived from source if not provided)
        """
        params: dict[str, Any] = {"source": source}
        if name:
            params["name"] = name

        command = Command.create("bundle.install", params)
        async for event in self._client._transport.send_command(command):
            yield event

    async def add(self, path: str, name: str) -> dict[str, Any]:
        """Register a local bundle.

        Args:
            path: Path to local bundle directory
            name: Name to register the bundle as
        """
        command = Command.create("bundle.add", {"path": path, "name": name})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {}

    async def remove(self, name: str) -> bool:
        """Remove a bundle registration."""
        command = Command.create("bundle.remove", {"name": name})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("removed", False)
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return False

    async def info(self, name: str) -> dict[str, Any]:
        """Get information about a bundle."""
        command = Command.create("bundle.info", {"name": name})
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {}


@dataclass
class TransportConfigAPI:
    """Configuration operations via transport."""

    _client: TransportAmplifierClient

    async def init(
        self,
        bundle: str = "foundation",
        detect_providers: bool = True,
    ) -> AsyncIterator[Event]:
        """Initialize runtime configuration.

        Streams progress events during initialization:
        - config.init.started
        - config.init.provider_detected (multiple)
        - config.init.bundle_set
        - result (final)

        Args:
            bundle: Default bundle to use
            detect_providers: Whether to auto-detect providers from environment
        """
        command = Command.create(
            "config.init",
            {"bundle": bundle, "detect_providers": detect_providers},
        )
        async for event in self._client._transport.send_command(command):
            yield event

    async def get(self) -> dict[str, Any]:
        """Get current configuration."""
        command = Command.create("config.get")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {}

    async def list_providers(self) -> list[dict[str, Any]]:
        """List all known providers and their availability."""
        command = Command.create("provider.list")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("providers", [])
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return []

    async def detect_providers(self) -> dict[str, Any]:
        """Detect available providers from environment."""
        command = Command.create("provider.detect")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {}

    async def list_bundles(self) -> list[dict[str, Any]]:
        """List available bundles."""
        command = Command.create("bundle.list")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("bundles", [])
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return []


@dataclass
class TransportAgentsAPI:
    """Agent operations via transport."""

    _client: TransportAmplifierClient

    async def list(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """List available agents.

        Args:
            session_id: Optional session ID to filter by bundle

        Returns:
            List of agent info dicts with name, description, bundle
        """
        params: dict[str, Any] = {}
        if session_id:
            params["session_id"] = session_id

        command = Command.create("agents.list", params if params else None)
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("agents", [])
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return []

    async def info(self, name: str, session_id: str | None = None) -> dict[str, Any]:
        """Get detailed info about an agent.

        Args:
            name: Agent name
            session_id: Optional session ID for context

        Returns:
            Agent info dict with name, description, bundle, instructions
        """
        params: dict[str, Any] = {"name": name}
        if session_id:
            params["session_id"] = session_id

        command = Command.create("agents.info", params)
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        raise RuntimeError("No response received")


@dataclass
class TransportToolsAPI:
    """Tool management operations via transport."""

    _client: TransportAmplifierClient

    async def list(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """List available tools.

        Args:
            session_id: Optional session to get tools from

        Returns:
            List of tool info dicts with name, description, module
        """
        params = {"session_id": session_id} if session_id else {}
        command = Command.create("tools.list", params if params else None)
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("tools", [])
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return []

    async def info(self, name: str, session_id: str | None = None) -> dict[str, Any]:
        """Get tool information.

        Args:
            name: Tool name
            session_id: Optional session to get tool from

        Returns:
            Tool info dict with name, description, module, config
        """
        params: dict[str, Any] = {"name": name}
        if session_id:
            params["session_id"] = session_id
        command = Command.create("tools.info", params)
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {}


@dataclass
class TransportSlashCommandsAPI:
    """Slash commands metadata via transport (for autocomplete)."""

    _client: TransportAmplifierClient

    async def list(self) -> dict[str, Any]:
        """Get available slash commands for autocomplete.

        Returns:
            Dict with 'commands', 'mode_shortcuts', and 'count'
        """
        command = Command.create("slash_commands.list")
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return {"commands": [], "mode_shortcuts": [], "count": 0}


@dataclass
class TransportApprovalAPI:
    """Approval operations via transport."""

    _client: TransportAmplifierClient

    async def respond(
        self,
        session_id: str,
        approval_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> bool:
        """Respond to an approval request."""
        params: dict[str, Any] = {
            "session_id": session_id,
            "approval_id": approval_id,
            "approved": approved,
        }
        if feedback:
            params["feedback"] = feedback

        command = Command.create("approval.respond", params)
        async for event in self._client._transport.send_command(command):
            if event.type == "result" and event.data:
                return event.data.get("success", False)
            if event.type == "error":
                raise RuntimeError(event.data.get("error", "Unknown error"))
        return False


@dataclass
class TransportAmplifierClient:
    """Transport-aware SDK client.

    Works with any ClientTransport implementation:
    - StdioClientTransport: Launch runtime as subprocess
    - HTTPClientTransport: Connect to HTTP server
    - MockClientTransport: For testing

    Usage:
        # Subprocess mode (TUI)
        transport = create_stdio_transport()
        async with TransportAmplifierClient(transport) as client:
            sessions = await client.session.list()

        # HTTP attach mode
        transport = create_http_transport("http://localhost:4096")
        async with TransportAmplifierClient(transport) as client:
            async for event in client.session.prompt(session_id, parts):
                print(event)

        # Testing
        transport = create_mock_transport()
        transport.set_response("session.list", [...])
        client = TransportAmplifierClient(transport)
    """

    _transport: ClientTransport
    _owns_transport: bool = field(default=True)

    @property
    def transport(self) -> ClientTransport:
        """Access the underlying transport."""
        return self._transport

    @property
    def session(self) -> TransportSessionAPI:
        """Session operations."""
        return TransportSessionAPI(_client=self)

    @property
    def event(self) -> TransportEventAPI:
        """Event subscription operations."""
        return TransportEventAPI(_client=self)

    @property
    def approval(self) -> TransportApprovalAPI:
        """Approval operations."""
        return TransportApprovalAPI(_client=self)

    @property
    def config(self) -> TransportConfigAPI:
        """Configuration operations."""
        return TransportConfigAPI(_client=self)

    @property
    def bundle(self) -> TransportBundleAPI:
        """Bundle management operations."""
        return TransportBundleAPI(_client=self)

    @property
    def agents(self) -> TransportAgentsAPI:
        """Agent operations."""
        return TransportAgentsAPI(_client=self)

    @property
    def slash_commands(self) -> TransportSlashCommandsAPI:
        """Slash commands metadata (for autocomplete)."""
        return TransportSlashCommandsAPI(_client=self)

    @property
    def tools(self) -> TransportToolsAPI:
        """Tool management operations."""
        return TransportToolsAPI(_client=self)

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._transport.is_connected

    async def connect(self) -> None:
        """Connect the transport."""
        await self._transport.connect()

    async def disconnect(self) -> None:
        """Disconnect the transport."""
        if self._owns_transport:
            await self._transport.disconnect()

    async def __aenter__(self) -> TransportAmplifierClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()


# Factory functions


def create_subprocess_client(
    command: list[str] | None = None,
    working_directory: str | None = None,
    env: dict[str, str] | None = None,
) -> TransportAmplifierClient:
    """Create a client that launches runtime as subprocess.

    This is the primary mode for TUI - it manages the runtime lifecycle.

    Args:
        command: Custom command (default: ["amplifier-runtime"])
        working_directory: CWD for subprocess
        env: Additional environment variables

    Returns:
        TransportAmplifierClient with StdioClientTransport
    """
    transport = create_stdio_transport(
        command=command,
        working_directory=working_directory,
        env=env,
    )
    return TransportAmplifierClient(_transport=transport)


def create_attach_client(
    base_url: str = "http://localhost:4096",
    timeout: float = 30.0,
) -> TransportAmplifierClient:
    """Create a client that attaches to existing server.

    Used when the runtime is already running (e.g., started separately).

    Args:
        base_url: Server URL
        timeout: Request timeout

    Returns:
        TransportAmplifierClient with HTTPClientTransport
    """
    transport = create_http_transport(base_url=base_url, timeout=timeout)
    return TransportAmplifierClient(_transport=transport)


def create_test_client(
    transport: MockClientTransport | None = None,
) -> TransportAmplifierClient:
    """Create a client for testing.

    Args:
        transport: Pre-configured mock transport (creates new if None)

    Returns:
        TransportAmplifierClient with MockClientTransport
    """
    return TransportAmplifierClient(
        _transport=transport or create_mock_transport(),
        _owns_transport=transport is None,
    )
