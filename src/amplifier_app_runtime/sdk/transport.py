"""Client-side transport abstraction for AmplifierClient.

Enables the SDK to work over stdio (subprocess), HTTP, or WebSocket
without changing client code. Also enables mock transports for testing.

Architecture:
- ClientTransport is the PROTOCOL (interface) for all client transports
- Implementations handle the wire format and connection management
- The AmplifierClient accepts any ClientTransport via constructor injection

Key difference from server-side Transport (in transport/base.py):
- Server Transport: bidirectional Event send/receive
- Client Transport: send Command, receive correlated Event stream
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..protocol.commands import Command
from ..protocol.events import Event

logger = logging.getLogger(__name__)


class TransportState(str, Enum):
    """Connection state machine."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


@dataclass
class ClientTransportConfig:
    """Configuration for client transports.

    This is the CLIENT-side config (for SDK). Different from TransportConfig
    in transport/base.py which is for server-side transports.
    """

    # Connection mode
    mode: str = "stdio"  # "stdio" | "http" | "websocket"

    # HTTP/WS settings (for attach mode)
    base_url: str = "http://localhost:4096"
    timeout: float = 30.0

    # Stdio settings (for subprocess mode)
    command: list[str] = field(default_factory=lambda: ["amplifier-runtime"])
    working_directory: str | None = None
    env: dict[str, str] | None = None

    # Reconnection
    auto_reconnect: bool = True
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 30.0
    reconnect_backoff: float = 2.0


