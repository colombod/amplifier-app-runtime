"""WebSocket transport implementation.

Full-duplex bidirectional transport over WebSocket protocol.
Supports both HTTP/1.1 upgrade and HTTP/2 WebSocket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from .base import Event, Transport, TransportConfig

logger = logging.getLogger(__name__)


class WebSocketMessageType(str, Enum):
    """WebSocket message types for the protocol."""

    # Client -> Server
    PROMPT = "prompt"  # Send a prompt to execute
    ABORT = "abort"  # Abort current execution
    APPROVAL = "approval"  # Respond to approval request
    PING = "ping"  # Keep-alive ping

    # Server -> Client
    EVENT = "event"  # Session event (content, tool_call, etc.)
    ERROR = "error"  # Error message
    PONG = "pong"  # Keep-alive pong
    CONNECTED = "connected"  # Connection established


@dataclass
class WebSocketMessage:
    """WebSocket protocol message."""

    type: WebSocketMessageType
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None  # For request/response correlation

    def to_json(self) -> str:
        """Serialize to JSON."""
        data = {"type": self.type.value, "payload": self.payload}
        if self.request_id:
            data["request_id"] = self.request_id
        return json.dumps(data)

    @classmethod
    def from_json(cls, data: str) -> WebSocketMessage:
        """Deserialize from JSON."""
        parsed = json.loads(data)
        return cls(
            type=WebSocketMessageType(parsed["type"]),
            payload=parsed.get("payload", {}),
            request_id=parsed.get("request_id"),
        )


class WebSocketServerTransport(Transport):
    """Server-side WebSocket transport.

    Handles a single WebSocket connection for bidirectional communication.
    Used by the server to communicate with a connected client.
    """

    def __init__(self, websocket: WebSocket):
        self._websocket = websocket
        self._connected = False
        self._receive_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._send_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Check if the WebSocket is connected."""
        return self._connected and self._websocket.client_state == WebSocketState.CONNECTED

    async def connect(self) -> None:
        """Accept the WebSocket connection."""
        await self._websocket.accept()
        self._connected = True

        # Send connected message
        await self.send_message(
            WebSocketMessage(
                type=WebSocketMessageType.CONNECTED,
                payload={"protocol_version": "1.0"},
            )
        )

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        if self._websocket.client_state == WebSocketState.CONNECTED:
            await self._websocket.close()

    async def send(self, event: Event) -> None:
        """Send an event to the client."""
        await self.send_message(
            WebSocketMessage(
                type=WebSocketMessageType.EVENT,
                payload={"type": event.type, "properties": event.properties},
            )
        )

    async def send_message(self, message: WebSocketMessage) -> None:
        """Send a WebSocket message."""
        async with self._send_lock:
            if self.is_connected:
                await self._websocket.send_text(message.to_json())

    async def send_error(self, error: str, request_id: str | None = None) -> None:
        """Send an error message."""
        await self.send_message(
            WebSocketMessage(
                type=WebSocketMessageType.ERROR,
                payload={"error": error},
                request_id=request_id,
            )
        )

    def receive(self) -> AsyncIterator[Event]:
        """Receive events (not used for server-side, use receive_messages instead)."""
        raise NotImplementedError("Use receive_messages() for server-side transport")

    async def receive_messages(self) -> AsyncIterator[WebSocketMessage]:
        """Receive messages from the client."""
        try:
            while self.is_connected:
                data = await self._websocket.receive_text()
                try:
                    message = WebSocketMessage.from_json(data)

                    # Handle ping/pong internally
                    if message.type == WebSocketMessageType.PING:
                        await self.send_message(
                            WebSocketMessage(
                                type=WebSocketMessageType.PONG,
                                request_id=message.request_id,
                            )
                        )
                        continue

                    yield message
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Invalid WebSocket message: {e}")
                    await self.send_error(f"Invalid message format: {e}")

        except WebSocketDisconnect:
            self._connected = False
        except Exception as e:
            logger.exception(f"WebSocket receive error: {e}")
            self._connected = False


