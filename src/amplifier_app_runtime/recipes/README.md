# Transport-Agnostic Recipe Discovery

This module provides core recipe discovery functionality usable by any transport (ACP, WebSocket, SSE, stdio, etc.).

## Overview

Recipe discovery was originally implemented in `acp/recipe_tools.py` for ACP-specific use. This module extracts and completes that functionality to make it reusable across all transports.

## Features

- **Multi-source discovery**: Bundles, workspace, user recipes
- **Complete bundle integration**: Fully implemented bundle recipe discovery using amplifier-foundation APIs
- **Pattern filtering**: Glob pattern support for recipe search
- **Metadata extraction**: Structured recipe information (stages, steps, approval gates)
- **Error handling**: Graceful degradation with error reporting

## Architecture

```
recipes/
├── __init__.py       # Public API exports
├── types.py          # Shared data types
├── metadata.py       # Metadata extraction
└── discovery.py      # Core discovery logic
```

## Usage

### Basic Discovery

```python
from amplifier_app_runtime.recipes import RecipeDiscovery

discovery = RecipeDiscovery()

# Discover all recipes with metadata
recipes = await discovery.discover_with_metadata()

for recipe in recipes:
    print(f"{recipe.name}: {recipe.description}")
    print(f"  Source: {recipe.source.value}")
    print(f"  Requires approval: {recipe.requires_approval}")
```

### Pattern Filtering

```python
# Find all code-related recipes
code_recipes = await discovery.discover_with_metadata(pattern="code-*")

# Find all YAML files matching pattern
yaml_recipes = await discovery.discover_with_metadata(pattern="*.yaml")
```

### Source-Specific Discovery

```python
# Only workspace recipes
workspace_only = await discovery.discover_with_metadata(
    include_bundles=False,
    include_user=False
)

# Only bundle recipes
bundle_only = await discovery.discover_with_metadata(
    include_workspace=False,
    include_user=False
)
```

### Bundle-Specific Discovery

```python
# Get recipes from a specific bundle
recipes_bundle_recipes = await discovery.get_bundle_recipes("recipes")

# Get metadata
for location in recipes_bundle_recipes:
    metadata = await discovery.get_metadata(location)
    print(f"{metadata.name} from {location.bundle_name}")
```

## Recipe Sources

### 1. Bundle Recipes
- Location: `<bundle-root>/recipes/`
- Detection: Loaded via `amplifier-foundation` BundleRegistry
- URI format: `@bundle-name:recipes/example.yaml`
- Example: `@recipes:examples/code-review.yaml`

### 2. Workspace Recipes
- Location: `.amplifier/recipes/` (current working directory)
- Detection: Checks `Path.cwd() / ".amplifier" / "recipes"`
- Use case: Project-specific workflows

### 3. User Recipes
- Location: `~/.amplifier/recipes/`
- Detection: Checks `Path.home() / ".amplifier" / "recipes"`
- Use case: Personal reusable workflows

## Data Types

### RecipeSourceType

```python
class RecipeSourceType(Enum):
    WORKSPACE = "workspace"
    USER = "user"
    BUNDLE = "bundle"
    LOCAL = "local"
```

### RecipeLocation

```python
@dataclass
class RecipeLocation:
    path: str                       # Filesystem path
    source_type: RecipeSourceType   # Source type
    bundle_name: str | None         # Bundle name if source is BUNDLE
    
    @property
    def is_bundle_recipe(self) -> bool
    
    @property
    def display_path(self) -> str  # Human-readable path/URI
```

### RecipeMetadata

```python
@dataclass
class RecipeMetadata:
    path: str                       # Full path or URI
    name: str                       # Recipe name (from filename)
    description: str                # From YAML description field
    valid: bool                     # Parse successful
    requires_approval: bool         # Has approval gates (staged recipes)
    stages: list[str] | None        # Stage names (staged recipes)
    steps: list[str] | None         # Step names (flat recipes)
    source: RecipeSourceType        # Source type
    error: str | None               # Error message if invalid
    
    def to_dict(self) -> dict       # Serialize to dict
```

## Integration with Transports

### ACP Integration (Reference Implementation)

```python
# acp/recipe_tools.py
from ..recipes import RecipeDiscovery

async def list_recipes_tool(pattern: str | None = None) -> dict:
    """ACP host-defined tool for recipe discovery."""
    discovery = RecipeDiscovery()
    metadata_list = await discovery.discover_with_metadata(pattern=pattern)
    
    return {
        "recipes": [m.to_dict() for m in metadata_list],
        "count": len(metadata_list),
        "pattern": pattern,
    }
```

### Other Transports

Any transport can use the same pattern:

```python
from amplifier_app_runtime.recipes import RecipeDiscovery

# In your transport's handler
discovery = RecipeDiscovery()
recipes = await discovery.discover_with_metadata()

# Transform to your transport's format
return your_format(recipes)
```

## Bundle Discovery Implementation

The module implements complete bundle recipe discovery using `amplifier-foundation` APIs:

1. **Enumerate loaded bundles**: Uses `registry.list_registered()`
2. **Get bundle path**: Uses `bundle.base_path` (public attribute)
3. **Search recipes/ directory**: Looks for YAML files in `<bundle-root>/recipes/`
4. **Pattern matching**: Supports glob patterns within bundle recipes
5. **URI generation**: Creates `@bundle:path` URIs via `RecipeLocation.display_path`

## Testing

```bash
# Test shared module
uv run pytest tests/recipes/ -v

# Test ACP integration
uv run pytest tests/acp/test_recipe_tools.py -v

# Test all recipe functionality
uv run pytest tests/recipes/ tests/acp/test_recipe_*.py -v
```

**Test coverage**: 40 tests across:
- 35 tests for shared module (types, metadata, discovery)
- 5 tests for ACP integration
- All original 17 event mapping tests pass

## Migration from Original Implementation

The original `acp/recipe_tools.py` (219 lines) is now:
- **Shared module** (3 files, 400 lines): Transport-agnostic core logic
- **ACP wrapper** (71 lines): Thin wrapper delegating to shared module

Benefits:
- ✅ Reusable across all transports
- ✅ Complete bundle discovery (was placeholder)
- ✅ Better separation of concerns
- ✅ Independent testability
- ✅ Backward compatible with ACP

## API Reference

### RecipeDiscovery Class

```python
class RecipeDiscovery:
    async def discover_recipes(
        pattern: str | None = None,
        include_bundles: bool = True,
        include_workspace: bool = True,
        include_user: bool = True
    ) -> list[RecipeLocation]
    
    async def get_bundle_recipes(
        bundle_name: str,
        pattern: str | None = None
    ) -> list[RecipeLocation]
    
    async def get_metadata(
        location: RecipeLocation
    ) -> RecipeMetadata
    
    async def get_metadata_batch(
        locations: list[RecipeLocation]
    ) -> list[RecipeMetadata]
    
    async def discover_with_metadata(
        pattern: str | None = None,
        include_bundles: bool = True,
        include_workspace: bool = True,
        include_user: bool = True
    ) -> list[RecipeMetadata]
```

### Metadata Functions

```python
async def extract_metadata(
    recipe_path: str,
    source_type: RecipeSourceType
) -> RecipeMetadata
    # Raises ValueError on parse errors

async def extract_metadata_safe(
    recipe_path: str,
    source_type: RecipeSourceType
) -> RecipeMetadata
    # Returns RecipeMetadata with error field on failures
```

## Future Enhancements

- Recipe validation and linting (Issue #21)
- Recipe execution monitoring
- Remote recipe registries
- Recipe caching for performance
- Recipe versioning support
