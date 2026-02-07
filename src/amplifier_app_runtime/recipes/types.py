"""Shared types for recipe discovery and management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecipeSourceType(Enum):
    """Type of recipe source."""

    WORKSPACE = "workspace"
    USER = "user"
    BUNDLE = "bundle"
    LOCAL = "local"


@dataclass
class RecipeLocation:
    """Location of a recipe file.

    Represents where a recipe is found and how to access it.

    Attributes:
        path: Full path or URI to recipe file
        source_type: Type of source (workspace, user, bundle, local)
        bundle_name: Name of bundle if source_type is BUNDLE
    """

    path: str
    source_type: RecipeSourceType
    bundle_name: str | None = None

    @property
    def is_bundle_recipe(self) -> bool:
        """Check if this is a bundle recipe."""
        return self.source_type == RecipeSourceType.BUNDLE

    @property
    def display_path(self) -> str:
        """Get human-readable display path."""
        if self.is_bundle_recipe and self.bundle_name:
            return f"@{self.bundle_name}:{self.path}"
        return self.path


@dataclass
class RecipeMetadata:
    """Structured recipe metadata.

    Extracted from recipe YAML files, providing structured information
    about recipe characteristics for IDE integration and execution.

    Attributes:
        path: Full path or URI to recipe file
        name: Recipe name (derived from filename)
        description: Recipe description from YAML
        valid: Whether recipe parsed successfully
        requires_approval: Whether recipe has approval gates (staged recipes)
        stages: List of stage names (for staged recipes)
        steps: List of step names (for flat recipes)
        source: Source type where recipe was found
        error: Error message if parsing failed
    """

    path: str
    name: str
    description: str
    valid: bool
    requires_approval: bool
    stages: list[str] | None
    steps: list[str] | None
    source: RecipeSourceType
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "path": self.path,
            "name": self.name,
            "description": self.description,
            "valid": self.valid,
            "requires_approval": self.requires_approval,
            "stages": self.stages,
            "steps": self.steps,
            "source": self.source.value,
            "error": self.error,
        }