class WebSocketClientTransport(Transport):
    """Client-side WebSocket transport.

    Connects to a WebSocket server for bidirectional communication.
    """

    def __init__(self, config: TransportConfig):
        self.config = config
        self._websocket: Any = None  # websockets.WebSocketClientProtocol
        self._connected = False
        self._receive_task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()

    async def connect(self) -> None:
        """Connect to the WebSocket server."""
        try:
            import websockets

            # Convert HTTP URL to WebSocket URL
            ws_url = self.config.base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws_url = f"{ws_url}/ws"

            self._websocket = await websockets.connect(
                ws_url,
                ping_interval=30,
                ping_timeout=10,
            )
            self._connected = True

            # Wait for connected message
            data = await self._websocket.recv()
            message = WebSocketMessage.from_json(data)
            if message.type != WebSocketMessageType.CONNECTED:
                raise ConnectionError(f"Unexpected message: {message.type}")

            # Start receive task
            self._receive_task = asyncio.create_task(self._receive_loop())

        except ImportError as e:
            raise ImportError(
                "websockets package required for WebSocket client. "
                "Install with: pip install websockets"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket server."""
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task

        if self._websocket:
            await self._websocket.close()

    async def send(self, event: Event) -> None:
        """Send an event to the server."""
        if not self._connected or not self._websocket:
            raise ConnectionError("Not connected")

        message = WebSocketMessage(
            type=WebSocketMessageType.EVENT,
            payload={"type": event.type, "properties": event.properties},
        )
        await self._websocket.send(message.to_json())

    async def send_prompt(self, content: str, request_id: str | None = None) -> None:
        """Send a prompt to the server."""
        if not self._connected or not self._websocket:
            raise ConnectionError("Not connected")

        message = WebSocketMessage(
            type=WebSocketMessageType.PROMPT,
            payload={"content": content},
            request_id=request_id,
        )
        await self._websocket.send(message.to_json())

    async def send_abort(self, request_id: str | None = None) -> None:
        """Send abort request to the server."""
        if not self._connected or not self._websocket:
            raise ConnectionError("Not connected")

        message = WebSocketMessage(
            type=WebSocketMessageType.ABORT,
            request_id=request_id,
        )
        await self._websocket.send(message.to_json())

    async def send_approval(
        self, approval_id: str, choice: str, request_id: str | None = None
    ) -> None:
        """Send approval response to the server."""
        if not self._connected or not self._websocket:
            raise ConnectionError("Not connected")

        message = WebSocketMessage(
            type=WebSocketMessageType.APPROVAL,
            payload={"approval_id": approval_id, "choice": choice},
            request_id=request_id,
        )
        await self._websocket.send(message.to_json())

    def receive(self) -> AsyncIterator[Event]:
        """Receive events from the server."""
        return self._event_generator()

    async def _event_generator(self) -> AsyncIterator[Event]:
        """Generate events from the queue."""
        while self._connected:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except TimeoutError:
                continue

    async def _receive_loop(self) -> None:
        """Background task to receive messages and queue events."""
        try:
            async for data in self._websocket:
                if not self._connected:
                    break

                try:
                    message = WebSocketMessage.from_json(data)

                    if message.type == WebSocketMessageType.EVENT:
                        event = Event(
                            type=message.payload.get("type", "unknown"),
                            properties=message.payload.get("properties", {}),
                        )
                        await self._event_queue.put(event)

                    elif message.type == WebSocketMessageType.ERROR:
                        logger.error(f"Server error: {message.payload.get('error')}")

                    elif message.type == WebSocketMessageType.PONG:
                        pass  # Handled internally

                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Invalid message from server: {e}")

        except Exception as e:
            logger.exception(f"WebSocket receive loop error: {e}")
        finally:
            self._connected = False
