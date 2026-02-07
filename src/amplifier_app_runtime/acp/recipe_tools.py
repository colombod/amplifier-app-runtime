"""Recipe discovery and management tools for ACP.

Provides structured recipe metadata for IDE integration.

This module wraps the transport-agnostic recipe discovery module
(amplifier_app_runtime.recipes) for ACP-specific use.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def list_recipes_tool(pattern: str | None = None) -> dict[str, Any]:
    """List available recipes with metadata.

    This is a host-defined tool that provides structured recipe discovery
    for IDE clients. Returns machine-readable recipe metadata including
    name, description, stages, and approval gate information.

    Args:
        pattern: Optional glob pattern to filter recipes (e.g., "code-*", "*.yaml")

    Returns:
        Dictionary with:
        - recipes: List of recipe metadata dicts
        - count: Total number of recipes found
        - pattern: Pattern used (if any)

    Example output:
        {
            "recipes": [
                {
                    "path": "@recipes:examples/code-review.yaml",
                    "name": "code-review",
                    "description": "Systematic code review workflow",
                    "requires_approval": true,
                    "stages": ["analysis", "feedback"],
                    "steps": null,
                    "source": "bundle"
                }
            ],
            "count": 1,
            "pattern": null
        }
    """
    try:
        # Use shared recipe discovery module
        from ..recipes import RecipeDiscovery

        discovery = RecipeDiscovery()

        # Discover recipes with metadata
        metadata_list = await discovery.discover_with_metadata(pattern=pattern)

        # Convert to dict format for serialization
        recipes = [metadata.to_dict() for metadata in metadata_list]

        return {
            "recipes": recipes,
            "count": len(recipes),
            "pattern": pattern,
        }

    except Exception as e:
        logger.error(f"Recipe discovery failed: {e}")
        return {
            "recipes": [],
            "count": 0,
            "error": str(e),
        }
