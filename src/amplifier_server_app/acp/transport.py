"""ACP JSON-RPC transport layer.

Provides JSON-RPC 2.0 transport over multiple channels:
- stdio: For local agents running as subprocesses
- HTTP: For remote agents over REST
- WebSocket: For remote agents with bidirectional streaming
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from .types import (
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcNotification,
    JsonRpcResponse,
)

logger = logging.getLogger(__name__)

# Type aliases
RequestHandler = Callable[[str, dict[str, Any] | None], Coroutine[Any, Any, Any]]
NotificationHandler = Callable[[str, dict[str, Any] | None], Coroutine[Any, Any, None]]


class AcpTransport(ABC):
    """Abstract base class for ACP transports."""

    @abstractmethod
    async def start(self) -> None:
        """Start the transport."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport."""

    @abstractmethod
    async def send_response(self, response: JsonRpcResponse) -> None:
        """Send a JSON-RPC response."""

    @abstractmethod
    async def send_notification(self, notification: JsonRpcNotification) -> None:
        """Send a JSON-RPC notification."""

    @abstractmethod
    def on_request(self, handler: RequestHandler) -> None:
        """Register a request handler."""

    @abstractmethod
    def on_notification(self, handler: NotificationHandler) -> None:
        """Register a notification handler."""


class JsonRpcProcessor:
    """Processes JSON-RPC messages and routes to handlers."""

    def __init__(self) -> None:
        self._request_handler: RequestHandler | None = None
        self._notification_handler: NotificationHandler | None = None
        self._pending_requests: dict[str | int, asyncio.Future[Any]] = {}

    def set_request_handler(self, handler: RequestHandler) -> None:
        """Set the handler for incoming requests."""
        self._request_handler = handler

    def set_notification_handler(self, handler: NotificationHandler) -> None:
        """Set the handler for incoming notifications."""
        self._notification_handler = handler

    async def process_message(self, data: str) -> JsonRpcResponse | None:
        """Process an incoming JSON-RPC message.

        Returns a response for requests, None for notifications.
        """
        try:
            message = json.loads(data)
        except json.JSONDecodeError as e:
            return JsonRpcResponse(
                id=None,
                error=JsonRpcError(
                    code=JsonRpcErrorCode.PARSE_ERROR,
                    message=f"Parse error: {e}",
                ),
            )

        # Check if it's a response (has result or error, no method)
        if "result" in message or "error" in message:
            return await self._handle_response(message)

        # Check for method (request or notification)
        if "method" not in message:
            return JsonRpcResponse(
                id=message.get("id"),
                error=JsonRpcError(
                    code=JsonRpcErrorCode.INVALID_REQUEST,
                    message="Missing 'method' field",
                ),
            )

        method = message["method"]
        params = message.get("params")
        request_id = message.get("id")

        # Notification (no id)
        if request_id is None:
            if self._notification_handler:
                try:
                    await self._notification_handler(method, params)
                except Exception as e:
                    logger.exception(f"Error handling notification {method}: {e}")
            return None

        # Request (has id)
        if self._request_handler:
            try:
                result = await self._request_handler(method, params)
                return JsonRpcResponse(id=request_id, result=result)
            except JsonRpcProtocolError as e:
                return JsonRpcResponse(
                    id=request_id,
                    error=JsonRpcError(code=e.code, message=e.message, data=e.data),
                )
            except Exception as e:
                logger.exception(f"Error handling request {method}: {e}")
                return JsonRpcResponse(
                    id=request_id,
                    error=JsonRpcError(
                        code=JsonRpcErrorCode.INTERNAL_ERROR,
                        message=str(e),
                    ),
                )

        return JsonRpcResponse(
            id=request_id,
            error=JsonRpcError(
                code=JsonRpcErrorCode.METHOD_NOT_FOUND,
                message=f"No handler for method: {method}",
            ),
        )

    async def _handle_response(self, message: dict[str, Any]) -> None:
        """Handle an incoming response to a previous request."""
        request_id = message.get("id")
        if request_id is None:
            return

        future = self._pending_requests.pop(request_id, None)
        if future is None:
            logger.warning(f"Received response for unknown request: {request_id}")
            return

        if "error" in message:
            error = message["error"]
            future.set_exception(
                JsonRpcProtocolError(
                    code=error.get("code", JsonRpcErrorCode.INTERNAL_ERROR),
                    message=error.get("message", "Unknown error"),
                    data=error.get("data"),
                )
            )
        else:
            future.set_result(message.get("result"))

        return None

    def create_pending_request(self, request_id: str | int) -> asyncio.Future[Any]:
        """Create a future for tracking a pending request."""
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future
        return future


