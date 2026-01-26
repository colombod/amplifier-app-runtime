"""Server-Sent Events (SSE) transport implementation.

The default transport for Phase 1. Works over HTTP/1.1 and HTTP/2.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

import httpx
from starlette.requests import Request
from starlette.responses import StreamingResponse

from .base import Event, EventStream, EventStreamFactory, TransportConfig

logger = logging.getLogger(__name__)


class SSEEventStream:
    """Client-side SSE event stream consumer.

    Handles:
    - Parsing SSE format (data: {...}\n\n)
    - Automatic reconnection on disconnect
    - Backoff for intermittent connectivity
    """

    def __init__(self, config: TransportConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._closed = False
        self._reconnect_delay = config.reconnect_delay

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure client is initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=httpx.Timeout(self.config.timeout, read=None),  # No read timeout for SSE
            )
        return self._client

    async def _connect(self) -> httpx.Response:
        """Establish SSE connection."""
        client = await self._ensure_client()
        response = await client.send(
            client.build_request("GET", "/event"),
            stream=True,
        )
        response.raise_for_status()
        return response

    async def __aiter__(self) -> AsyncIterator[Event]:
        """Iterate over events from the SSE stream."""
        while not self._closed:
            try:
                response = await self._connect()
                self._response = response
                self._reconnect_delay = self.config.reconnect_delay  # Reset on success

                async for line in response.aiter_lines():
                    if self._closed:
                        break

                    if line.startswith("data: "):
                        data = line[6:]  # Strip "data: " prefix
                        try:
                            payload = json.loads(data)
                            yield Event(
                                type=payload.get("type", "unknown"),
                                properties=payload.get("properties", {}),
                            )
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse SSE data: {data}")

            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                if self._closed:
                    break

                if self.config.reconnect:
                    logger.warning(
                        f"SSE connection lost: {e}. Reconnecting in {self._reconnect_delay}s..."
                    )
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * self.config.reconnect_backoff,
                        self.config.max_reconnect_delay,
                    )
                else:
                    raise

    async def close(self) -> None:
        """Close the event stream."""
        self._closed = True
        if self._response:
            await self._response.aclose()
        if self._client:
            await self._client.aclose()


class SSETransport(EventStreamFactory):
    """Factory for SSE event streams."""

    async def create_stream(self, config: TransportConfig) -> EventStream:
        """Create an SSE event stream."""
        return SSEEventStream(config)

    def supports_http3(self) -> bool:
        """SSE doesn't support HTTP/3 natively."""
        return False


# Server-side SSE utilities


async def sse_response(
    request: Request,
    event_iterator: AsyncIterator[Event],
    heartbeat_interval: float = 30.0,
) -> StreamingResponse:
    """Create an SSE streaming response.

    Args:
        request: The incoming request (for disconnect detection)
        event_iterator: Async iterator yielding events
        heartbeat_interval: Seconds between heartbeat pings
    """

    async def generate():
        # Send initial connected event
        yield f"data: {json.dumps({'type': 'server.connected', 'properties': {}})}\n\n"

        heartbeat_task = None
        event_queue: asyncio.Queue[Event | None] = asyncio.Queue()

        async def heartbeat():
            """Send periodic heartbeats to keep connection alive."""
            while True:
                await asyncio.sleep(heartbeat_interval)
                await event_queue.put(Event(type="server.heartbeat", properties={}))

        async def collect_events():
            """Collect events from the iterator into the queue."""
            try:
                async for event in event_iterator:
                    await event_queue.put(event)
            finally:
                await event_queue.put(None)  # Signal completion

        heartbeat_task = asyncio.create_task(heartbeat())
        collector_task = asyncio.create_task(collect_events())

        try:
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    if event is None:
                        break  # Iterator exhausted

                    payload = {"type": event.type, "properties": event.properties}
                    yield f"data: {json.dumps(payload)}\n\n"

                except TimeoutError:
                    continue  # Check disconnect and try again

        finally:
            heartbeat_task.cancel()
            collector_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
            with contextlib.suppress(asyncio.CancelledError):
                await collector_task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
