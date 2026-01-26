"""SSE event streaming endpoint."""

import json

from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from ..bus import Bus
from ..events import ServerConnected, ServerConnectedProps


async def sse_endpoint(request: Request) -> StreamingResponse:
    """SSE endpoint - streams ALL events to clients.

    Clients subscribe to this endpoint to receive real-time updates
    about sessions, messages, tools, and approvals.
    """

    async def event_stream():
        # Send initial connected event
        connected = {
            "type": ServerConnected.type,
            "properties": ServerConnectedProps().model_dump(),
        }
        yield f"data: {json.dumps(connected)}\n\n"

        # Stream all events from the bus
        try:
            async for event in Bus.stream():
                # Check for client disconnect
                if await request.is_disconnected():
                    break

                yield f"data: {json.dumps(event)}\n\n"
        except GeneratorExit:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


event_routes = [
    Route("/event", sse_endpoint, methods=["GET"]),
]
