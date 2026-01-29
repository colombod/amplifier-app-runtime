"""
Session persistence management for Amplifier Server App.

Aligned with amplifier-app-cli for consistent session storage.

Storage location: ~/.amplifier/projects/<project-slug>/sessions/<session-id>/
Files created: transcript.jsonl, metadata.json
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .project_utils import get_project_slug

logger = logging.getLogger(__name__)


def is_top_level_session(session_id: str) -> bool:
    """Check if a session ID is a top-level (main) session.

    Spawned sub-sessions have IDs in the format: {parent_id}_{agent_name}
    Top-level sessions are just UUIDs without underscores.

    Args:
        session_id: Session ID to check

    Returns:
        True if this is a top-level session, False if spawned
    """
    return "_" not in session_id


class SessionStore:
    """
    Manages session persistence to filesystem.

    Aligned with amplifier-app-cli storage format for cross-app compatibility.

    Contract:
    - Inputs: session_id (str), transcript (list), metadata (dict)
    - Outputs: Saved files or loaded data tuples
    - Side Effects: Filesystem writes to ~/.amplifier/projects/<project-slug>/sessions/<session-id>/
    - Errors: FileNotFoundError for missing sessions, IOError for disk issues
    - Files created: transcript.jsonl, metadata.json
    """

    def __init__(self, storage_dir: Path | None = None):
        """Initialize with base directory for sessions.

        Args:
            storage_dir: Base directory for session storage.
                        Defaults to ~/.amplifier/projects/<project-slug>/sessions/
        """
        if storage_dir is None:
            project_slug = get_project_slug()
            storage_dir = Path.home() / ".amplifier" / "projects" / project_slug / "sessions"
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        """Get the directory path for a session."""
        return self.storage_dir / session_id

    def _metadata_path(self, session_id: str) -> Path:
        """Get the metadata file path for a session."""
        return self._session_dir(session_id) / "metadata.json"

    def _transcript_path(self, session_id: str) -> Path:
        """Get the transcript file path for a session."""
        return self._session_dir(session_id) / "transcript.jsonl"

    # =========================================================================
    # Core save/load methods (aligned with app-cli)
    # =========================================================================

    def save(self, session_id: str, transcript: list, metadata: dict) -> None:
        """Save session state atomically.

        Args:
            session_id: Unique session identifier
            transcript: List of message objects for the session
            metadata: Session metadata dictionary

        Raises:
            ValueError: If session_id is empty or invalid
            IOError: If unable to write files
        """
        if not session_id or not session_id.strip():
            raise ValueError("session_id cannot be empty")

        # Sanitize session_id to prevent path traversal
        if "/" in session_id or "\\" in session_id or session_id in (".", ".."):
            raise ValueError(f"Invalid session_id: {session_id}")

        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save transcript
        self._save_transcript(session_id, transcript)

        # Save metadata
        self._save_metadata_dict(session_dir, metadata)

        logger.debug(f"Session {session_id} saved successfully")

    def load(self, session_id: str) -> tuple[list, dict]:
        """Load session state.

        Args:
            session_id: Session identifier to load

        Returns:
            Tuple of (transcript, metadata)

        Raises:
            FileNotFoundError: If session does not exist
            ValueError: If session_id is invalid
        """
        if not session_id or not session_id.strip():
            raise ValueError("session_id cannot be empty")

        # Sanitize session_id
        if "/" in session_id or "\\" in session_id or session_id in (".", ".."):
            raise ValueError(f"Invalid session_id: {session_id}")

        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            raise FileNotFoundError(f"Session '{session_id}' not found")

        # Load transcript
        transcript = self.load_transcript(session_id)

        # Load metadata
        metadata = self.load_metadata(session_id) or {}

        logger.debug(f"Session {session_id} loaded successfully")
        return transcript, metadata

    # =========================================================================
    # Metadata methods
    # =========================================================================

    def save_metadata(
        self,
        session_id: str,
        bundle_name: str | None = None,
        turn_count: int = 0,
        created_at: datetime | str | None = None,
        updated_at: datetime | str | None = None,
        name: str | None = None,
        cwd: str | None = None,
        parent_session_id: str | None = None,
        state: str = "active",
        error: str | None = None,
        **extra: Any,
    ) -> None:
        """Save session metadata to storage.

        Args:
            session_id: Unique session identifier
            bundle_name: Name of the bundle used
            turn_count: Number of conversation turns
            created_at: Session creation time (defaults to now)
            updated_at: Last update time (defaults to now)
            name: Optional human-readable session name
            cwd: Working directory for the session
            parent_session_id: Parent session if this is a sub-session
            state: Session state (active, completed, error, etc.)
            error: Error message if state is error
            **extra: Additional metadata fields
        """
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)

        # Handle datetime or string for created_at/updated_at
        def to_iso(val: datetime | str | None, default: datetime) -> str:
            if val is None:
                return default.isoformat()
            if isinstance(val, str):
                return val
            return val.isoformat()

        metadata = {
            "session_id": session_id,
            "bundle": bundle_name,  # Use "bundle" to match app-cli format
            "turn_count": turn_count,
            "created": to_iso(created_at, now),  # Use "created" to match app-cli
            "updated": to_iso(updated_at, now),  # Use "updated" to match app-cli
            "name": name,
            "cwd": cwd,
            "parent_session_id": parent_session_id,
            "state": state,
            "error": error,
            **extra,
        }

        self._save_metadata_dict(session_dir, metadata)

    def _save_metadata_dict(self, session_dir: Path, metadata: dict) -> None:
        """Save metadata dictionary to file."""
        metadata_file = session_dir / "metadata.json"
        content = json.dumps(metadata, indent=2, ensure_ascii=False)
        metadata_file.write_text(content, encoding="utf-8")

    def load_metadata(self, session_id: str) -> dict | None:
        """Load session metadata from storage.

        Args:
            session_id: Session identifier to load

        Returns:
            Metadata dictionary or None if not found
        """
        metadata_path = self._metadata_path(session_id)
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, encoding="utf-8") as f:
                data = json.load(f)

            # Recalculate turn count from transcript if needed
            transcript = self.load_transcript(session_id)
            if transcript:
                user_turns = sum(1 for m in transcript if m.get("role") == "user")
                if user_turns > data.get("turn_count", 0):
                    data["turn_count"] = user_turns

            return data
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load metadata for {session_id}: {e}")
            return None

    def update_metadata(self, session_id: str, **updates: Any) -> bool:
        """Update specific fields in session metadata.

        Args:
            session_id: Session identifier
            **updates: Fields to update

        Returns:
            True if update succeeded, False if session not found
        """
        metadata = self.load_metadata(session_id)
        if metadata is None:
            return False

        metadata.update(updates)
        metadata["updated"] = datetime.now(UTC).isoformat()

        session_dir = self._session_dir(session_id)
        self._save_metadata_dict(session_dir, metadata)
        return True

    def get_metadata(self, session_id: str) -> dict:
        """Get session metadata (alias for load_metadata with exception on not found)."""
        metadata = self.load_metadata(session_id)
        if metadata is None:
            raise FileNotFoundError(f"Session '{session_id}' not found")
        return metadata

    # =========================================================================
    # Transcript methods
    # =========================================================================

    def save_transcript(self, session_id: str, messages: list[dict]) -> None:
        """Save conversation transcript to storage.

        Args:
            session_id: Session identifier
            messages: List of message dictionaries
        """
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        transcript_path = self._transcript_path(session_id)

        # Build JSONL content (filter to user/assistant only)
        lines = []
        for message in messages:
            msg_dict = message if isinstance(message, dict) else message.model_dump()

            # Skip system and developer role messages
            if msg_dict.get("role") in ("system", "developer"):
                continue

            # Add timestamp if not present
            if "timestamp" not in msg_dict:
                msg_dict["timestamp"] = datetime.now(UTC).isoformat(timespec="milliseconds")

            lines.append(json.dumps(msg_dict, ensure_ascii=False))

        content = "\n".join(lines) + "\n" if lines else ""
        transcript_path.write_text(content, encoding="utf-8")

    def _save_transcript(self, session_id: str, transcript: list) -> None:
        """Internal method to save transcript (called by save())."""
        self.save_transcript(session_id, transcript)

    def load_transcript(self, session_id: str) -> list[dict]:
        """Load conversation transcript from storage.

        Args:
            session_id: Session identifier

        Returns:
            List of message dictionaries (empty if not found)
        """
        transcript_path = self._transcript_path(session_id)
        if not transcript_path.exists():
            return []

        try:
            messages = []
            with open(transcript_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        messages.append(json.loads(line))
            return messages
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load transcript for {session_id}: {e}")
            return []

    def append_message(self, session_id: str, message: dict) -> None:
        """Append a single message to the transcript.

        Args:
            session_id: Session identifier
            message: Message dictionary to append
        """
        # Skip system/developer messages
        if message.get("role") in ("system", "developer"):
            return

        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        transcript_path = self._transcript_path(session_id)

        # Add timestamp if not present
        if "timestamp" not in message:
            message["timestamp"] = datetime.now(UTC).isoformat(timespec="milliseconds")

        line = json.dumps(message, ensure_ascii=False) + "\n"

        with open(transcript_path, "a", encoding="utf-8") as f:
            f.write(line)

    # =========================================================================
    # Listing and querying methods
    # =========================================================================

    def list_sessions(
        self,
        *,
        top_level_only: bool = True,
        limit: int = 100,
        min_turns: int = 1,
        state: str | None = None,
    ) -> list[dict]:
        """List sessions with metadata.

        Args:
            top_level_only: If True, exclude spawned sub-sessions
            limit: Maximum number of sessions to return
            min_turns: Minimum turn count filter
            state: Filter by session state

        Returns:
            List of session metadata dictionaries, sorted by updated_at descending
        """
        if not self.storage_dir.exists():
            return []

        sessions = []
        for session_dir in self.storage_dir.iterdir():
            if not session_dir.is_dir() or session_dir.name.startswith("."):
                continue

            session_id = session_dir.name

            # Filter to top-level sessions if requested
            if top_level_only and not is_top_level_session(session_id):
                continue

            # Load metadata
            metadata = self.load_metadata(session_id)
            if metadata is None:
                continue

            # Apply filters
            if metadata.get("turn_count", 0) < min_turns:
                continue

            if state is not None and metadata.get("state") != state:
                continue

            sessions.append(metadata)

        # Sort by updated time descending
        sessions.sort(key=lambda x: x.get("updated", x.get("created", "")), reverse=True)

        return sessions[:limit]

    def list_session_ids(self, *, top_level_only: bool = True) -> list[str]:
        """List session IDs (for compatibility with app-cli).

        Args:
            top_level_only: If True, exclude spawned sub-sessions

        Returns:
            List of session IDs, sorted by modification time (newest first)
        """
        if not self.storage_dir.exists():
            return []

        sessions = []
        for session_dir in self.storage_dir.iterdir():
            if session_dir.is_dir() and not session_dir.name.startswith("."):
                session_name = session_dir.name

                # Filter to top-level sessions if requested
                if top_level_only and not is_top_level_session(session_name):
                    continue

                # Include session with its modification time for sorting
                try:
                    mtime = session_dir.stat().st_mtime
                    sessions.append((session_name, mtime))
                except Exception:
                    sessions.append((session_name, 0))

        # Sort by modification time (newest first) and return just the names
        sessions.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in sessions]

    def find_session(self, partial_id: str, *, top_level_only: bool = True) -> str:
        """Find session by partial ID prefix.

        Args:
            partial_id: Partial session ID (prefix match)
            top_level_only: If True, only match top-level sessions

        Returns:
            Full session ID if exactly one match

        Raises:
            FileNotFoundError: If no sessions match
            ValueError: If multiple sessions match (ambiguous)
        """
        if not partial_id or not partial_id.strip():
            raise ValueError("Session ID cannot be empty")

        partial_id = partial_id.strip()

        # Check for exact match first
        if self.session_exists(partial_id) and (
            not top_level_only or is_top_level_session(partial_id)
        ):
            return partial_id

        # Find prefix matches
        matches = [
            sid
            for sid in self.list_session_ids(top_level_only=top_level_only)
            if sid.startswith(partial_id)
        ]

        if not matches:
            raise FileNotFoundError(f"No session found matching '{partial_id}'")
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous session ID '{partial_id}' matches {len(matches)} sessions: "
                f"{', '.join(m[:12] + '...' for m in matches[:3])}"
                + (f" and {len(matches) - 3} more" if len(matches) > 3 else "")
            )
        return matches[0]

    # =========================================================================
    # Session operations
    # =========================================================================

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists.

        Args:
            session_id: Session identifier to check

        Returns:
            True if session exists, False otherwise
        """
        if not session_id or "/" in session_id or "\\" in session_id:
            return False

        session_dir = self._session_dir(session_id)
        return session_dir.exists() and session_dir.is_dir()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session identifier to delete

        Returns:
            True if deleted, False if not found
        """
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return False

        shutil.rmtree(session_dir)
        logger.info(f"Deleted session: {session_id}")
        return True

    def delete_all_sessions(self, *, confirm: bool = False) -> int:
        """Delete all sessions.

        Args:
            confirm: Must be True to proceed (safety check)

        Returns:
            Number of sessions deleted

        Raises:
            ValueError: If confirm is not True
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to delete all sessions")

        count = 0
        for session_dir in self.storage_dir.iterdir():
            if session_dir.is_dir() and not session_dir.name.startswith("."):
                shutil.rmtree(session_dir)
                count += 1

        logger.info(f"Deleted {count} sessions")
        return count

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Remove sessions older than specified days.

        Args:
            days: Number of days to keep sessions (default 30)

        Returns:
            Number of sessions removed
        """
        if days < 0:
            raise ValueError("days must be non-negative")

        if not self.storage_dir.exists():
            return 0

        from datetime import timedelta

        cutoff_time = datetime.now(UTC) - timedelta(days=days)
        cutoff_timestamp = cutoff_time.timestamp()

        removed = 0
        for session_dir in self.storage_dir.iterdir():
            if not session_dir.is_dir() or session_dir.name.startswith("."):
                continue

            try:
                mtime = session_dir.stat().st_mtime
                if mtime < cutoff_timestamp:
                    shutil.rmtree(session_dir)
                    logger.info(f"Removed old session: {session_dir.name}")
                    removed += 1
            except Exception as e:
                logger.error(f"Failed to remove session {session_dir.name}: {e}")

        return removed

    def get_session_summary(self, session_id: str) -> dict | None:
        """Get a summary of a session including transcript preview.

        Args:
            session_id: Session identifier

        Returns:
            Summary dictionary or None if not found
        """
        metadata = self.load_metadata(session_id)
        if metadata is None:
            return None

        transcript = self.load_transcript(session_id)

        # Find first user message and last assistant message
        first_user = None
        last_assistant = None
        for msg in transcript:
            if msg.get("role") == "user" and first_user is None:
                first_user = msg.get("content", "")[:100]
            if msg.get("role") == "assistant":
                last_assistant = msg.get("content", "")[:100]

        return {
            **metadata,
            "message_count": len(transcript),
            "first_user_message": first_user or "",
            "last_assistant_message": last_assistant or "",
        }
