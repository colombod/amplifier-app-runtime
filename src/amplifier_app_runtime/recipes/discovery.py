"""Transport-agnostic recipe discovery.

Provides core recipe discovery functionality usable by any transport
(ACP, WebSocket, SSE, stdio, etc.).
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from .metadata import extract_metadata_safe
from .types import RecipeLocation, RecipeMetadata, RecipeSourceType

logger = logging.getLogger(__name__)


class RecipeDiscovery:
    """Transport-agnostic recipe discovery.

    Discovers recipes from multiple sources:
    - Loaded bundles (via amplifier-foundation)
    - Workspace recipes (.amplifier/recipes/)
    - User recipes (~/.amplifier/recipes/)
    - Local files (arbitrary paths)

    Usage:
        discovery = RecipeDiscovery()
        locations = await discovery.discover_recipes(pattern="code-*")
        metadata = await discovery.get_metadata_batch(locations)
    """

    def __init__(self) -> None:
        """Initialize recipe discovery."""
        self._bundle_registry: Any | None = None

    async def discover_recipes(
        self,
        pattern: str | None = None,
        include_bundles: bool = True,
        include_workspace: bool = True,
        include_user: bool = True,
    ) -> list[RecipeLocation]:
        """Discover recipe files from all sources.

        Args:
            pattern: Optional glob pattern to filter recipes (e.g., "code-*", "*.yaml")
            include_bundles: Whether to search loaded bundles
            include_workspace: Whether to search workspace recipes
            include_user: Whether to search user recipes

        Returns:
            List of recipe locations
        """
        locations: list[RecipeLocation] = []

        # Discover from bundles
        if include_bundles:
            try:
                bundle_locations = await self._discover_bundle_recipes(pattern)
                locations.extend(bundle_locations)
            except Exception as e:
                logger.debug(f"Bundle recipe discovery failed: {e}")

        # Discover from workspace
        if include_workspace:
            workspace_path = Path.cwd() / ".amplifier" / "recipes"
            if workspace_path.exists():
                workspace_locations = self._discover_directory_recipes(
                    workspace_path, RecipeSourceType.WORKSPACE, pattern
                )
                locations.extend(workspace_locations)

        # Discover from user directory
        if include_user:
            user_path = Path.home() / ".amplifier" / "recipes"
            if user_path.exists():
                user_locations = self._discover_directory_recipes(
                    user_path, RecipeSourceType.USER, pattern
                )
                locations.extend(user_locations)

        return locations

    async def get_bundle_recipes(
        self, bundle_name: str, pattern: str | None = None
    ) -> list[RecipeLocation]:
        """Get recipes from a specific bundle.

        Args:
            bundle_name: Name of bundle to search
            pattern: Optional glob pattern

        Returns:
            List of recipe locations from the bundle
        """
        try:
            bundle_path = await self._get_bundle_path(bundle_name)
            if bundle_path is None:
                logger.warning(f"Bundle '{bundle_name}' not found or has no path")
                return []

            recipes_dir = bundle_path / "recipes"
            if not recipes_dir.exists():
                logger.debug(f"Bundle '{bundle_name}' has no recipes directory")
                return []

            # Find YAML files in bundle recipes directory
            yaml_files = self._find_yaml_files(recipes_dir, pattern)

            # Convert to RecipeLocation
            locations = []
            for file_path in yaml_files:
                # RecipeLocation stores filesystem path, display_path property generates URI
                locations.append(
                    RecipeLocation(
                        path=str(file_path),
                        source_type=RecipeSourceType.BUNDLE,
                        bundle_name=bundle_name,
                    )
                )

            return locations

        except Exception as e:
            logger.error(f"Failed to get recipes from bundle '{bundle_name}': {e}")
            return []

    async def get_metadata(self, location: RecipeLocation) -> RecipeMetadata:
        """Extract metadata for a single recipe location.

        Args:
            location: Recipe location

        Returns:
            Recipe metadata
        """
        return await extract_metadata_safe(location.path, location.source_type)

    async def get_metadata_batch(self, locations: list[RecipeLocation]) -> list[RecipeMetadata]:
        """Extract metadata for multiple recipes.

        Args:
            locations: List of recipe locations

        Returns:
            List of recipe metadata (same order as input)
        """
        metadata_list = []
        for location in locations:
            metadata = await self.get_metadata(location)
            metadata_list.append(metadata)
        return metadata_list

    async def discover_with_metadata(
        self,
        pattern: str | None = None,
        include_bundles: bool = True,
        include_workspace: bool = True,
        include_user: bool = True,
    ) -> list[RecipeMetadata]:
        """Discover recipes and extract metadata in one call.

        Convenience method that combines discovery and metadata extraction.

        Args:
            pattern: Optional glob pattern
            include_bundles: Whether to search bundles
            include_workspace: Whether to search workspace
            include_user: Whether to search user directory

        Returns:
            List of recipe metadata
        """
        locations = await self.discover_recipes(
            pattern=pattern,
            include_bundles=include_bundles,
            include_workspace=include_workspace,
            include_user=include_user,
        )
        return await self.get_metadata_batch(locations)

    # Private methods

    async def _discover_bundle_recipes(self, pattern: str | None = None) -> list[RecipeLocation]:
        """Discover recipes from loaded bundles.

        Returns:
            List of recipe locations from bundles
        """
        locations: list[RecipeLocation] = []

        try:
            from amplifier_foundation.registry import BundleRegistry

            # Get or create bundle registry
            if self._bundle_registry is None:
                self._bundle_registry = BundleRegistry()

            # Get loaded bundles
            loaded_bundles = self._get_loaded_bundle_names()

            # Search each bundle for recipes
            for bundle_name in loaded_bundles:
                bundle_locations = await self.get_bundle_recipes(bundle_name, pattern)
                locations.extend(bundle_locations)

        except ImportError:
            logger.debug("amplifier-foundation not available for bundle recipe discovery")

        return locations

    def _get_loaded_bundle_names(self) -> list[str]:
        """Get names of currently loaded bundles.

        Returns:
            List of bundle names
        """
        # Check if we have a registry
        if self._bundle_registry is None:
            return []

        # Use list_registered() to get all registered bundle names
        try:
            return self._bundle_registry.list_registered()
        except Exception as e:
            logger.debug(f"Could not enumerate loaded bundles: {e}")

        return []

    async def _get_bundle_path(self, bundle_name: str) -> Path | None:
        """Get filesystem path for a bundle.

        Args:
            bundle_name: Name of bundle

        Returns:
            Path to bundle root directory, or None if not found
        """
        try:
            if self._bundle_registry is None:
                from amplifier_foundation.registry import BundleRegistry

                self._bundle_registry = BundleRegistry()

            # Load bundle to get its configuration
            bundle = await self._bundle_registry.load(bundle_name)

            # Get bundle path from bundle object (base_path is the public attribute)
            if hasattr(bundle, "base_path"):
                return bundle.base_path

        except Exception as e:
            logger.debug(f"Could not get path for bundle '{bundle_name}': {e}")

        return None

    def _discover_directory_recipes(
        self, directory: Path, source_type: RecipeSourceType, pattern: str | None = None
    ) -> list[RecipeLocation]:
        """Discover recipes in a directory.

        Args:
            directory: Directory to search
            source_type: Type of source (workspace, user)
            pattern: Optional glob pattern

        Returns:
            List of recipe locations
        """
        yaml_files = self._find_yaml_files(directory, pattern)

        return [
            RecipeLocation(path=str(f), source_type=source_type, bundle_name=None)
            for f in yaml_files
        ]

    def _find_yaml_files(self, directory: Path, pattern: str | None = None) -> list[Path]:
        """Find YAML files in directory matching pattern.

        Args:
            directory: Directory to search
            pattern: Optional glob pattern

        Returns:
            List of file paths
        """
        if pattern:
            # Use glob pattern directly if it looks like a glob
            if "*" in pattern or "?" in pattern or "[" in pattern:
                files = directory.glob(pattern)
            else:
                # Simple pattern - search recursively and filter
                all_files = directory.rglob("*.yaml")
                files = [f for f in all_files if fnmatch.fnmatch(f.name, pattern)]
        else:
            # Find all YAML files recursively
            files = directory.rglob("*.yaml")

        return [f for f in files if f.is_file()]
