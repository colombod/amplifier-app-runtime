"""Tests for recipe types."""

from __future__ import annotations

from amplifier_app_runtime.recipes.types import (
    RecipeLocation,
    RecipeMetadata,
    RecipeSourceType,
)


class TestRecipeSourceType:
    """Test RecipeSourceType enum."""

    def test_enum_values(self):
        """Test all enum values are defined."""
        assert RecipeSourceType.WORKSPACE.value == "workspace"
        assert RecipeSourceType.USER.value == "user"
        assert RecipeSourceType.BUNDLE.value == "bundle"
        assert RecipeSourceType.LOCAL.value == "local"


class TestRecipeLocation:
    """Test RecipeLocation dataclass."""

    def test_workspace_location(self):
        """Test workspace recipe location."""
        loc = RecipeLocation(
            path="/path/to/workspace/.amplifier/recipes/test.yaml",
            source_type=RecipeSourceType.WORKSPACE,
        )

        assert loc.path == "/path/to/workspace/.amplifier/recipes/test.yaml"
        assert loc.source_type == RecipeSourceType.WORKSPACE
        assert loc.bundle_name is None
        assert not loc.is_bundle_recipe

    def test_bundle_location(self):
        """Test bundle recipe location."""
        loc = RecipeLocation(
            path="/path/to/bundle/recipes/example.yaml",
            source_type=RecipeSourceType.BUNDLE,
            bundle_name="recipes",
        )

        assert loc.is_bundle_recipe
        assert loc.bundle_name == "recipes"

    def test_display_path_for_bundle(self):
        """Test display_path generates correct URI for bundles."""
        loc = RecipeLocation(
            path="/path/to/bundle/recipes/example.yaml",
            source_type=RecipeSourceType.BUNDLE,
            bundle_name="recipes",
        )

        # Display path should show URI format
        display = loc.display_path
        assert display.startswith("@recipes:")

    def test_display_path_for_local(self):
        """Test display_path returns path as-is for non-bundle."""
        loc = RecipeLocation(path="/local/recipe.yaml", source_type=RecipeSourceType.LOCAL)

        assert loc.display_path == "/local/recipe.yaml"


class TestRecipeMetadata:
    """Test RecipeMetadata dataclass."""

    def test_valid_flat_recipe_metadata(self):
        """Test metadata for valid flat recipe."""
        metadata = RecipeMetadata(
            path="/path/to/recipe.yaml",
            name="test-recipe",
            description="Test recipe",
            valid=True,
            requires_approval=False,
            stages=None,
            steps=["step1", "step2"],
            source=RecipeSourceType.WORKSPACE,
        )

        assert metadata.valid
        assert not metadata.requires_approval
        assert metadata.steps == ["step1", "step2"]
        assert metadata.stages is None

    def test_valid_staged_recipe_metadata(self):
        """Test metadata for valid staged recipe."""
        metadata = RecipeMetadata(
            path="/path/to/staged.yaml",
            name="staged-recipe",
            description="Staged recipe",
            valid=True,
            requires_approval=True,
            stages=["planning", "implementation"],
            steps=None,
            source=RecipeSourceType.USER,
        )

        assert metadata.valid
        assert metadata.requires_approval
        assert metadata.stages == ["planning", "implementation"]
        assert metadata.steps is None

    def test_invalid_recipe_metadata(self):
        """Test metadata for invalid recipe."""
        metadata = RecipeMetadata(
            path="/path/to/broken.yaml",
            name="broken",
            description="",
            valid=False,
            requires_approval=False,
            stages=None,
            steps=None,
            source=RecipeSourceType.LOCAL,
            error="Invalid YAML: expected mapping",
        )

        assert not metadata.valid
        assert metadata.error is not None

    def test_to_dict_conversion(self):
        """Test converting metadata to dictionary."""
        metadata = RecipeMetadata(
            path="/path/to/recipe.yaml",
            name="test",
            description="Test recipe",
            valid=True,
            requires_approval=False,
            stages=None,
            steps=["step1"],
            source=RecipeSourceType.WORKSPACE,
        )

        result = metadata.to_dict()

        assert result["path"] == "/path/to/recipe.yaml"
        assert result["name"] == "test"
        assert result["source"] == "workspace"
        assert result["valid"] is True
        assert result["steps"] == ["step1"]

    def test_to_dict_with_error(self):
        """Test to_dict includes error field."""
        metadata = RecipeMetadata(
            path="/path/to/broken.yaml",
            name="broken",
            description="",
            valid=False,
            requires_approval=False,
            stages=None,
            steps=None,
            source=RecipeSourceType.LOCAL,
            error="Parse failed",
        )

        result = metadata.to_dict()

        assert result["valid"] is False
        assert result["error"] == "Parse failed"
