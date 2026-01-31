"""Tests for ACP session discovery and management.

Tests the session listing and resume functionality that discovers
sessions from Amplifier's filesystem storage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from amplifier_app_runtime.acp.agent import (
    _decode_project_path,
    _encode_project_path,
    discover_sessions,
    find_session_directory,
)


class TestProjectPathEncoding:
    """Tests for project path encoding/decoding."""

    def test_encode_unix_path(self) -> None:
        """Unix absolute paths encode correctly."""
        assert _encode_project_path("/home/user/project") == "-home-user-project"
        assert _encode_project_path("/var/data/app") == "-var-data-app"

    def test_encode_root_path(self) -> None:
        """Root path encodes to single dash."""
        assert _encode_project_path("/") == "-"

    def test_encode_relative_path(self) -> None:
        """Relative paths get leading dash added."""
        # Relative paths should still work
        result = _encode_project_path("relative/path")
        assert result.startswith("-")
        assert "relative" in result

    def test_decode_unix_path(self) -> None:
        """Encoded paths decode back to original."""
        assert _decode_project_path("-home-user-project") == "/home/user/project"
        assert _decode_project_path("-var-data-app") == "/var/data/app"

    def test_encode_decode_roundtrip(self) -> None:
        """Encoding then decoding returns original path."""
        paths = [
            "/home/user/project",
            "/var/data/app",
            "/tmp/test",
        ]
        for path in paths:
            encoded = _encode_project_path(path)
            decoded = _decode_project_path(encoded)
            assert decoded == path, f"Roundtrip failed for {path}"


class TestDiscoverSessions:
    """Tests for session discovery from filesystem."""

    @pytest.fixture
    def mock_projects_dir(self, tmp_path: Path) -> Path:
        """Create a mock Amplifier projects directory structure."""
        projects_dir = tmp_path / ".amplifier" / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir

    def _create_session(
        self,
        projects_dir: Path,
        project_path: str,
        session_id: str,
        metadata: dict | None = None,
        events: list[dict] | None = None,
    ) -> Path:
        """Helper to create a mock session directory."""
        encoded = _encode_project_path(project_path)
        session_dir = projects_dir / encoded / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        if metadata:
            with open(session_dir / "metadata.json", "w") as f:
                json.dump(metadata, f)

        if events:
            with open(session_dir / "events.jsonl", "w") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")

        return session_dir

    @pytest.mark.asyncio
    async def test_discover_no_projects_dir(self, tmp_path: Path) -> None:
        """Returns empty list when projects directory doesn't exist."""
        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            tmp_path / "nonexistent",
        ):
            sessions = await discover_sessions()
            assert sessions == []

    @pytest.mark.asyncio
    async def test_discover_empty_projects(self, mock_projects_dir: Path) -> None:
        """Returns empty list when no sessions exist."""
        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            sessions = await discover_sessions()
            assert sessions == []

    @pytest.mark.asyncio
    async def test_discover_session_with_metadata(self, mock_projects_dir: Path) -> None:
        """Discovers sessions with metadata.json."""
        now = datetime.now(UTC).isoformat()
        self._create_session(
            mock_projects_dir,
            "/home/user/project",
            "sess_abc123",
            metadata={
                "session_id": "sess_abc123",
                "bundle": "foundation",
                "turn_count": 5,
                "created": now,
                "updated": now,
                "name": "Test Session",
                "cwd": "/home/user/project",
                "state": "ready",
            },
        )

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            sessions = await discover_sessions()

        assert len(sessions) == 1
        session = sessions[0]
        assert session["session_id"] == "sess_abc123"
        assert session["bundle"] == "foundation"
        assert session["turn_count"] == 5
        assert session["name"] == "Test Session"
        assert session["state"] == "ready"
        assert session["is_child"] is False

    @pytest.mark.asyncio
    async def test_discover_session_without_metadata(self, mock_projects_dir: Path) -> None:
        """Discovers sessions even without metadata.json."""
        session_dir = mock_projects_dir / "-home-user-project" / "sessions" / "sess_minimal"
        session_dir.mkdir(parents=True)

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            sessions = await discover_sessions()

        assert len(sessions) == 1
        session = sessions[0]
        assert session["session_id"] == "sess_minimal"
        assert session["bundle"] is None
        assert session["state"] == "unknown"

    @pytest.mark.asyncio
    async def test_discover_child_sessions_marked(self, mock_projects_dir: Path) -> None:
        """Child sessions are correctly identified."""
        # Parent session
        self._create_session(
            mock_projects_dir,
            "/home/user/project",
            "parent_abc123",
            metadata={
                "session_id": "parent_abc123",
                "bundle": "foundation",
            },
        )

        # Child session (naming pattern: parent-child_agentname)
        self._create_session(
            mock_projects_dir,
            "/home/user/project",
            "parent_abc123-child456_explorer",
            metadata={
                "session_id": "parent_abc123-child456_explorer",
                "parent_id": "parent_abc123",
                "bundle": "foundation",
            },
        )

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            sessions = await discover_sessions()

        # Find parent and child
        parent = next((s for s in sessions if s["session_id"] == "parent_abc123"), None)
        child = next(
            (s for s in sessions if s["session_id"] == "parent_abc123-child456_explorer"),
            None,
        )

        assert parent is not None
        assert parent["is_child"] is False

        assert child is not None
        assert child["is_child"] is True

    @pytest.mark.asyncio
    async def test_discover_filters_by_cwd(self, mock_projects_dir: Path) -> None:
        """Session discovery can be filtered by working directory."""
        # Session in project A
        self._create_session(
            mock_projects_dir,
            "/home/user/project-a",
            "sess_a",
            metadata={"session_id": "sess_a"},
        )

        # Session in project B
        self._create_session(
            mock_projects_dir,
            "/home/user/project-b",
            "sess_b",
            metadata={"session_id": "sess_b"},
        )

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            # Filter to project A only
            sessions = await discover_sessions(cwd="/home/user/project-a")

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess_a"

    @pytest.mark.asyncio
    async def test_discover_respects_limit(self, mock_projects_dir: Path) -> None:
        """Session discovery respects the limit parameter."""
        # Create multiple sessions
        for i in range(10):
            self._create_session(
                mock_projects_dir,
                "/home/user/project",
                f"sess_{i:03d}",
                metadata={
                    "session_id": f"sess_{i:03d}",
                    "updated": f"2025-01-{(i + 1):02d}T00:00:00Z",
                },
            )

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            sessions = await discover_sessions(limit=5)

        assert len(sessions) == 5

    @pytest.mark.asyncio
    async def test_discover_sorts_by_updated(self, mock_projects_dir: Path) -> None:
        """Sessions are sorted by updated time (most recent first)."""
        self._create_session(
            mock_projects_dir,
            "/home/user/project",
            "sess_old",
            metadata={
                "session_id": "sess_old",
                "updated": "2025-01-01T00:00:00Z",
            },
        )
        self._create_session(
            mock_projects_dir,
            "/home/user/project",
            "sess_new",
            metadata={
                "session_id": "sess_new",
                "updated": "2025-01-15T00:00:00Z",
            },
        )

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            sessions = await discover_sessions()

        assert len(sessions) == 2
        # Most recent first
        assert sessions[0]["session_id"] == "sess_new"
        assert sessions[1]["session_id"] == "sess_old"


