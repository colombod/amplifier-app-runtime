"""Amplifier Server Application.

Creates the Starlette ASGI application with all routes.
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from .routes import event_routes, health_routes, session_routes


def create_app() -> Starlette:
    """Create the Amplifier backend application.

    Returns:
        Configured Starlette application
    """
    # Combine all routes
    routes: list[Route] = []
    routes.extend(health_routes)
    routes.extend(event_routes)
    routes.extend(session_routes)

    # CORS middleware for local development (Phase 1)
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
