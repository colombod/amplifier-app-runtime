"""Tests for SessionStore - aligned with app-cli storage format."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from amplifier_server_app.session_store import SessionStore, is_top_level_session

if TYPE_CHECKING:
    pass


class TestIsTopLevelSession:
    """Tests for is_top_level_session helper."""

    def test_top_level_session(self) -> None:
        """Top-level sessions have no underscore (UUIDs)."""
        # Standard UUID format (no underscores)
        assert is_top_level_session("abc123")
        assert is_top_level_session("550e8400e29b41d4a716446655440000")
        # Custom format with dashes (still no underscore)
        assert is_top_level_session("session-with-dashes")

    def test_sub_session(self) -> None:
        """Sub-sessions have underscore separating parent from agent name."""
        assert not is_top_level_session("parent_explorer")
        assert not is_top_level_session("abc123_zen-architect")
        assert not is_top_level_session("a_b_c")


class TestSessionStore:
    """Tests for SessionStore persistence."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SessionStore:
        """Create a SessionStore with a temp directory."""
        return SessionStore(storage_dir=tmp_path / "sessions")

    def test_save_and_load_session(self, store: SessionStore) -> None:
        """Can save and load a complete session."""
        transcript = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        metadata = {"bundle": "test-bundle", "model": "test-model"}

        store.save("test123", transcript, metadata)
        loaded_transcript, loaded_metadata = store.load("test123")

        assert len(loaded_transcript) == 2
        assert loaded_transcript[0]["content"] == "Hello"
        assert loaded_metadata["bundle"] == "test-bundle"

    def test_save_metadata(self, store: SessionStore) -> None:
        """Can save session metadata."""
        store.save_metadata(
            "test456",
            bundle_name="my-bundle",
            turn_count=5,
            state="active",
        )

        metadata = store.load_metadata("test456")
        assert metadata is not None
        assert metadata["bundle"] == "my-bundle"
        assert metadata["turn_count"] == 5
        assert metadata["state"] == "active"

    def test_save_metadata_with_datetime(self, store: SessionStore) -> None:
        """Metadata handles datetime objects."""
        now = datetime.now(UTC)
        store.save_metadata(
            "testdt",
            created_at=now,
            updated_at=now,
        )

        metadata = store.load_metadata("testdt")
        assert metadata is not None
        assert "created" in metadata
        assert "updated" in metadata

    def test_save_metadata_with_string_dates(self, store: SessionStore) -> None:
        """Metadata handles ISO string dates."""
        created = "2025-01-15T10:00:00+00:00"
        store.save_metadata(
            "teststr",
            created_at=created,
        )

        metadata = store.load_metadata("teststr")
        assert metadata is not None
        assert metadata["created"] == created

    def test_load_nonexistent_metadata(self, store: SessionStore) -> None:
        """Loading nonexistent metadata returns None."""
        assert store.load_metadata("nonexistent") is None

    def test_update_metadata(self, store: SessionStore) -> None:
        """Can update specific metadata fields."""
        store.save_metadata("testupdate", state="active", turn_count=1)

        success = store.update_metadata("testupdate", state="completed", turn_count=5)
        assert success

        metadata = store.load_metadata("testupdate")
        assert metadata is not None
        assert metadata["state"] == "completed"
        assert metadata["turn_count"] == 5

    def test_update_nonexistent_metadata(self, store: SessionStore) -> None:
        """Updating nonexistent metadata returns False."""
        assert not store.update_metadata("nonexistent", state="completed")

    def test_save_and_load_transcript(self, store: SessionStore) -> None:
        """Can save and load transcript separately."""
        messages = [
            {"role": "user", "content": "Question?"},
            {"role": "assistant", "content": "Answer!"},
        ]

        store.save_transcript("testtrans", messages)
        loaded = store.load_transcript("testtrans")

        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[1]["role"] == "assistant"

    def test_transcript_filters_system_messages(self, store: SessionStore) -> None:
        """Transcript filters out system/developer messages."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "developer", "content": "Developer context"},
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant response"},
        ]

        store.save_transcript("testfilter", messages)
        loaded = store.load_transcript("testfilter")

        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[1]["role"] == "assistant"

    def test_transcript_adds_timestamps(self, store: SessionStore) -> None:
        """Transcript adds timestamps to messages."""
        messages = [{"role": "user", "content": "Hello"}]

        store.save_transcript("testts", messages)
        loaded = store.load_transcript("testts")

        assert len(loaded) == 1
        assert "timestamp" in loaded[0]

    def test_append_message(self, store: SessionStore) -> None:
        """Can append individual messages to transcript."""
        store.save_transcript("testappend", [{"role": "user", "content": "First"}])
        store.append_message("testappend", {"role": "assistant", "content": "Second"})

        loaded = store.load_transcript("testappend")
        assert len(loaded) == 2
        assert loaded[1]["content"] == "Second"

    def test_append_skips_system_messages(self, store: SessionStore) -> None:
        """Append skips system/developer messages."""
        store.save_transcript("testappskip", [{"role": "user", "content": "First"}])
        store.append_message("testappskip", {"role": "system", "content": "System"})

        loaded = store.load_transcript("testappskip")
        assert len(loaded) == 1

    def test_list_sessions(self, store: SessionStore) -> None:
        """Can list all sessions."""
        store.save_metadata("abc123", turn_count=3)
        store.save_metadata("def456", turn_count=5)
        store.save_metadata("ghi789", turn_count=1)

        sessions = store.list_sessions(min_turns=0)
        assert len(sessions) == 3

        # Should be sorted by updated descending
        ids = [s["session_id"] for s in sessions]
        assert set(ids) == {"abc123", "def456", "ghi789"}

    def test_list_sessions_min_turns_filter(self, store: SessionStore) -> None:
        """List filters by minimum turn count."""
        store.save_metadata("highturns", turn_count=10)
        store.save_metadata("lowturns", turn_count=1)
        store.save_metadata("noturns", turn_count=0)

        sessions = store.list_sessions(min_turns=5)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "highturns"

    def test_list_sessions_top_level_filter(self, store: SessionStore) -> None:
        """List filters out sub-sessions by default."""
        store.save_metadata("parent1", turn_count=3)
        store.save_metadata("parent1_explorer", turn_count=2)  # Sub-session
        store.save_metadata("another", turn_count=1)

        # Default: top_level_only=True
        sessions = store.list_sessions(min_turns=0)
        ids = [s["session_id"] for s in sessions]
        assert "parent1" in ids
        assert "another" in ids
        assert "parent1_explorer" not in ids

        # With top_level_only=False
        all_sessions = store.list_sessions(top_level_only=False, min_turns=0)
        all_ids = [s["session_id"] for s in all_sessions]
        assert "parent1_explorer" in all_ids

    def test_list_sessions_limit(self, store: SessionStore) -> None:
        """List respects limit parameter."""
        for i in range(10):
            store.save_metadata(f"session{i:03d}", turn_count=1)

        sessions = store.list_sessions(limit=3, min_turns=0)
        assert len(sessions) == 3

    def test_list_sessions_state_filter(self, store: SessionStore) -> None:
        """List filters by state."""
        store.save_metadata("active1", state="ready", turn_count=1)
        store.save_metadata("active2", state="ready", turn_count=1)
        store.save_metadata("completed1", state="completed", turn_count=1)

        ready = store.list_sessions(state="ready", min_turns=0)
        assert len(ready) == 2

        completed = store.list_sessions(state="completed", min_turns=0)
        assert len(completed) == 1

    def test_delete_session(self, store: SessionStore) -> None:
        """Can delete a session."""
        store.save_metadata("todelete", turn_count=1)
        assert store.session_exists("todelete")

        result = store.delete_session("todelete")
        assert result
        assert not store.session_exists("todelete")

    def test_delete_nonexistent_session(self, store: SessionStore) -> None:
        """Deleting nonexistent session returns False."""
        assert not store.delete_session("nonexistent")

    def test_delete_all_sessions(self, store: SessionStore) -> None:
        """Can delete all sessions with confirmation."""
        store.save_metadata("session1", turn_count=1)
        store.save_metadata("session2", turn_count=1)
        store.save_metadata("session3", turn_count=1)

        count = store.delete_all_sessions(confirm=True)
        assert count == 3
        assert len(store.list_sessions(min_turns=0)) == 0

    def test_delete_all_requires_confirm(self, store: SessionStore) -> None:
        """Delete all requires confirm=True."""
        store.save_metadata("session1", turn_count=1)

        with pytest.raises(ValueError, match="confirm=True"):
            store.delete_all_sessions()

    def test_session_exists(self, store: SessionStore) -> None:
        """Can check if session exists."""
        assert not store.session_exists("nonexistent")

        store.save_metadata("exists", turn_count=1)
        assert store.session_exists("exists")

    def test_get_session_summary(self, store: SessionStore) -> None:
        """Can get session summary with transcript preview."""
        store.save_metadata("testsummary", bundle_name="test", turn_count=2)
        store.save_transcript(
            "testsummary",
            [
                {"role": "user", "content": "What is Python?"},
                {"role": "assistant", "content": "Python is a programming language."},
            ],
        )

        summary = store.get_session_summary("testsummary")
        assert summary is not None
        assert summary["bundle"] == "test"
        assert summary["message_count"] == 2
        assert "Python" in summary["first_user_message"]
        assert "programming" in summary["last_assistant_message"]

    def test_get_nonexistent_summary(self, store: SessionStore) -> None:
        """Getting nonexistent summary returns None."""
        assert store.get_session_summary("nonexistent") is None

    def test_find_session_exact_match(self, store: SessionStore) -> None:
        """find_session returns exact match."""
        store.save_metadata("abc123def456", turn_count=1)

        found = store.find_session("abc123def456")
        assert found == "abc123def456"

    def test_find_session_prefix_match(self, store: SessionStore) -> None:
        """find_session returns prefix match."""
        store.save_metadata("abc123def456", turn_count=1)

        found = store.find_session("abc123")
        assert found == "abc123def456"

    def test_find_session_not_found(self, store: SessionStore) -> None:
        """find_session raises if not found."""
        with pytest.raises(FileNotFoundError):
            store.find_session("nonexistent")

    def test_find_session_ambiguous(self, store: SessionStore) -> None:
        """find_session raises if ambiguous."""
        store.save_metadata("abc123first", turn_count=1)
        store.save_metadata("abc123second", turn_count=1)

        with pytest.raises(ValueError, match="Ambiguous"):
            store.find_session("abc123")

    def test_turn_count_recalculated_from_transcript(self, store: SessionStore) -> None:
        """Turn count is recalculated from transcript on load."""
        # Save with turn_count=0
        store.save_metadata("testrecalc", turn_count=0)
        # Save transcript with 3 user messages
        store.save_transcript(
            "testrecalc",
            [
                {"role": "user", "content": "One"},
                {"role": "assistant", "content": "Response 1"},
                {"role": "user", "content": "Two"},
                {"role": "assistant", "content": "Response 2"},
                {"role": "user", "content": "Three"},
            ],
        )

        metadata = store.load_metadata("testrecalc")
        assert metadata is not None
        assert metadata["turn_count"] == 3

    def test_transcript_is_jsonl_format(self, store: SessionStore) -> None:
        """Transcript is stored as JSONL (one JSON object per line)."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "World"},
        ]
        store.save_transcript("testjsonl", messages)

        # Read raw file
        transcript_path = store._transcript_path("testjsonl")
        content = transcript_path.read_text()
        lines = [line for line in content.strip().split("\n") if line]

        assert len(lines) == 2
        # Each line should be valid JSON
        for line in lines:
            json.loads(line)

    def test_unicode_in_transcript(self, store: SessionStore) -> None:
        """Transcript handles unicode properly."""
        messages = [
            {"role": "user", "content": "Hello 世界 🌍"},
            {"role": "assistant", "content": "Привет мир 🚀"},
        ]
        store.save_transcript("testunicode", messages)
        loaded = store.load_transcript("testunicode")

        assert loaded[0]["content"] == "Hello 世界 🌍"
        assert loaded[1]["content"] == "Привет мир 🚀"

    def test_list_session_ids(self, store: SessionStore) -> None:
        """list_session_ids returns just IDs for app-cli compatibility."""
        store.save_metadata("first", turn_count=1)
        store.save_metadata("second", turn_count=1)

        ids = store.list_session_ids()
        assert isinstance(ids, list)
        assert all(isinstance(sid, str) for sid in ids)
        assert set(ids) == {"first", "second"}