class TestFindSessionDirectory:
    """Tests for finding a specific session directory."""

    @pytest.fixture
    def mock_projects_dir(self, tmp_path: Path) -> Path:
        """Create a mock Amplifier projects directory structure."""
        projects_dir = tmp_path / ".amplifier" / "projects"
        projects_dir.mkdir(parents=True)
        return projects_dir

    def test_find_nonexistent_session(self, mock_projects_dir: Path) -> None:
        """Returns None for sessions that don't exist."""
        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            result = find_session_directory("nonexistent_session")
            assert result is None

    def test_find_session_with_cwd_hint(self, mock_projects_dir: Path) -> None:
        """Finds session when cwd hint is provided."""
        encoded = _encode_project_path("/home/user/project")
        session_dir = mock_projects_dir / encoded / "sessions" / "sess_target"
        session_dir.mkdir(parents=True)

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            result = find_session_directory("sess_target", cwd="/home/user/project")

        assert result is not None
        assert result.name == "sess_target"

    def test_find_session_without_cwd_hint(self, mock_projects_dir: Path) -> None:
        """Finds session by searching all projects."""
        encoded = _encode_project_path("/somewhere/else")
        session_dir = mock_projects_dir / encoded / "sessions" / "sess_hidden"
        session_dir.mkdir(parents=True)

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            # No cwd hint - should still find it
            result = find_session_directory("sess_hidden")

        assert result is not None
        assert result.name == "sess_hidden"

    def test_find_session_wrong_cwd_falls_back(self, mock_projects_dir: Path) -> None:
        """Falls back to search all when cwd hint is wrong."""
        # Session is in project-a
        encoded = _encode_project_path("/home/user/project-a")
        session_dir = mock_projects_dir / encoded / "sessions" / "sess_123"
        session_dir.mkdir(parents=True)

        with patch(
            "amplifier_app_runtime.acp.agent.AMPLIFIER_PROJECTS_DIR",
            mock_projects_dir,
        ):
            # Wrong cwd hint - should still find via fallback
            result = find_session_directory("sess_123", cwd="/home/user/project-b")

        assert result is not None
        assert result.name == "sess_123"
