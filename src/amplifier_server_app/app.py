"""Amplifier Server Application.

Creates the Starlette ASGI application with all routes.

Route organization:
- /health - Health check endpoints
- /event - SSE event streaming (legacy)
- /session/* - Session management (legacy, will be deprecated)
- /v1/* - Protocol-based routes (recommended)
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route

from .acp import acp_routes
from .routes import (
    event_routes,
    health_routes,
    protocol_routes,
    session_routes,
    websocket_routes,
)


def create_app(*, use_protocol_routes: bool = True) -> Starlette:
    """Create the Amplifier backend application.

    Args:
        use_protocol_routes: If True, use protocol-based routes at /v1/
                            If False, use legacy session routes

    Returns:
        Configured Starlette application
    """
    # Combine all routes
    routes: list[Route | Mount] = []
    routes.extend(health_routes)
    routes.extend(event_routes)
    routes.extend(websocket_routes)  # WebSocket full-duplex transport
    routes.extend(acp_routes)  # Agent Client Protocol (ACP) routes

    if use_protocol_routes:
        # Mount protocol routes at /v1/ prefix
        routes.append(Mount("/v1", routes=protocol_routes))
        # Also keep at root for backward compatibility during migration
        routes.extend(protocol_routes)
    else:
        # Legacy routes
        routes.extend(session_routes)

    # CORS middleware for local development
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]

    app = Starlette(routes=routes, middleware=middleware)
    return app


# Lazy singleton for embedded mode
_app: Starlette | None = None


def get_app() -> Starlette:
    """Get or create the application singleton.

    Used by embedded mode to ensure single app instance.
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app
