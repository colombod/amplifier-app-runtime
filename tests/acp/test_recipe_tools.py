"""Tests for ACP recipe tools integration.

These tests verify the ACP wrapper delegates correctly to the shared recipe
discovery module. Core recipe discovery logic is tested in tests/recipes/.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from amplifier_app_runtime.acp.recipe_tools import list_recipes_tool


class TestListRecipesTool:
    """Test suite for list_recipes_tool (ACP wrapper)."""

    @pytest.mark.asyncio
    async def test_list_recipes_returns_structure(self):
        """Test list_recipes returns expected structure."""
        # Mock the shared RecipeDiscovery module at import location
        with patch("amplifier_app_runtime.recipes.RecipeDiscovery") as mock_discovery_class:
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_with_metadata = AsyncMock(return_value=[])

            result = await list_recipes_tool()

        assert "recipes" in result
        assert "count" in result
        assert "pattern" in result
        assert isinstance(result["recipes"], list)
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_recipes_with_pattern(self):
        """Test list_recipes accepts pattern parameter."""
        with patch("amplifier_app_runtime.recipes.RecipeDiscovery") as mock_discovery_class:
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_with_metadata = AsyncMock(return_value=[])

            result = await list_recipes_tool(pattern="code-*")

        assert result["pattern"] == "code-*"
        # Verify pattern was passed to underlying module
        mock_discovery.discover_with_metadata.assert_called_once_with(pattern="code-*")

    @pytest.mark.asyncio
    async def test_list_recipes_handles_errors_gracefully(self):
        """Test list_recipes returns error structure on failure."""
        with patch("amplifier_app_runtime.recipes.RecipeDiscovery") as mock_discovery_class:
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_with_metadata = AsyncMock(
                side_effect=RuntimeError("Discovery failed")
            )

            result = await list_recipes_tool()

        assert result["recipes"] == []
        assert result["count"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_recipes_converts_metadata_to_dict(self):
        """Test list_recipes converts RecipeMetadata to dicts."""
        from amplifier_app_runtime.recipes.types import RecipeMetadata, RecipeSourceType

        # Create mock metadata
        mock_metadata = RecipeMetadata(
            path="test.yaml",
            name="test",
            description="Test recipe",
            valid=True,
            requires_approval=False,
            stages=None,
            steps=["step1"],
            source=RecipeSourceType.WORKSPACE,
        )

        with patch("amplifier_app_runtime.recipes.RecipeDiscovery") as mock_discovery_class:
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_with_metadata = AsyncMock(return_value=[mock_metadata])

            result = await list_recipes_tool()

        assert result["count"] == 1
        assert isinstance(result["recipes"][0], dict)
        assert result["recipes"][0]["name"] == "test"
        assert result["recipes"][0]["source"] == "workspace"

    @pytest.mark.asyncio
    async def test_list_recipes_invalid_recipe_in_results(self):
        """Test invalid recipes are included with error field."""
        from amplifier_app_runtime.recipes.types import RecipeMetadata, RecipeSourceType

        # Create mock metadata for invalid recipe
        invalid_metadata = RecipeMetadata(
            path="broken.yaml",
            name="broken",
            description="",
            valid=False,
            requires_approval=False,
            stages=None,
            steps=None,
            source=RecipeSourceType.LOCAL,
            error="Invalid YAML: unexpected token",
        )

        with patch("amplifier_app_runtime.recipes.RecipeDiscovery") as mock_discovery_class:
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_with_metadata = AsyncMock(return_value=[invalid_metadata])

            result = await list_recipes_tool()

        assert result["count"] == 1
        assert result["recipes"][0]["valid"] is False
        assert result["recipes"][0]["error"] is not None
