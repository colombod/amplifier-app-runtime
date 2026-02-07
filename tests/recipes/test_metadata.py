"""Tests for recipe metadata extraction."""

from __future__ import annotations

import pytest

from amplifier_app_runtime.recipes.metadata import (
    extract_metadata,
    extract_metadata_safe,
)
from amplifier_app_runtime.recipes.types import RecipeSourceType


class TestExtractMetadata:
    """Test metadata extraction from recipe files."""

    @pytest.mark.asyncio
    async def test_extract_from_flat_recipe(self, tmp_path):
        """Test extracting metadata from flat recipe."""
        recipe_file = tmp_path / "test-recipe.yaml"
        recipe_file.write_text(
            """
description: Test recipe for unit tests
steps:
  - name: step1
    agent: self
  - name: step2
    agent: explorer
"""
        )

        metadata = await extract_metadata(str(recipe_file), RecipeSourceType.WORKSPACE)

        assert metadata.name == "test-recipe"
        assert metadata.description == "Test recipe for unit tests"
        assert metadata.valid is True
        assert metadata.requires_approval is False
        assert metadata.stages is None
        assert metadata.steps == ["step1", "step2"]
        assert metadata.source == RecipeSourceType.WORKSPACE

    @pytest.mark.asyncio
    async def test_extract_from_staged_recipe(self, tmp_path):
        """Test extracting metadata from staged recipe."""
        recipe_file = tmp_path / "staged-recipe.yaml"
        recipe_file.write_text(
            """
description: Staged recipe with approval gates
stages:
  - name: analysis
    agent: zen-architect
  - name: feedback
    agent: self
"""
        )

        metadata = await extract_metadata(str(recipe_file), RecipeSourceType.USER)

        assert metadata.name == "staged-recipe"
        assert metadata.requires_approval is True
        assert metadata.stages == ["analysis", "feedback"]
        assert metadata.steps is None
        assert metadata.source == RecipeSourceType.USER

    @pytest.mark.asyncio
    async def test_extract_handles_missing_description(self, tmp_path):
        """Test extraction handles missing description field."""
        recipe_file = tmp_path / "no-desc.yaml"
        recipe_file.write_text(
            """
steps:
  - name: step1
    agent: self
"""
        )

        metadata = await extract_metadata(str(recipe_file), RecipeSourceType.LOCAL)

        assert metadata.description == ""

    @pytest.mark.asyncio
    async def test_extract_raises_on_invalid_yaml(self, tmp_path):
        """Test extraction raises on invalid YAML."""
        recipe_file = tmp_path / "invalid.yaml"
        recipe_file.write_text("not: valid: yaml: {{{")

        with pytest.raises(ValueError, match="Invalid YAML"):
            await extract_metadata(str(recipe_file), RecipeSourceType.LOCAL)

    @pytest.mark.asyncio
    async def test_extract_raises_on_missing_file(self):
        """Test extraction raises on missing file."""
        with pytest.raises(ValueError, match="not found"):
            await extract_metadata("/nonexistent/recipe.yaml", RecipeSourceType.LOCAL)

    @pytest.mark.asyncio
    async def test_extract_raises_on_missing_steps_and_stages(self, tmp_path):
        """Test extraction raises if neither steps nor stages present."""
        recipe_file = tmp_path / "no-structure.yaml"
        recipe_file.write_text(
            """
description: Recipe without steps or stages
"""
        )

        with pytest.raises(ValueError, match="must have 'steps' or 'stages'"):
            await extract_metadata(str(recipe_file), RecipeSourceType.LOCAL)

    @pytest.mark.asyncio
    async def test_extract_handles_bundle_uri(self, tmp_path):
        """Test extraction handles bundle URI format."""
        # Create recipe file
        recipe_file = tmp_path / "example.yaml"
        recipe_file.write_text(
            """
description: Bundle recipe
steps:
  - name: step1
    agent: self
"""
        )

        # Pass as bundle URI - function should extract path after colon
        bundle_uri = f"@recipes:{recipe_file}"

        metadata = await extract_metadata(bundle_uri, RecipeSourceType.BUNDLE)

        # Path should be preserved as bundle URI
        assert metadata.path == bundle_uri
        assert metadata.source == RecipeSourceType.BUNDLE


class TestExtractMetadataSafe:
    """Test safe metadata extraction with error handling."""

    @pytest.mark.asyncio
    async def test_safe_extract_success(self, tmp_path):
        """Test safe extraction on valid recipe."""
        recipe_file = tmp_path / "valid.yaml"
        recipe_file.write_text(
            """
description: Valid recipe
steps:
  - name: step1
    agent: self
"""
        )

        metadata = await extract_metadata_safe(str(recipe_file), RecipeSourceType.WORKSPACE)

        assert metadata.valid is True
        assert metadata.error is None

    @pytest.mark.asyncio
    async def test_safe_extract_returns_error_metadata(self, tmp_path):
        """Test safe extraction returns metadata with error on failure."""
        recipe_file = tmp_path / "invalid.yaml"
        recipe_file.write_text("not: valid: yaml: {{{")

        metadata = await extract_metadata_safe(str(recipe_file), RecipeSourceType.LOCAL)

        assert metadata.valid is False
        assert metadata.error is not None
        assert "Invalid YAML" in metadata.error
        assert metadata.name == "invalid"

    @pytest.mark.asyncio
    async def test_safe_extract_missing_file(self):
        """Test safe extraction handles missing file."""
        metadata = await extract_metadata_safe("/nonexistent/recipe.yaml", RecipeSourceType.LOCAL)

        assert metadata.valid is False
        assert metadata.error is not None
        assert "not found" in metadata.error
