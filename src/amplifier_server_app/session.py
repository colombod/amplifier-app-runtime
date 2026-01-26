"""Session Manager for Amplifier Server.

Manages Amplifier sessions with full lifecycle support:
- Session creation and configuration
- Prompt execution with streaming
- Event forwarding to transport
- Session persistence and resume
- Agent spawning with context

Integrates with amplifier-core's Session and Coordinator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .event_types import ALL_EVENTS
from .protocols import ApprovalSystem, DisplaySystem, SpawnManager, StreamingHook
from .transport.base import Event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Session lifecycle states."""

    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class SessionMetadata:
    """Metadata for a session."""

    session_id: str
    state: SessionState = SessionState.CREATED
    bundle_name: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    turn_count: int = 0
    cwd: str = field(default_factory=lambda: str(Path.cwd()))
    parent_session_id: str | None = None
    error: str | None = None


@dataclass
class SessionConfig:
    """Configuration for session creation."""

    bundle: str | None = None
    provider: str | None = None
    model: str | None = None
    max_turns: int = 100
    timeout: float = 300.0
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)


class ManagedSession:
    """A managed Amplifier session with transport integration.

    Wraps an Amplifier session with:
    - Event streaming via protocols
    - Approval handling
    - Display notifications
    - Agent spawning
    - State management
    """

    def __init__(
        self,
        session_id: str,
        config: SessionConfig,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]] | None = None,
    ):
        self.session_id = session_id
        self.config = config
        self.metadata = SessionMetadata(
            session_id=session_id,
            bundle_name=config.bundle,
            cwd=config.working_directory or str(Path.cwd()),
        )

        # Protocol handlers
        self._send = send_fn
        self.display = DisplaySystem(send_fn)
        self.approval = ApprovalSystem(send_fn)
        self.spawn_manager = SpawnManager(send_fn)
        self.streaming_hook = StreamingHook(send_fn)

        # Internal state
        self._amplifier_session: Any = None  # AmplifierSession when loaded
        self._lock = asyncio.Lock()
        self._cancel_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize the Amplifier session.

        Loads the bundle and prepares the session for execution.
        """
        async with self._lock:
            if self.metadata.state != SessionState.CREATED:
                raise RuntimeError(f"Cannot initialize session in state {self.metadata.state}")

            try:
                # Try to import amplifier-core
                # This is optional - server can run in "mock" mode without it
                try:
                    from amplifier_core import Session as AmplifierSession
                    from amplifier_foundation import load_bundle

                    # Load bundle if specified
                    bundle = None
                    if self.config.bundle:
                        bundle = await load_bundle(self.config.bundle)

                    # Create Amplifier session
                    self._amplifier_session = AmplifierSession(
                        bundle=bundle,
                        cwd=self.config.working_directory,
                    )

                    # Register streaming hook for all events
                    if hasattr(self._amplifier_session, "hook_registry"):
                        for event in ALL_EVENTS:
                            self._amplifier_session.hook_registry.register(
                                event, self.streaming_hook, priority=100
                            )

                    logger.info(f"Session {self.session_id} initialized with amplifier-core")

                except ImportError:
                    # Running without amplifier-core - use mock mode
                    logger.warning(
                        f"Session {self.session_id} running in mock mode "
                        "(amplifier-core not installed)"
                    )
                    self._amplifier_session = None

                self.metadata.state = SessionState.READY
                self.metadata.updated_at = datetime.now()

                # Notify client
                await self._emit_state_change()

            except Exception as e:
                self.metadata.state = SessionState.ERROR
                self.metadata.error = str(e)
                logger.error(f"Failed to initialize session {self.session_id}: {e}")
                raise

    async def execute(self, prompt: str) -> AsyncIterator[Event]:
        """Execute a prompt and stream results.

        Args:
            prompt: The user's prompt

        Yields:
            Events as they occur during execution
        """
        async with self._lock:
            if self.metadata.state not in (SessionState.READY, SessionState.PAUSED):
                raise RuntimeError(f"Cannot execute in state {self.metadata.state}")

            self.metadata.state = SessionState.RUNNING
            self.metadata.turn_count += 1
            self.metadata.updated_at = datetime.now()

        # Emit prompt submit event
        yield Event(
            type="prompt:submit",
            properties={
                "session_id": self.session_id,
                "prompt": prompt,
                "turn": self.metadata.turn_count,
            },
        )

        try:
            if self._amplifier_session:
                # Real execution with amplifier-core
                async for event in self._execute_with_amplifier(prompt):
                    yield event
            else:
                # Mock execution for testing
                async for event in self._execute_mock(prompt):
                    yield event

            # Update state on completion
            async with self._lock:
                self.metadata.state = SessionState.READY
                self.metadata.updated_at = datetime.now()

            # Emit completion event
            yield Event(
                type="prompt:complete",
                properties={
                    "session_id": self.session_id,
                    "turn": self.metadata.turn_count,
                },
            )

        except asyncio.CancelledError:
            async with self._lock:
                self.metadata.state = SessionState.CANCELLED
            yield Event(
                type="cancel:completed",
                properties={"session_id": self.session_id},
            )
            raise

        except Exception as e:
            async with self._lock:
                self.metadata.state = SessionState.ERROR
                self.metadata.error = str(e)

            yield Event(
                type="error",
                properties={
                    "session_id": self.session_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise

    async def _execute_with_amplifier(self, prompt: str) -> AsyncIterator[Event]:
        """Execute prompt using real Amplifier session."""
        # This would integrate with the actual AmplifierSession.run() method
        # For now, we yield a placeholder - full integration requires
        # adapting to amplifier-core's async patterns

        # The streaming_hook is already registered and will forward events
        # via the send_fn, so we just need to run the session

        try:
            # Placeholder for actual execution
            # result = await self._amplifier_session.run(prompt)

            yield Event(
                type="content_block:start",
                properties={
                    "session_id": self.session_id,
                    "block_type": "text",
                    "index": 0,
                },
            )

            # Simulate streaming response
            response = f"[amplifier-core integration pending] Received: {prompt}"
            for chunk in [response[i : i + 10] for i in range(0, len(response), 10)]:
                yield Event(
                    type="content_block:delta",
                    properties={
                        "session_id": self.session_id,
                        "index": 0,
                        "delta": {"text": chunk},
                    },
                )
                await asyncio.sleep(0.05)

            yield Event(
                type="content_block:end",
                properties={
                    "session_id": self.session_id,
                    "index": 0,
                    "block": {"text": response},
                },
            )

        except Exception as e:
            logger.error(f"Execution error: {e}")
            raise

    async def _execute_mock(self, prompt: str) -> AsyncIterator[Event]:
        """Execute prompt in mock mode (without amplifier-core)."""
        yield Event(
            type="content_block:start",
            properties={
                "session_id": self.session_id,
                "block_type": "text",
                "index": 0,
            },
        )

        # Simulate streaming response
        response = f"[Mock mode - amplifier-core not installed]\nReceived prompt: {prompt}"
        for _i, char in enumerate(response):
            if self._cancel_event.is_set():
                break
            yield Event(
                type="content_block:delta",
                properties={
                    "session_id": self.session_id,
                    "index": 0,
                    "delta": {"text": char},
                },
            )
            await asyncio.sleep(0.02)

        yield Event(
            type="content_block:end",
            properties={
                "session_id": self.session_id,
                "index": 0,
                "block": {"text": response},
            },
        )

    async def cancel(self) -> None:
        """Cancel the current execution."""
        self._cancel_event.set()
        self.approval.cancel_all("cancelled")

        async with self._lock:
            if self.metadata.state == SessionState.RUNNING:
                self.metadata.state = SessionState.CANCELLED

        if self._send:
            await self._send(
                Event(
                    type="cancel:requested",
                    properties={"session_id": self.session_id},
                )
            )

    async def handle_approval(self, request_id: str, choice: str) -> bool:
        """Handle an approval response from the client."""
        result = self.approval.handle_response(request_id, choice)

        if result and self._send:
            event_type = "approval:granted" if choice != "deny" else "approval:denied"
            await self._send(
                Event(
                    type=event_type,
                    properties={
                        "session_id": self.session_id,
                        "request_id": request_id,
                        "choice": choice,
                    },
                )
            )

        return result

    async def _emit_state_change(self) -> None:
        """Emit session state change event."""
        if self._send:
            await self._send(
                Event(
                    type="session:state",
                    properties={
                        "session_id": self.session_id,
                        "state": self.metadata.state.value,
                        "turn_count": self.metadata.turn_count,
                        "bundle": self.metadata.bundle_name,
                    },
                )
            )

    def set_send_function(self, send_fn: Callable[[Event], Coroutine[Any, Any, None]]) -> None:
        """Update the send function for all protocol handlers."""
        self._send = send_fn
        self.display.set_send_function(send_fn)
        self.approval.set_send_function(send_fn)
        self.spawn_manager.set_send_function(send_fn)
        self.streaming_hook.set_send_function(send_fn)

    def to_dict(self) -> dict[str, Any]:
        """Serialize session metadata."""
        return {
            "session_id": self.session_id,
            "state": self.metadata.state.value,
            "bundle": self.metadata.bundle_name,
            "created_at": self.metadata.created_at.isoformat(),
            "updated_at": self.metadata.updated_at.isoformat(),
            "turn_count": self.metadata.turn_count,
            "cwd": self.metadata.cwd,
            "parent_session_id": self.metadata.parent_session_id,
            "error": self.metadata.error,
        }


class SessionManager:
    """Manager for all active sessions.

    Provides:
    - Session creation and lookup
    - Session lifecycle management
    - Concurrent session support
    - Cleanup and persistence
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        config: SessionConfig | None = None,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]] | None = None,
    ) -> ManagedSession:
        """Create a new session.

        Args:
            config: Session configuration
            send_fn: Function to send events to client

        Returns:
            The created session
        """
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        config = config or SessionConfig()

        session = ManagedSession(
            session_id=session_id,
            config=config,
            send_fn=send_fn,
        )

        async with self._lock:
            self._sessions[session_id] = session

        logger.info(f"Created session {session_id}")
        return session

    async def get(self, session_id: str) -> ManagedSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The session ID

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if session:
            # Cancel any pending operations
            await session.cancel()
            logger.info(f"Deleted session {session_id}")
            return True

        return False

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions with metadata."""
        return [s.to_dict() for s in self._sessions.values()]

    async def cleanup_completed(self, max_age_seconds: float = 3600) -> int:
        """Clean up old completed sessions.

        Args:
            max_age_seconds: Maximum age for completed sessions

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now()
        to_delete = []

        for session_id, session in self._sessions.items():
            if session.metadata.state in (
                SessionState.COMPLETED,
                SessionState.ERROR,
                SessionState.CANCELLED,
            ):
                age = (now - session.metadata.updated_at).total_seconds()
                if age > max_age_seconds:
                    to_delete.append(session_id)

        async with self._lock:
            for session_id in to_delete:
                self._sessions.pop(session_id, None)

        if to_delete:
            logger.info(f"Cleaned up {len(to_delete)} old sessions")

        return len(to_delete)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return sum(
            1
            for s in self._sessions.values()
            if s.metadata.state
            in (SessionState.READY, SessionState.RUNNING, SessionState.WAITING_APPROVAL)
        )

    @property
    def total_count(self) -> int:
        """Total number of sessions."""
        return len(self._sessions)


# Global session manager instance
session_manager = SessionManager()
