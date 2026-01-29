"""WebSocket endpoint for full-duplex session communication.

Provides bidirectional communication between clients and sessions,
supporting real-time prompts, streaming responses, and approvals.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..session import session_manager
from ..transport.websocket import (
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketServerTransport,
)

logger = logging.getLogger(__name__)


class WebSocketSessionHandler:
    """Handles WebSocket connections for a session.

    Manages the full-duplex communication lifecycle:
    - Accepts connection and associates with session
    - Routes incoming messages (prompts, approvals, aborts)
    - Streams session events back to client
    - Handles disconnection and cleanup
    """

    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.transport = WebSocketServerTransport(websocket)
        self._execution_task: asyncio.Task | None = None
        self._running = False

    async def handle(self) -> None:
        """Main handler for the WebSocket connection."""
        # Get or validate session
        session = await session_manager.get(self.session_id)
        if not session:
            await self.websocket.close(code=4004, reason="Session not found")
            return

        try:
            await self.transport.connect()
            self._running = True

            # Process incoming messages
            async for message in self.transport.receive_messages():
                if not self._running:
                    break

                await self._handle_message(session, message)

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for session {self.session_id}")
        except Exception as e:
            logger.exception(f"WebSocket error for session {self.session_id}: {e}")
        finally:
            self._running = False
            await self._cleanup()

    async def _handle_message(self, session: Any, message: WebSocketMessage) -> None:
        """Route incoming message to appropriate handler."""
        try:
            if message.type == WebSocketMessageType.PROMPT:
                await self._handle_prompt(session, message)

            elif message.type == WebSocketMessageType.ABORT:
                await self._handle_abort(session, message)

            elif message.type == WebSocketMessageType.APPROVAL:
                await self._handle_approval(session, message)

            else:
                await self.transport.send_error(
                    f"Unknown message type: {message.type}",
                    request_id=message.request_id,
                )

        except Exception as e:
            logger.exception(f"Error handling message {message.type}: {e}")
            await self.transport.send_error(str(e), request_id=message.request_id)

    async def _handle_prompt(self, session: Any, message: WebSocketMessage) -> None:
        """Handle prompt execution request."""
        content = message.payload.get("content", "")
        if not content:
            await self.transport.send_error(
                "Missing 'content' in prompt payload",
                request_id=message.request_id,
            )
            return

        # Cancel any existing execution
        if self._execution_task and not self._execution_task.done():
            self._execution_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._execution_task

        # Start new execution
        self._execution_task = asyncio.create_task(
            self._stream_execution(session, content, message.request_id)
        )

    async def _stream_execution(self, session: Any, content: str, request_id: str | None) -> None:
        """Stream execution events to the client."""
        try:
            async for event in session.execute(content):
                if not self._running:
                    break

                await self.transport.send_message(
                    WebSocketMessage(
                        type=WebSocketMessageType.EVENT,
                        payload={"type": event.type, **event.properties},
                        request_id=request_id,
                    )
                )

            # Send completion event
            await self.transport.send_message(
                WebSocketMessage(
                    type=WebSocketMessageType.EVENT,
                    payload={"type": "done"},
                    request_id=request_id,
                )
            )

        except asyncio.CancelledError:
            await self.transport.send_message(
                WebSocketMessage(
                    type=WebSocketMessageType.EVENT,
                    payload={"type": "cancelled"},
                    request_id=request_id,
                )
            )
        except Exception as e:
            logger.exception(f"Execution error: {e}")
            await self.transport.send_error(str(e), request_id=request_id)

    async def _handle_abort(self, session: Any, message: WebSocketMessage) -> None:
        """Handle abort request."""
        if self._execution_task and not self._execution_task.done():
            self._execution_task.cancel()
            await self.transport.send_message(
                WebSocketMessage(
                    type=WebSocketMessageType.EVENT,
                    payload={"type": "abort_acknowledged"},
                    request_id=message.request_id,
                )
            )
        else:
            await self.transport.send_message(
                WebSocketMessage(
                    type=WebSocketMessageType.EVENT,
                    payload={"type": "no_execution_to_abort"},
                    request_id=message.request_id,
                )
            )

    async def _handle_approval(self, session: Any, message: WebSocketMessage) -> None:
        """Handle approval response."""
        approval_id = message.payload.get("approval_id")
        choice = message.payload.get("choice")

        if not approval_id or not choice:
            await self.transport.send_error(
                "Missing 'approval_id' or 'choice' in approval payload",
                request_id=message.request_id,
            )
            return

        try:
            result = await session.handle_approval(approval_id, choice)
            await self.transport.send_message(
                WebSocketMessage(
                    type=WebSocketMessageType.EVENT,
                    payload={"type": "approval_handled", "success": result},
                    request_id=message.request_id,
                )
            )
        except Exception as e:
            await self.transport.send_error(
                f"Approval handling failed: {e}",
                request_id=message.request_id,
            )

    async def _cleanup(self) -> None:
        """Cleanup resources on disconnect."""
        if self._execution_task and not self._execution_task.done():
            self._execution_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._execution_task

        await self.transport.disconnect()


async def websocket_session_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for session communication.

    URL: /ws/sessions/{session_id}

    Protocol:
    1. Client connects with session_id in URL
    2. Server sends 'connected' message with protocol version
    3. Client can send:
       - prompt: Execute a prompt, receive streaming events
       - abort: Cancel current execution
       - approval: Respond to approval request
       - ping: Keep-alive (server responds with pong)
    4. Server streams events back for the active execution
    """
    session_id = websocket.path_params.get("session_id")
    if not session_id:
        await websocket.close(code=4000, reason="Missing session_id")
        return

    handler = WebSocketSessionHandler(websocket, session_id)
    await handler.handle()


async def websocket_global_endpoint(websocket: WebSocket) -> None:
    """Global WebSocket endpoint for system-wide events.

    URL: /ws

    Streams all events from the event bus to connected clients.
    Useful for dashboards or monitoring tools that need all events.
    """
    from ..bus import Bus

    transport = WebSocketServerTransport(websocket)

    try:
        await transport.connect()

        async for event in Bus.stream():
            if not transport.is_connected:
                break

            await transport.send_message(
                WebSocketMessage(
                    type=WebSocketMessageType.EVENT,
                    payload=event,
                )
            )

    except WebSocketDisconnect:
        logger.info("Global WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"Global WebSocket error: {e}")
    finally:
        await transport.disconnect()


# Route definitions
websocket_routes = [
    WebSocketRoute("/ws", websocket_global_endpoint),
    WebSocketRoute("/ws/sessions/{session_id}", websocket_session_endpoint),
]
