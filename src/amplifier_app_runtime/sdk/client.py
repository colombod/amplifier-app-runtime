"""SDK Client - Connects to Amplifier Server.

Supports both HTTP (remote) and embedded (in-process) modes.
The same client interface works regardless of connection mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ..transport.base import Event, TransportConfig
from ..transport.sse import SSEEventStream
from .types import MessagePart, SessionInfo


class FetchProtocol(Protocol):
    """Protocol for fetch-like function."""

    async def __call__(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response: ...


@dataclass
class SessionAPI:
    """Session operations."""

    _client: AmplifierClient

    async def list(self) -> list[SessionInfo]:
        """List all sessions."""
        response = await self._client._fetch("GET", "/session")
        data = response.json()
        return [SessionInfo(**s) for s in data]

    async def create(self, title: str | None = None) -> SessionInfo:
        """Create a new session."""
        body = {"title": title} if title else {}
        response = await self._client._fetch("POST", "/session", json=body)
        return SessionInfo(**response.json())

    async def get(self, session_id: str) -> SessionInfo:
        """Get a session by ID."""
        response = await self._client._fetch("GET", f"/session/{session_id}")
        return SessionInfo(**response.json())

    async def delete(self, session_id: str) -> bool:
        """Delete a session."""
        response = await self._client._fetch("DELETE", f"/session/{session_id}")
        return response.json().get("deleted", False)

    async def prompt(
        self,
        session_id: str,
        parts: list[MessagePart],
        agent: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a prompt to a session."""
        body: dict[str, Any] = {"parts": [p.model_dump() for p in parts]}
        if agent:
            body["agent"] = agent
        if model:
            body["model"] = model

        response = await self._client._fetch("POST", f"/session/{session_id}/message", json=body)
        return response.json()

    async def abort(self, session_id: str) -> bool:
        """Abort an active session."""
        response = await self._client._fetch("POST", f"/session/{session_id}/abort")
        return response.json().get("aborted", False)

    async def messages(self, session_id: str) -> list[dict[str, Any]]:
        """Get messages for a session."""
        response = await self._client._fetch("GET", f"/session/{session_id}/message")
        data = response.json()
        return data.get("messages", [])


@dataclass
class EventAPI:
    """Event subscription operations."""

    _client: AmplifierClient

    async def subscribe(self) -> AsyncIterator[Event]:
        """Subscribe to the SSE event stream.

        Usage:
            async for event in client.event.subscribe():
                if event.type == "session.idle":
                    break
        """
        config = TransportConfig(base_url=self._client.base_url)
        stream = SSEEventStream(config)

        async for event in stream:
            yield event


@dataclass
class AmplifierClient:
    """SDK client - works with both embedded and remote servers."""

    base_url: str
    _fetch_fn: FetchProtocol | None = None
    _http_client: httpx.AsyncClient | None = field(default=None, repr=False)

    @property
    def session(self) -> SessionAPI:
        """Session operations."""
        return SessionAPI(_client=self)

    @property
    def event(self) -> EventAPI:
        """Event subscription operations."""
        return EventAPI(_client=self)

    async def _fetch(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request."""
        if self._fetch_fn:
            return await self._fetch_fn(method, url, json)

        if self._http_client is None:
            self._http_client = httpx.AsyncClient(base_url=self.base_url)

        client = self._http_client
        response = await client.request(method, url, json=json)
        response.raise_for_status()
        return response

    async def close(self) -> None:
        """Close the client."""
        if self._http_client:
            await self._http_client.aclose()


def create_client(base_url: str = "http://localhost:4096") -> AmplifierClient:
    """Create an SDK client for remote server.

    Args:
        base_url: Server URL (default: http://localhost:4096)

    Returns:
        AmplifierClient configured for HTTP
    """
    return AmplifierClient(base_url=base_url)


def create_embedded_client() -> AmplifierClient:
    """Create an SDK client for embedded (in-process) mode.

    The embedded client calls the ASGI app directly without network I/O.
    This is the default mode when running `amplifier` without `--attach`.

    Returns:
        AmplifierClient configured for embedded mode
    """
    from starlette.testclient import TestClient

    from ..app import get_app

    app = get_app()
    test_client = TestClient(app, raise_server_exceptions=False)

    async def embedded_fetch(
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Fetch via embedded ASGI app."""
        response = test_client.request(method, url, json=json)
        # Convert to httpx.Response for consistency
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.content,
        )

    return AmplifierClient(
        base_url="http://amplifier.embedded",
        _fetch_fn=embedded_fetch,
    )
