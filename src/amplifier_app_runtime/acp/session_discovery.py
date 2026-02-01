"""Amplifier session discovery from filesystem.

This module handles discovering and locating Amplifier sessions stored
in the filesystem at ~/.amplifier/projects/.

Extracted from agent.py to improve maintainability and testability.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Amplifier session storage location
AMPLIFIER_PROJECTS_DIR = Path.home() / ".amplifier" / "projects"


def encode_project_path(cwd: str) -> str:
    """Encode a working directory path to Amplifier's project directory name format.

    Amplifier encodes paths by replacing '/' with '-' and stripping leading '-'.

    Args:
        cwd: Working directory path (e.g., /home/user/project)

    Returns:
        Encoded directory name (e.g., -home-user-project)

    Example:
        >>> encode_project_path("/home/user/project")
        '-home-user-project'
    """
    # Normalize the path and replace / with -
    normalized = os.path.normpath(cwd)
    encoded = normalized.replace("/", "-").replace("\\", "-")
    # Ensure it starts with - (Unix paths start with /)
    if not encoded.startswith("-"):
        encoded = "-" + encoded
    return encoded


def decode_project_path(encoded: str) -> str:
    """Decode an Amplifier project directory name back to a path.

    Args:
        encoded: Encoded directory name (e.g., -home-user-project)

    Returns:
        Decoded path (e.g., /home/user/project)

    Example:
        >>> decode_project_path("-home-user-project")
        '/home/user/project'
    """
    # Replace - with / and handle the leading -
    if encoded.startswith("-"):
        encoded = encoded[1:]  # Remove leading -
    return "/" + encoded.replace("-", "/")


async def discover_sessions(
    cwd: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Discover Amplifier sessions from the filesystem.

    Scans ~/.amplifier/projects/{encoded-path}/sessions/ to find persisted
    sessions and their metadata.

    Args:
        cwd: If provided, only return sessions for this working directory.
             If None, returns sessions from all projects.
        limit: Maximum number of sessions to return.

    Returns:
        List of session metadata dicts with keys:
        - session_id: The session ID
        - cwd: Working directory for the session
        - name: Human-readable name (may be None)
        - created: ISO datetime string
        - updated: ISO datetime string
        - turn_count: Number of turns in session
        - state: Session state (ready, etc.)
        - bundle: Bundle name
        - is_child: Whether this is a child/spawned session
    """
    sessions: list[dict[str, Any]] = []

    if not AMPLIFIER_PROJECTS_DIR.exists():
        return sessions

    # Determine which project directories to scan
    project_dirs = _get_project_dirs(cwd)

    # Scan each project's sessions directory
    for project_dir, project_cwd in project_dirs:
        sessions_dir = project_dir / "sessions"
        if not sessions_dir.exists():
            continue

        for session_dir in sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            session_info = _load_session_metadata(session_dir, project_cwd)
            if session_info:
                sessions.append(session_info)

            if len(sessions) >= limit:
                break

        if len(sessions) >= limit:
            break

    # Sort by updated time (most recent first)
    sessions.sort(key=_session_sort_key, reverse=True)

    return sessions[:limit]


def find_session_directory(session_id: str, cwd: str | None = None) -> Path | None:
    """Find the directory for a specific session.

    Args:
        session_id: The session ID to find.
        cwd: Optional working directory hint to narrow the search.

    Returns:
        Path to the session directory, or None if not found.
    """
    if not AMPLIFIER_PROJECTS_DIR.exists():
        return None

    # If cwd provided, check that project first
    if cwd:
        encoded_path = encode_project_path(cwd)
        project_dir = AMPLIFIER_PROJECTS_DIR / encoded_path
        session_dir = project_dir / "sessions" / session_id
        if session_dir.exists():
            return session_dir

    # Search all projects
    for project_dir in AMPLIFIER_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        session_dir = project_dir / "sessions" / session_id
        if session_dir.exists():
            return session_dir

    return None


def _get_project_dirs(cwd: str | None) -> list[tuple[Path, str]]:
    """Get list of project directories to scan.

    Args:
        cwd: Optional working directory to filter to

    Returns:
        List of (project_dir, decoded_cwd) tuples
    """
    project_dirs: list[tuple[Path, str]] = []

    if cwd:
        # Only scan the specific project directory
        encoded_path = encode_project_path(cwd)
        project_dir = AMPLIFIER_PROJECTS_DIR / encoded_path
        if project_dir.exists():
            project_dirs.append((project_dir, cwd))
    else:
        # Scan all project directories
        for project_dir in AMPLIFIER_PROJECTS_DIR.iterdir():
            if project_dir.is_dir():
                decoded_cwd = decode_project_path(project_dir.name)
                project_dirs.append((project_dir, decoded_cwd))

    return project_dirs


def _load_session_metadata(session_dir: Path, project_cwd: str) -> dict[str, Any] | None:
    """Load session metadata from a session directory.

    Args:
        session_dir: Path to the session directory
        project_cwd: Working directory for the project

    Returns:
        Session metadata dict or None if failed to load
    """
    metadata_file = session_dir / "metadata.json"

    if not metadata_file.exists():
        # Construct minimal metadata from directory name
        session_id = session_dir.name
        # Check if it's a child session (contains agent name after _)
        is_child = "_" in session_id and "-" in session_id

        return {
            "session_id": session_id,
            "cwd": project_cwd,
            "name": None,
            "created": None,
            "updated": None,
            "turn_count": 0,
            "state": "unknown",
            "bundle": None,
            "is_child": is_child,
        }

    try:
        with open(metadata_file) as f:
            metadata = json.load(f)

        session_id = metadata.get("session_id", session_dir.name)

        # Check if it's a child session
        is_child = (
            metadata.get("parent_session_id") is not None
            or metadata.get("parent_id") is not None
            or ("_" in session_id and "-" in session_id)
        )

        return {
            "session_id": session_id,
            "cwd": metadata.get("cwd", project_cwd),
            "name": metadata.get("name"),
            "created": metadata.get("created"),
            "updated": metadata.get("updated"),
            "turn_count": metadata.get("turn_count", 0),
            "state": metadata.get("state", "unknown"),
            "bundle": metadata.get("bundle"),
            "is_child": is_child,
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read session metadata {metadata_file}: {e}")
        return None


def _session_sort_key(session: dict[str, Any]) -> str:
    """Get sort key for a session (by updated/created time).

    Args:
        session: Session metadata dict

    Returns:
        ISO datetime string for sorting (empty string if no date)
    """
    updated = session.get("updated")
    if updated:
        return updated
    created = session.get("created")
    if created:
        return created
    return ""
