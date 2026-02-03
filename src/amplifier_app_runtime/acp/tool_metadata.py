"""Shared tool metadata for ACP integration.

This module provides a single source of truth for tool display information
used across the ACP implementation (event mapping, approval bridge, etc.).

Consolidates duplicate tool title/kind mappings that were previously
scattered across agent.py and approval_bridge.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolMeta:
    """Metadata for a tool's ACP display properties.

    Attributes:
        kind: ACP tool kind (read, edit, execute, search, fetch, think, other)
        title_fn: Function to generate human-readable title from arguments
        category: Optional category for grouping (file, web, code, etc.)
    """

    kind: str
    title_fn: Callable[[dict[str, Any]], str]
    category: str | None = None


def _truncate(s: str, max_len: int = 50) -> str:
    """Truncate string with ellipsis if too long."""
    return s[:max_len] + "..." if len(s) > max_len else s


# =============================================================================
# Tool Metadata Registry
# =============================================================================

TOOL_METADATA: dict[str, ToolMeta] = {
    # File operations
    "read_file": ToolMeta(
        kind="read",
        title_fn=lambda args: f"Reading {args.get('file_path', 'file')}",
        category="file",
    ),
    "write_file": ToolMeta(
        kind="edit",
        title_fn=lambda args: f"Writing {args.get('file_path', 'file')}",
        category="file",
    ),
    "edit_file": ToolMeta(
        kind="edit",
        title_fn=lambda args: f"Editing {args.get('file_path', 'file')}",
        category="file",
    ),
    "glob": ToolMeta(
        kind="search",
        title_fn=lambda args: f"Finding files: {args.get('pattern', '*')}",
        category="file",
    ),
    "grep": ToolMeta(
        kind="search",
        title_fn=lambda args: f"Searching for: {_truncate(args.get('pattern', '...'))}",
        category="file",
    ),
    "load_skill": ToolMeta(
        kind="read",
        title_fn=lambda args: f"Loading skill: {args.get('skill_name', 'skill')}",
        category="file",
    ),
    # Execution operations
    "bash": ToolMeta(
        kind="execute",
        title_fn=lambda args: f"Run: {_truncate(args.get('command', 'command'))}",
        category="execute",
    ),
    "python_check": ToolMeta(
        kind="execute",
        title_fn=lambda args: "Checking Python code",
        category="code",
    ),
    "recipes": ToolMeta(
        kind="execute",
        title_fn=lambda args: f"Recipe: {args.get('operation', 'execute')}",
        category="workflow",
    ),
    # Web operations
    "web_fetch": ToolMeta(
        kind="fetch",
        title_fn=lambda args: f"Fetching {_truncate(args.get('url', 'URL'))}",
        category="web",
    ),
    "web_search": ToolMeta(
        kind="search",
        title_fn=lambda args: f"Searching: {_truncate(args.get('query', '...'))}",
        category="web",
    ),
    # Agent/planning operations
    "task": ToolMeta(
        kind="think",
        title_fn=lambda args: f"Delegating to {args.get('agent', 'agent')}",
        category="agent",
    ),
    "todo": ToolMeta(
        kind="think",
        title_fn=lambda args: "Updating task list",
        category="planning",
    ),
    # IDE tools (ACP client-side)
    "ide_terminal": ToolMeta(
        kind="execute",
        title_fn=lambda args: f"Terminal: {_truncate(args.get('command', 'command'))}",
        category="ide",
    ),
    "ide_read_file": ToolMeta(
        kind="read",
        title_fn=lambda args: f"IDE Read: {args.get('path', 'file')}",
        category="ide",
    ),
    "ide_write_file": ToolMeta(
        kind="edit",
        title_fn=lambda args: f"IDE Write: {args.get('path', 'file')}",
        category="ide",
    ),
    # Shadow environment tools
    "shadow": ToolMeta(
        kind="execute",
        title_fn=lambda args: f"Shadow: {args.get('operation', 'operation')}",
        category="testing",
    ),
}


# =============================================================================
# Public API
# =============================================================================


def get_tool_title(tool_name: str, arguments: dict[str, Any]) -> str:
    """Generate a human-readable title for a tool call.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments dictionary

    Returns:
        Human-readable title string for display in IDE

    Example:
        >>> get_tool_title("read_file", {"file_path": "/src/main.py"})
        'Reading /src/main.py'
    """
    meta = TOOL_METADATA.get(tool_name)
    if meta:
        try:
            return meta.title_fn(arguments)
        except Exception:
            pass

    # Default: humanize the tool name
    return tool_name.replace("_", " ").title()


def get_tool_kind(tool_name: str) -> str:
    """Get the ACP tool kind for a tool.

    ACP tool kinds are used by IDEs to display appropriate icons/styling:
    - read: Reading data (file, API, etc.)
    - edit: Modifying data
    - delete: Removing data
    - move: Moving/renaming
    - search: Searching/finding
    - execute: Running commands/code
    - think: Planning/reasoning
    - fetch: Network requests
    - other: Default fallback

    Args:
        tool_name: Name of the tool

    Returns:
        ACP tool kind string

    Example:
        >>> get_tool_kind("bash")
        'execute'
        >>> get_tool_kind("unknown_tool")
        'other'
    """
    meta = TOOL_METADATA.get(tool_name)
    return meta.kind if meta else "other"


def get_tool_category(tool_name: str) -> str | None:
    """Get the category for a tool (optional grouping).

    Categories are for internal organization:
    - file: File system operations
    - web: Web/network operations
    - code: Code analysis/checking
    - execute: Command execution
    - agent: Agent delegation
    - planning: Task planning
    - ide: IDE-specific tools
    - testing: Test environments

    Args:
        tool_name: Name of the tool

    Returns:
        Category string or None if not categorized
    """
    meta = TOOL_METADATA.get(tool_name)
    return meta.category if meta else None


def register_tool_metadata(
    tool_name: str,
    kind: str,
    title_fn: Callable[[dict[str, Any]], str],
    category: str | None = None,
) -> None:
    """Register metadata for a custom tool.

    Allows extensions to register their tools for proper ACP display.

    Args:
        tool_name: Name of the tool to register
        kind: ACP tool kind
        title_fn: Function to generate title from arguments
        category: Optional category for grouping
    """
    TOOL_METADATA[tool_name] = ToolMeta(
        kind=kind,
        title_fn=title_fn,
        category=category,
    )
