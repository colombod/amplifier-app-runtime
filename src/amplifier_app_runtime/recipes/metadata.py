"""Recipe metadata extraction."""

from __future__ import annotations

import logging
from pathlib import Path

from .types import RecipeMetadata, RecipeSourceType

logger = logging.getLogger(__name__)


async def extract_metadata(recipe_path: str, source_type: RecipeSourceType) -> RecipeMetadata:
    """Extract metadata from recipe YAML file.

    Args:
        recipe_path: Path to recipe file (can be URI like @bundle:path)
        source_type: Type of recipe source

    Returns:
        RecipeMetadata with extracted information

    Raises:
        ValueError: If recipe is invalid or cannot be parsed
    """
    import yaml

    # Handle bundle URIs - extract actual path
    file_path = recipe_path
    if recipe_path.startswith("@"):
        # Bundle URI - extract path after colon
        parts = recipe_path.split(":", 1)
        if len(parts) > 1:
            file_path = parts[1]

    # Read recipe file
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"Recipe file not found: {file_path}")

    try:
        with open(path) as f:
            recipe_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e

    if not isinstance(recipe_data, dict):
        raise ValueError("Recipe YAML must be a dictionary")

    # Extract basic metadata
    name = path.stem
    description = recipe_data.get("description", "")

    # Check if staged or flat recipe
    requires_approval = False
    stages = None
    steps = None

    if "stages" in recipe_data:
        # Staged recipe with approval gates
        requires_approval = True
        stages = [stage.get("name", f"stage_{i}") for i, stage in enumerate(recipe_data["stages"])]
    elif "steps" in recipe_data:
        # Flat recipe
        requires_approval = False
        steps = [step.get("name", f"step_{i}") for i, step in enumerate(recipe_data["steps"])]
    else:
        raise ValueError("Recipe must have 'steps' or 'stages' field")

    return RecipeMetadata(
        path=recipe_path,
        name=name,
        description=description,
        valid=True,
        requires_approval=requires_approval,
        stages=stages,
        steps=steps,
        source=source_type,
        error=None,
    )


async def extract_metadata_safe(recipe_path: str, source_type: RecipeSourceType) -> RecipeMetadata:
    """Extract metadata with error handling.

    Args:
        recipe_path: Path to recipe file
        source_type: Type of recipe source

    Returns:
        RecipeMetadata (with error field set if extraction failed)
    """
    try:
        return await extract_metadata(recipe_path, source_type)
    except Exception as e:
        logger.warning(f"Failed to parse recipe {recipe_path}: {e}")
        # Return metadata with error
        name = Path(recipe_path).stem if not recipe_path.startswith("@") else recipe_path
        return RecipeMetadata(
            path=recipe_path,
            name=name,
            description="",
            valid=False,
            requires_approval=False,
            stages=None,
            steps=None,
            source=source_type,
            error=str(e),
        )
