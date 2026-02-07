"""Tests for recipe discovery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_app_runtime.recipes.discovery import RecipeDiscovery
from amplifier_app_runtime.recipes.types import (
    RecipeLocation,
    RecipeSourceType,
)


class TestRecipeDiscovery:
    """Test RecipeDiscovery class."""

    @pytest.mark.asyncio
    async def test_discover_workspace_recipes(self, tmp_path):
        """Test discovering workspace recipes."""
        # Create workspace structure
        workspace = tmp_path
        recipes_dir = workspace / ".amplifier" / "recipes"
        recipes_dir.mkdir(parents=True)

        # Create test recipes
        (recipes_dir / "recipe1.yaml").write_text("description: Recipe 1\nsteps:\n  - name: s1")
        (recipes_dir / "recipe2.yaml").write_text("description: Recipe 2\nsteps:\n  - name: s1")

        # Change to workspace directory
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(workspace)

            discovery = RecipeDiscovery()
            locations = await discovery.discover_recipes(include_bundles=False, include_user=False)

            assert len(locations) == 2
            assert all(loc.source_type == RecipeSourceType.WORKSPACE for loc in locations)
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_discover_user_recipes(self, tmp_path, monkeypatch):
        """Test discovering user recipes."""
        # Create user recipes structure
        user_recipes = tmp_path / "user" / ".amplifier" / "recipes"
        user_recipes.mkdir(parents=True)

        (user_recipes / "user-recipe.yaml").write_text("description: User\nsteps:\n  - name: s1")

        # Mock Path.home() to return our temp directory
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "user")

        discovery = RecipeDiscovery()
        locations = await discovery.discover_recipes(include_bundles=False, include_workspace=False)

        assert len(locations) == 1
        assert locations[0].source_type == RecipeSourceType.USER

    @pytest.mark.asyncio
    async def test_discover_with_pattern(self, tmp_path):
        """Test discovery with glob pattern."""
        recipes_dir = tmp_path / ".amplifier" / "recipes"
        recipes_dir.mkdir(parents=True)

        # Create recipes with different names
        (recipes_dir / "code-review.yaml").write_text("description: CR\nsteps:\n  - name: s1")
        (recipes_dir / "code-analyze.yaml").write_text("description: CA\nsteps:\n  - name: s1")
        (recipes_dir / "other.yaml").write_text("description: Other\nsteps:\n  - name: s1")

        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            discovery = RecipeDiscovery()
            locations = await discovery.discover_recipes(
                pattern="code-*", include_bundles=False, include_user=False
            )

            assert len(locations) == 2
            assert all("code-" in loc.path for loc in locations)
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_discover_empty_returns_empty_list(self, tmp_path):
        """Test discovery with no recipes returns empty list."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            discovery = RecipeDiscovery()
            locations = await discovery.discover_recipes(include_bundles=False)

            assert locations == []
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_get_metadata_for_location(self, tmp_path):
        """Test extracting metadata for a location."""
        recipe_file = tmp_path / "test.yaml"
        recipe_file.write_text("description: Test\nsteps:\n  - name: step1")

        location = RecipeLocation(path=str(recipe_file), source_type=RecipeSourceType.WORKSPACE)

        discovery = RecipeDiscovery()
        metadata = await discovery.get_metadata(location)

        assert metadata.valid is True
        assert metadata.name == "test"
        assert metadata.description == "Test"

    @pytest.mark.asyncio
    async def test_get_metadata_batch(self, tmp_path):
        """Test batch metadata extraction."""
        # Create multiple recipes
        recipe1 = tmp_path / "recipe1.yaml"
        recipe1.write_text("description: R1\nsteps:\n  - name: s1")

        recipe2 = tmp_path / "recipe2.yaml"
        recipe2.write_text("description: R2\nsteps:\n  - name: s1")

        locations = [
            RecipeLocation(path=str(recipe1), source_type=RecipeSourceType.WORKSPACE),
            RecipeLocation(path=str(recipe2), source_type=RecipeSourceType.WORKSPACE),
        ]

        discovery = RecipeDiscovery()
        metadata_list = await discovery.get_metadata_batch(locations)

        assert len(metadata_list) == 2
        assert all(m.valid for m in metadata_list)

    @pytest.mark.asyncio
    async def test_discover_with_metadata_convenience(self, tmp_path):
        """Test discover_with_metadata convenience method."""
        recipes_dir = tmp_path / ".amplifier" / "recipes"
        recipes_dir.mkdir(parents=True)

        (recipes_dir / "recipe.yaml").write_text("description: Test\nsteps:\n  - name: s1")

        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            discovery = RecipeDiscovery()
            metadata_list = await discovery.discover_with_metadata(
                include_bundles=False, include_user=False
            )

            assert len(metadata_list) == 1
            assert metadata_list[0].valid is True
            assert metadata_list[0].name == "recipe"
        finally:
            os.chdir(original_cwd)


