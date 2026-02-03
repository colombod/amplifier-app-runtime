"""Module discovery endpoints.

Provides discovery of installed Amplifier modules (providers, tools, hooks, etc.)
without requiring them to be loaded into a session.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def list_modules(request: Request) -> JSONResponse:
    """List available Amplifier modules.
    
    Query parameters:
        type: Comma-separated list of module types to filter
              (provider, tool, orchestrator, context, hook)
    
    Returns:
        JSON object with modules grouped by type
        
    Example:
        GET /v1/modules?type=provider,hook
        
        {
          "provider": [
            {"id": "provider-anthropic", "name": "Anthropic", "version": "1.0.0", ...}
          ],
          "hook": [
            {"id": "hook-logging", "name": "Logging Hook", "version": "1.0.0", ...}
          ]
        }
    """
    # Import here to avoid circular dependencies
    try:
        from amplifier_core.loader import ModuleLoader
    except ImportError:
        # Fallback if running in environment without full amplifier-core
        return JSONResponse(
            {"error": "Module discovery not available in this runtime configuration"},
            status_code=503,
        )

    # Parse type filter
    type_param = request.query_params.get("type", "")
    type_filter = [t.strip() for t in type_param.split(",") if t.strip()]

    try:
        # Discover all installed modules
        loader = ModuleLoader()
        all_modules = await loader.discover()

        # Filter by type if requested
        if type_filter:
            all_modules = [m for m in all_modules if m.type in type_filter]

        # Group by type
        grouped = {}
        for module in all_modules:
            if module.type not in grouped:
                grouped[module.type] = []

            # Convert ModuleInfo to dict
            grouped[module.type].append(
                {
                    "id": module.id,
                    "name": module.name,
                    "type": module.type,
                    "version": getattr(module, "version", "1.0.0"),
                    "description": getattr(module, "description", f"Module: {module.name}"),
                    "mount_point": getattr(module, "mount_point", None),
                }
            )

        return JSONResponse(grouped)

    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to discover modules: {str(e)}"}, status_code=500
        )


# Routes
routes = [
    Route("/v1/modules", list_modules, methods=["GET"]),
]