@runtime_checkable
class ClientTransport(Protocol):
    """Protocol for SDK client transports.

    All transports must implement:
    - connect/disconnect: Lifecycle management
    - send_command: Send a command and receive correlated events
    - events: Subscribe to uncorrelated events (notifications, heartbeats)

    The transport handles:
    - Wire format (JSON lines, HTTP, WebSocket frames)
    - Connection management and reconnection
    - Command/event correlation
    """

    @property
    def state(self) -> TransportState:
        """Current connection state."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        ...

    async def connect(self) -> None:
        """Establish connection to the runtime.

        Raises:
            ConnectionError: If connection fails
        """
        ...

    async def disconnect(self) -> None:
        """Close the connection gracefully."""
        ...

    def send_command(self, command: Command) -> AsyncIterator[Event]:
        """Send a command and yield correlated response events.

        Yields events until a final event (result/error with final=True)
        is received for this command's correlation_id.

        Args:
            command: The command to send

        Yields:
            Events correlated to this command

        Raises:
            ConnectionError: If not connected
            TimeoutError: If no response within timeout
        """
        ...

    def events(self) -> AsyncIterator[Event]:
        """Subscribe to uncorrelated events (notifications, heartbeats).

        Used for events not correlated to a specific command,
        like approval requests or session state changes.

        Yields:
            Uncorrelated events from the server
        """
        ...


class BaseClientTransport(ABC):
    """Base class for client transports with common functionality.

    Provides:
    - State management
    - Event routing (correlated vs uncorrelated)
    - Background reader task management
    """

    def __init__(self, config: ClientTransportConfig):
        self.config = config
        self._state = TransportState.DISCONNECTED
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._pending_commands: dict[str, asyncio.Queue[Event]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> TransportState:
        """Current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._state == TransportState.CONNECTED

    async def connect(self) -> None:
        """Establish connection."""
        async with self._lock:
            if self._state == TransportState.CONNECTED:
                return

            self._state = TransportState.CONNECTING
            try:
                await self._do_connect()
                self._state = TransportState.CONNECTED

                # Start background reader
                self._reader_task = asyncio.create_task(self._read_loop())

                logger.info(f"{self.__class__.__name__} connected")
            except Exception as e:
                self._state = TransportState.DISCONNECTED
                raise ConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Close the connection."""
        async with self._lock:
            if self._state in (TransportState.DISCONNECTED, TransportState.CLOSED):
                return

            self._state = TransportState.CLOSED

            # Cancel reader task
            if self._reader_task:
                self._reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task
                self._reader_task = None

            # Drain pending commands with error
            for queue in self._pending_commands.values():
                await queue.put(
                    Event.error(None, "Transport disconnected", code="transport_closed")
                )
            self._pending_commands.clear()

            await self._do_disconnect()
            self._state = TransportState.DISCONNECTED
            logger.info(f"{self.__class__.__name__} disconnected")

    async def send_command(self, command: Command) -> AsyncIterator[Event]:
        """Send command and yield correlated events."""
        if not self.is_connected:
            raise ConnectionError("Transport not connected")

        # Register pending command
        response_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._pending_commands[command.id] = response_queue

        try:
            # Send command
            await self._do_send(command)

            # Yield correlated events until final
            while True:
                try:
                    event = await asyncio.wait_for(
                        response_queue.get(),
                        timeout=self.config.timeout,
                    )
                    yield event

                    if event.final:
                        break
                except TimeoutError:
                    yield Event.error(
                        command.id,
                        "Command timed out",
                        code="timeout",
                    )
                    break
        finally:
            self._pending_commands.pop(command.id, None)

    async def events(self) -> AsyncIterator[Event]:
        """Yield uncorrelated events."""
        while self.is_connected or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except TimeoutError:
                continue

    async def _read_loop(self) -> None:
        """Background task reading events and routing them."""
        try:
            async for event in self._receive_events():
                # Route to pending command or general queue
                if event.correlation_id and event.correlation_id in self._pending_commands:
                    await self._pending_commands[event.correlation_id].put(event)
                else:
                    await self._event_queue.put(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Read loop error: {e}")
            # Put error in all pending queues
            for queue in self._pending_commands.values():
                await queue.put(Event.error(None, f"Transport error: {e}", code="transport_error"))

    # Abstract methods for subclasses
    @abstractmethod
    async def _do_connect(self) -> None:
        """Implementation-specific connection logic."""
        ...

    @abstractmethod
    async def _do_disconnect(self) -> None:
        """Implementation-specific disconnection logic."""
        ...

    @abstractmethod
    async def _do_send(self, command: Command) -> None:
        """Implementation-specific send logic."""
        ...

    @abstractmethod
    def _receive_events(self) -> AsyncIterator[Event]:
        """Implementation-specific receive logic. Must be an async generator."""
        ...

    async def __aenter__(self) -> BaseClientTransport:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()


class StdioClientTransport(BaseClientTransport):
    """Transport over subprocess stdin/stdout.

    Launches `amplifier-runtime` as subprocess and communicates
    via newline-delimited JSON.

    This is the primary mode for TUI - it manages the runtime lifecycle.

    Wire format:
    - Commands: JSON object + newline to subprocess stdin
    - Events: JSON object + newline from subprocess stdout
    """

    def __init__(self, config: ClientTransportConfig | None = None):
        super().__init__(config or ClientTransportConfig(mode="stdio"))
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def _do_connect(self) -> None:
        """Launch subprocess and establish communication."""
        cmd = self.config.command

        # Build environment
        env = None
        if self.config.env:
            env = {**os.environ, **self.config.env}

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.working_directory,
            env=env,
        )

        # Start stderr reader (for logging)
        self._stderr_task = asyncio.create_task(self._read_stderr())

        logger.info(f"Launched subprocess: {' '.join(cmd)} (pid={self._process.pid})")

    async def _do_disconnect(self) -> None:
        """Terminate subprocess."""
        if self._stderr_task:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
            logger.info(f"Subprocess terminated (pid={self._process.pid})")
            self._process = None

    async def _do_send(self, command: Command) -> None:
        """Send command as JSON line to stdin."""
        if not self._process or not self._process.stdin:
            raise ConnectionError("Process not running")

        line = command.model_dump_json() + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

    async def _receive_events(self) -> AsyncIterator[Event]:
        """Read events from stdout."""
        if not self._process or not self._process.stdout:
            raise ConnectionError("Process not running")

        while True:
            line = await self._process.stdout.readline()
            if not line:
                # EOF - process exited
                break

            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            # Skip non-JSON lines (e.g., log messages that leaked to stdout)
            if not line_str.startswith("{"):
                logger.debug(f"Skipping non-JSON line: {line_str[:50]}")
                continue

            try:
                data = json.loads(line_str)
                yield Event.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                # Log but don't yield error events for parse failures
                # These often happen during shutdown when process is terminating
                logger.debug(f"Failed to parse event: {e} (line: {line_str[:50]})")

    async def _read_stderr(self) -> None:
        """Read and log stderr output."""
        if not self._process or not self._process.stderr:
            return

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                logger.debug(f"[runtime stderr] {line.decode('utf-8').strip()}")
        except asyncio.CancelledError:
            pass


class HTTPClientTransport(BaseClientTransport):
    """Transport over HTTP REST + SSE.

    Uses REST endpoints for commands:
    - GET/POST /session - List/create sessions
    - GET/DELETE /session/{id} - Get/delete session
    - POST /session/{id}/prompt - Send prompt (streaming SSE response)
    - POST /session/{id}/prompt/sync - Send prompt (wait for completion)
    - POST /session/{id}/cancel - Cancel execution
    - POST /session/{id}/approval - Respond to approval
    - GET /ping - Health check

    Used when attaching to an existing runtime server.
    """

    def __init__(self, config: ClientTransportConfig | None = None):
        super().__init__(config or ClientTransportConfig(mode="http"))
        self._http_client: Any | None = None  # httpx.AsyncClient

    async def _do_connect(self) -> None:
        """Connect to HTTP server."""
        import httpx

        client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.timeout, read=None),
        )

        # Verify server is reachable
        try:
            response = await client.get("/health")
            response.raise_for_status()
        except Exception as e:
            await client.aclose()
            raise ConnectionError(f"Server not reachable: {e}") from e

        self._http_client = client

    async def _do_disconnect(self) -> None:
        """Close HTTP connection."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _do_send(self, command: Command) -> None:
        """Send command via HTTP.

        For streaming commands (prompt.send), we DON'T queue results here.
        The caller should use send_command_streaming() instead.
        For non-streaming commands, we queue the result immediately.
        """
        if not self._http_client:
            raise ConnectionError("HTTP client not connected")

        # Map command to appropriate endpoint
        endpoint, method, is_streaming = self._map_command_to_endpoint(command)
        params = command.params.copy()

        # Remove session_id from params (it's in the URL)
        params.pop("session_id", None)

        if is_streaming:
            # For streaming commands, start SSE and queue events as they arrive
            await self._handle_streaming_command(command, endpoint, params)
        else:
            # For non-streaming commands, make request and queue result
            response = await self._http_client.request(
                method,
                endpoint,
                json=params if method == "POST" and params else None,
            )
            response.raise_for_status()
            data = response.json()
            if command.id in self._pending_commands:
                await self._pending_commands[command.id].put(Event.result(command.id, data))

    async def _handle_streaming_command(
        self, command: Command, endpoint: str, params: dict[str, Any]
    ) -> None:
        """Handle a streaming command by reading SSE events."""
        if not self._http_client:
            raise ConnectionError("HTTP client not connected")

        # Make streaming request
        async with self._http_client.stream(
            "POST",
            endpoint,
            json=params if params else None,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()

            # Read SSE events
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Strip "data: " prefix
                try:
                    data = json.loads(data_str)
                    event = Event.model_validate(data)
                    # Set correlation_id to command id
                    event_with_correlation = Event(
                        id=event.id,
                        type=event.type,
                        correlation_id=command.id,
                        data=event.data,
                        timestamp=event.timestamp,
                        sequence=event.sequence,
                        final=event.final,
                    )
                    if command.id in self._pending_commands:
                        await self._pending_commands[command.id].put(event_with_correlation)

                    if event.final:
                        return
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse SSE event: {e}")

    def _map_command_to_endpoint(self, command: Command) -> tuple[str, str, bool]:
        """Map command type to HTTP endpoint, method, and streaming flag."""
        session_id = command.params.get("session_id", "")

        # (endpoint, method, is_streaming)
        mapping: dict[str, tuple[str, str, bool]] = {
            "session.create": ("/session", "POST", False),
            "session.list": ("/session", "GET", False),
            "session.get": (f"/session/{session_id}", "GET", False),
            "session.delete": (f"/session/{session_id}", "DELETE", False),
            "prompt.send": (f"/session/{session_id}/prompt", "POST", True),
            "prompt.cancel": (f"/session/{session_id}/cancel", "POST", False),
            "approval.respond": (f"/session/{session_id}/approval", "POST", False),
            "ping": ("/ping", "GET", False),
            "capabilities": ("/capabilities", "GET", False),
        }
        return mapping.get(command.cmd, ("/", "GET", False))

    async def _receive_events(self) -> AsyncIterator[Event]:
        """HTTP transport doesn't have a persistent event stream.

        Events are received inline with command responses.
        This is a no-op generator for HTTP transport.
        """
        # HTTP transport receives events via command responses, not a persistent stream
        return
        yield  # Make this a generator


class WebSocketClientTransport(BaseClientTransport):
    """Transport over WebSocket for full-duplex communication.

    Connects to /ws/sessions/{session_id} for per-session bidirectional
    communication, or /ws for global event streaming.

    This is the preferred transport for interactive TUI when:
    - You need to send commands while receiving events
    - You need to cancel/abort mid-execution
    - You need to respond to approvals during execution

    Wire format:
    - Messages: JSON objects with {type, payload, request_id}
    - Types: prompt, abort, approval, ping (client->server)
    - Types: event, error, pong, connected (server->client)
    """

    def __init__(self, config: ClientTransportConfig | None = None):
        super().__init__(config or ClientTransportConfig(mode="websocket"))
        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._session_id: str | None = None

    async def _do_connect(self) -> None:
        """Connect to WebSocket server."""
        try:
            import websockets
        except ImportError as e:
            raise ImportError(
                "websockets package required. Install with: pip install websockets"
            ) from e

        # Convert HTTP URL to WebSocket URL
        ws_url = self.config.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws"

        self._ws = await websockets.connect(
            ws_url,
            ping_interval=30,
            ping_timeout=10,
        )

        # Wait for connected message
        data = await self._ws.recv()
        msg = json.loads(data)
        if msg.get("type") != "connected":
            raise ConnectionError(f"Unexpected message: {msg}")

        logger.info(
            f"WebSocket connected, protocol: {msg.get('payload', {}).get('protocol_version')}"
        )

    async def connect_session(self, session_id: str) -> None:
        """Connect to a specific session's WebSocket.

        Use this instead of connect() when you want per-session communication.
        """
        try:
            import websockets
        except ImportError as e:
            raise ImportError(
                "websockets package required. Install with: pip install websockets"
            ) from e

        async with self._lock:
            if self._state == TransportState.CONNECTED:
                return

            self._state = TransportState.CONNECTING
            self._session_id = session_id

            try:
                ws_url = self.config.base_url.replace("http://", "ws://").replace(
                    "https://", "wss://"
                )
                ws_url = f"{ws_url}/ws/sessions/{session_id}"

                self._ws = await websockets.connect(
                    ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                )

                # Wait for connected message
                data = await self._ws.recv()
                msg = json.loads(data)
                if msg.get("type") != "connected":
                    raise ConnectionError(f"Unexpected message: {msg}")

                self._state = TransportState.CONNECTED
                self._reader_task = asyncio.create_task(self._read_loop())
                logger.info(f"WebSocket connected to session {session_id}")

            except Exception as e:
                self._state = TransportState.DISCONNECTED
                raise ConnectionError(f"Failed to connect: {e}") from e

    async def _do_disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._session_id = None

    async def _do_send(self, command: Command) -> None:
        """Send command as WebSocket message."""
        if not self._ws:
            raise ConnectionError("WebSocket not connected")

        # Map command to WebSocket message type
        msg_type, payload = self._command_to_ws_message(command)

        message = {
            "type": msg_type,
            "payload": payload,
            "request_id": command.id,
        }

        await self._ws.send(json.dumps(message))

    def _command_to_ws_message(self, command: Command) -> tuple[str, dict[str, Any]]:
        """Convert Command to WebSocket message type and payload."""
        cmd = command.cmd
        params = command.params

        if cmd == "prompt.send":
            return "prompt", {"content": params.get("content", params.get("prompt", ""))}
        elif cmd == "prompt.cancel":
            return "abort", {}
        elif cmd == "approval.respond":
            return "approval", {
                "approval_id": params.get("approval_id"),
                "choice": params.get("choice"),
            }
        elif cmd == "ping":
            return "ping", {}
        else:
            # For other commands, send as generic command
            return "command", {"cmd": cmd, "params": params}

    async def _receive_events(self) -> AsyncIterator[Event]:
        """Receive events from WebSocket."""
        if not self._ws:
            raise ConnectionError("WebSocket not connected")

        try:
            async for data in self._ws:
                try:
                    msg = json.loads(data)
                    msg_type = msg.get("type")
                    payload = msg.get("payload", {})
                    request_id = msg.get("request_id")

                    if msg_type == "event":
                        # Convert to Event
                        event_type = payload.get("type", "unknown")
                        event_data = {k: v for k, v in payload.items() if k != "type"}

                        # Check if this is a final event
                        is_final = event_type in ("done", "cancelled", "error", "result")

                        yield Event(
                            type=event_type,
                            correlation_id=request_id,
                            data=event_data,
                            final=is_final,
                        )

                    elif msg_type == "error":
                        yield Event.error(
                            request_id,
                            payload.get("error", "Unknown error"),
                            code="ws_error",
                        )

                    elif msg_type == "pong":
                        # Handled internally, but could emit for monitoring
                        pass

                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Invalid WebSocket message: {e}")
                    yield Event.error(None, f"Parse error: {e}", code="parse_error")

        except Exception as e:
            logger.error(f"WebSocket receive error: {e}")

    # Convenience methods for interactive use

    async def send_prompt(self, content: str) -> AsyncIterator[Event]:
        """Send a prompt and yield response events.

        This is a convenience method for interactive TUI use.
        """
        command = Command.create("prompt.send", {"content": content})
        async for event in self.send_command(command):
            yield event

    async def send_abort(self) -> None:
        """Send abort to cancel current execution."""
        if not self._ws:
            raise ConnectionError("WebSocket not connected")

        message = {"type": "abort", "payload": {}}
        await self._ws.send(json.dumps(message))

    async def send_approval(self, approval_id: str, choice: str) -> None:
        """Send approval response."""
        if not self._ws:
            raise ConnectionError("WebSocket not connected")

        message = {
            "type": "approval",
            "payload": {"approval_id": approval_id, "choice": choice},
        }
        await self._ws.send(json.dumps(message))


class MockClientTransport(BaseClientTransport):
    """Mock transport for testing.

    Allows injecting predefined responses and recording commands.
    No actual I/O - everything is in-memory.

    Usage:
        transport = MockClientTransport()
        transport.set_response("session.create", [
            Event.result("cmd_1", {"session_id": "test_123"})
        ])

        client = AmplifierClient(transport=transport)
        session = await client.session.create()

        assert transport.recorded_commands[0].cmd == "session.create"
    """

    def __init__(self) -> None:
        super().__init__(ClientTransportConfig(mode="mock"))
        self._responses: dict[str, list[Event]] = {}
        self._recorded_commands: list[Command] = []
        self._mock_events: asyncio.Queue[Event] = asyncio.Queue()

    @property
    def recorded_commands(self) -> list[Command]:
        """Get all commands sent through this transport."""
        return self._recorded_commands.copy()

    def set_response(self, command_type: str, events: list[Event]) -> None:
        """Set canned response for a command type.

        Args:
            command_type: The command type (e.g., "session.create")
            events: List of events to return (last should have final=True)
        """
        self._responses[command_type] = events

    def inject_event(self, event: Event) -> None:
        """Inject an uncorrelated event (for testing event subscriptions)."""
        self._mock_events.put_nowait(event)

    def clear(self) -> None:
        """Clear recorded commands and responses."""
        self._recorded_commands.clear()
        self._responses.clear()
        while not self._mock_events.empty():
            self._mock_events.get_nowait()

    async def _do_connect(self) -> None:
        """No-op for mock."""
        pass

    async def _do_disconnect(self) -> None:
        """No-op for mock."""
        pass

    async def _do_send(self, command: Command) -> None:
        """Record command and queue canned response."""
        self._recorded_commands.append(command)

        # Get canned response or default
        events = self._responses.get(command.cmd, [Event.result(command.id, {"mock": True})])

        # Queue events with correct correlation_id
        for event in events:
            # Create a copy with the correct correlation_id
            event_copy = Event(
                id=event.id,
                type=event.type,
                correlation_id=command.id,
                data=event.data,
                timestamp=event.timestamp,
                sequence=event.sequence,
                final=event.final,
            )
            if command.id in self._pending_commands:
                await self._pending_commands[command.id].put(event_copy)

    async def _receive_events(self) -> AsyncIterator[Event]:
        """Yield injected events."""
        while True:
            try:
                event = await asyncio.wait_for(self._mock_events.get(), timeout=0.1)
                yield event
            except TimeoutError:
                if not self.is_connected:
                    break


# Factory functions


def create_stdio_transport(
    command: list[str] | None = None,
    working_directory: str | None = None,
    env: dict[str, str] | None = None,
) -> StdioClientTransport:
    """Create a stdio transport for subprocess communication.

    Args:
        command: Custom command (default: ["amplifier-runtime"])
        working_directory: CWD for subprocess
        env: Additional environment variables

    Returns:
        StdioClientTransport configured for subprocess communication
    """
    config = ClientTransportConfig(
        mode="stdio",
        command=command or ["amplifier-runtime"],
        working_directory=working_directory,
        env=env,
    )
    return StdioClientTransport(config)


def create_http_transport(
    base_url: str = "http://localhost:4096",
    timeout: float = 30.0,
) -> HTTPClientTransport:
    """Create an HTTP transport for server attachment.

    Args:
        base_url: Server URL
        timeout: Request timeout

    Returns:
        HTTPClientTransport configured for HTTP communication
    """
    config = ClientTransportConfig(
        mode="http",
        base_url=base_url,
        timeout=timeout,
    )
    return HTTPClientTransport(config)


def create_websocket_transport(
    base_url: str = "http://localhost:4096",
    timeout: float = 30.0,
) -> WebSocketClientTransport:
    """Create a WebSocket transport for bidirectional communication.

    Args:
        base_url: Server URL (http:// will be converted to ws://)
        timeout: Request timeout

    Returns:
        WebSocketClientTransport for full-duplex communication
    """
    config = ClientTransportConfig(
        mode="websocket",
        base_url=base_url,
        timeout=timeout,
    )
    return WebSocketClientTransport(config)


def create_mock_transport() -> MockClientTransport:
    """Create a mock transport for testing.

    Returns:
        MockClientTransport for testing
    """
    return MockClientTransport()
