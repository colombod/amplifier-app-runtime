"""Transport-agnostic recipe discovery and management.

This module provides core recipe functionality usable by any transport
(ACP, WebSocket, SSE, stdio, etc.).

Public API:
    RecipeDiscovery - Main discovery class
    RecipeMetadata - Structured metadata from recipes
    RecipeLocation - Recipe file location
    RecipeSourceType - Enum for source types
    extract_metadata - Extract metadata from a recipe file
    extract_metadata_safe - Extract with error handling
"""

from __future__ import annotations

from .discovery import RecipeDiscovery
from .metadata import extract_metadata, extract_metadata_safe
from .types import RecipeLocation, RecipeMetadata, RecipeSourceType

__all__ = [
    "RecipeDiscovery",
    "RecipeMetadata",
    "RecipeLocation",
    "RecipeSourceType",
    "extract_metadata",
    "extract_metadata_safe",
]
