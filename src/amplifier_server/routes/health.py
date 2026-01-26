"""Health check endpoint."""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


health_routes = [
    Route("/health", health_check, methods=["GET"]),
]