class JsonRpcProtocolError(Exception):
    """Exception for JSON-RPC protocol errors."""

    def __init__(
        self,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class StdioAcpTransport(AcpTransport):
    """ACP transport over stdio (stdin/stdout).

    Used for local agents running as subprocesses of the editor.
    Messages are newline-delimited JSON.
    """

    def __init__(self) -> None:
        self._processor = JsonRpcProcessor()
        self._running = False
        self._read_task: asyncio.Task[None] | None = None
        self._writer_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start reading from stdin."""
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        """Stop the transport."""
        self._running = False
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task

    async def _read_loop(self) -> None:
        """Read JSON-RPC messages from stdin."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_event_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self._running:
            try:
                line = await reader.readline()
                if not line:
                    break

                data = line.decode("utf-8").strip()
                if not data:
                    continue

                response = await self._processor.process_message(data)
                if response:
                    await self.send_response(response)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error reading from stdin: {e}")

    async def send_response(self, response: JsonRpcResponse) -> None:
        """Send a JSON-RPC response to stdout."""
        await self._write(response.model_dump_json() + "\n")

    async def send_notification(self, notification: JsonRpcNotification) -> None:
        """Send a JSON-RPC notification to stdout."""
        await self._write(notification.model_dump_json() + "\n")

    async def _write(self, data: str) -> None:
        """Write data to stdout with locking."""
        async with self._writer_lock:
            sys.stdout.write(data)
            sys.stdout.flush()

    def on_request(self, handler: RequestHandler) -> None:
        """Register a request handler."""
        self._processor.set_request_handler(handler)

    def on_notification(self, handler: NotificationHandler) -> None:
        """Register a notification handler."""
        self._processor.set_notification_handler(handler)


class HttpAcpTransport(AcpTransport):
    """ACP transport over HTTP.

    Used for remote agents. Each request is a separate HTTP POST.
    Notifications are sent via Server-Sent Events (SSE).
    """

    def __init__(self) -> None:
        self._processor = JsonRpcProcessor()
        self._notification_queues: list[asyncio.Queue[JsonRpcNotification | None]] = []
        self._queue_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the transport (no-op for HTTP, handled by web framework)."""
        pass

    async def stop(self) -> None:
        """Stop the transport."""
        async with self._queue_lock:
            for queue in self._notification_queues:
                await queue.put(None)  # Signal end
            self._notification_queues.clear()

    async def handle_request(self, data: str) -> str:
        """Handle an incoming HTTP request.

        Returns the JSON-RPC response as a string.
        """
        response = await self._processor.process_message(data)
        if response:
            return response.model_dump_json()
        return ""

    async def send_response(self, response: JsonRpcResponse) -> None:
        """Send response (handled via handle_request return value)."""
        # For HTTP, responses are returned from handle_request
        pass

    async def send_notification(self, notification: JsonRpcNotification) -> None:
        """Send a notification to all connected SSE clients."""
        async with self._queue_lock:
            for queue in self._notification_queues:
                await queue.put(notification)

    async def notification_stream(self) -> AsyncIterator[JsonRpcNotification]:
        """Create an SSE notification stream."""
        queue: asyncio.Queue[JsonRpcNotification | None] = asyncio.Queue()

        async with self._queue_lock:
            self._notification_queues.append(queue)

        try:
            while True:
                notification = await queue.get()
                if notification is None:
                    break
                yield notification
        finally:
            async with self._queue_lock:
                if queue in self._notification_queues:
                    self._notification_queues.remove(queue)

    def on_request(self, handler: RequestHandler) -> None:
        """Register a request handler."""
        self._processor.set_request_handler(handler)

    def on_notification(self, handler: NotificationHandler) -> None:
        """Register a notification handler."""
        self._processor.set_notification_handler(handler)


class WebSocketAcpTransport(AcpTransport):
    """ACP transport over WebSocket.

    Used for remote agents with bidirectional streaming.
    Full-duplex communication for real-time updates.
    """

    def __init__(self, send_func: Callable[[str], Coroutine[Any, Any, None]]) -> None:
        """Initialize with a send function provided by the WebSocket handler."""
        self._processor = JsonRpcProcessor()
        self._send_func = send_func
        self._running = False

    async def start(self) -> None:
        """Start the transport."""
        self._running = True

    async def stop(self) -> None:
        """Stop the transport."""
        self._running = False

    async def handle_message(self, data: str) -> None:
        """Handle an incoming WebSocket message."""
        response = await self._processor.process_message(data)
        if response:
            await self.send_response(response)

    async def send_response(self, response: JsonRpcResponse) -> None:
        """Send a JSON-RPC response via WebSocket."""
        if self._running:
            await self._send_func(response.model_dump_json())

    async def send_notification(self, notification: JsonRpcNotification) -> None:
        """Send a JSON-RPC notification via WebSocket."""
        if self._running:
            await self._send_func(notification.model_dump_json())

    def on_request(self, handler: RequestHandler) -> None:
        """Register a request handler."""
        self._processor.set_request_handler(handler)

    def on_notification(self, handler: NotificationHandler) -> None:
        """Register a notification handler."""
        self._processor.set_notification_handler(handler)


# =============================================================================
# Helper functions
# =============================================================================


def create_error_response(
    request_id: str | int | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> JsonRpcResponse:
    """Create a JSON-RPC error response."""
    return JsonRpcResponse(
        id=request_id,
        error=JsonRpcError(code=code, message=message, data=data),
    )


def create_notification(method: str, params: dict[str, Any] | None = None) -> JsonRpcNotification:
    """Create a JSON-RPC notification."""
    return JsonRpcNotification(method=method, params=params)