class TestBundleRecipeDiscovery:
    """Test bundle recipe discovery."""

    @pytest.mark.asyncio
    async def test_get_bundle_recipes(self, tmp_path):
        """Test discovering recipes from a specific bundle."""
        # Create mock bundle structure
        bundle_root = tmp_path / "mock-bundle"
        recipes_dir = bundle_root / "recipes"
        recipes_dir.mkdir(parents=True)

        (recipes_dir / "example.yaml").write_text("description: Example\nsteps:\n  - name: s1")

        # Mock bundle loading
        mock_bundle = MagicMock()
        mock_bundle.base_path = bundle_root

        mock_registry = MagicMock()
        mock_registry.load = AsyncMock(return_value=mock_bundle)

        discovery = RecipeDiscovery()
        discovery._bundle_registry = mock_registry

        locations = await discovery.get_bundle_recipes("test-bundle")

        assert len(locations) == 1
        assert locations[0].source_type == RecipeSourceType.BUNDLE
        assert locations[0].bundle_name == "test-bundle"

    @pytest.mark.asyncio
    async def test_get_bundle_recipes_with_pattern(self, tmp_path):
        """Test bundle recipe discovery with pattern."""
        bundle_root = tmp_path / "bundle"
        recipes_dir = bundle_root / "recipes"
        recipes_dir.mkdir(parents=True)

        (recipes_dir / "code-review.yaml").write_text("description: CR\nsteps:\n  - name: s1")
        (recipes_dir / "code-analyze.yaml").write_text("description: CA\nsteps:\n  - name: s1")
        (recipes_dir / "other.yaml").write_text("description: Other\nsteps:\n  - name: s1")

        mock_bundle = MagicMock()
        mock_bundle.base_path = bundle_root

        mock_registry = MagicMock()
        mock_registry.load = AsyncMock(return_value=mock_bundle)

        discovery = RecipeDiscovery()
        discovery._bundle_registry = mock_registry

        locations = await discovery.get_bundle_recipes("test-bundle", pattern="code-*")

        assert len(locations) == 2
        assert all("code-" in loc.path for loc in locations)

    @pytest.mark.asyncio
    async def test_get_bundle_recipes_no_recipes_directory(self, tmp_path):
        """Test bundle without recipes directory returns empty list."""
        bundle_root = tmp_path / "bundle-no-recipes"
        bundle_root.mkdir()

        mock_bundle = MagicMock()
        mock_bundle.base_path = bundle_root

        mock_registry = MagicMock()
        mock_registry.load = AsyncMock(return_value=mock_bundle)

        discovery = RecipeDiscovery()
        discovery._bundle_registry = mock_registry

        locations = await discovery.get_bundle_recipes("test-bundle")

        assert locations == []

    @pytest.mark.asyncio
    async def test_discover_bundle_recipes_integration(self, tmp_path):
        """Test discovering recipes from all bundles."""
        # Create mock bundle
        bundle_root = tmp_path / "bundle"
        recipes_dir = bundle_root / "recipes"
        recipes_dir.mkdir(parents=True)

        (recipes_dir / "example.yaml").write_text("description: Example\nsteps:\n  - name: s1")

        # Mock registry
        mock_bundle = MagicMock()
        mock_bundle.base_path = bundle_root

        mock_registry = MagicMock()
        mock_registry.load = AsyncMock(return_value=mock_bundle)
        mock_registry.list_registered = MagicMock(return_value=["test-bundle"])

        discovery = RecipeDiscovery()
        discovery._bundle_registry = mock_registry

        # Discover from bundles
        locations = await discovery.discover_recipes(include_workspace=False, include_user=False)

        assert len(locations) == 1
        assert locations[0].source_type == RecipeSourceType.BUNDLE


class TestFindYamlFiles:
    """Test YAML file discovery logic."""

    def test_find_all_yaml_files(self, tmp_path):
        """Test finding all YAML files recursively."""
        # Create structure
        (tmp_path / "recipe1.yaml").touch()
        (tmp_path / "recipe2.yaml").touch()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "recipe3.yaml").touch()

        discovery = RecipeDiscovery()
        files = discovery._find_yaml_files(tmp_path)

        assert len(files) == 3
        assert all(f.suffix == ".yaml" for f in files)

    def test_find_with_glob_pattern(self, tmp_path):
        """Test finding with glob pattern."""
        (tmp_path / "code-review.yaml").touch()
        (tmp_path / "code-analyze.yaml").touch()
        (tmp_path / "other.yaml").touch()

        discovery = RecipeDiscovery()
        files = discovery._find_yaml_files(tmp_path, pattern="code-*.yaml")

        assert len(files) == 2
        assert all("code-" in f.name for f in files)

    def test_find_with_simple_pattern(self, tmp_path):
        """Test finding with simple name pattern."""
        (tmp_path / "test-recipe.yaml").touch()
        (tmp_path / "production-recipe.yaml").touch()
        (tmp_path / "other.yaml").touch()

        discovery = RecipeDiscovery()
        files = discovery._find_yaml_files(tmp_path, pattern="*-recipe.yaml")

        assert len(files) == 2

    def test_find_excludes_directories(self, tmp_path):
        """Test that directories are not included."""
        (tmp_path / "recipe.yaml").mkdir()  # Directory named .yaml
        (tmp_path / "actual.yaml").touch()  # Actual file

        discovery = RecipeDiscovery()
        files = discovery._find_yaml_files(tmp_path)

        assert len(files) == 1
        assert files[0].name == "actual.yaml"
