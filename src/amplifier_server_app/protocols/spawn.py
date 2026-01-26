"""Spawn Manager Protocol.

Handles agent spawning (sub-sessions) with event forwarding.
When a parent session spawns a child agent, events from the child
are forwarded to the parent's client with proper nesting context.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..transport.base import Event

logger = logging.getLogger(__name__)


@dataclass
class SpawnedSession:
    """Metadata for a spawned child session."""

    child_session_id: str
    parent_session_id: str
    parent_tool_call_id: str | None
    agent_name: str
    nesting_depth: int
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    status: str = "running"  # running, completed, error, cancelled


class SpawnManager:
    """Manager for spawned agent sessions with event forwarding.

    Handles the lifecycle of child sessions spawned by parent sessions.
    Forwards events from children to parents with proper context for
    nested agent visualization in the UI.

    Key features:
    - Tracks parent-child relationships
    - Forwards child events to parent's transport
    - Adds nesting context (child_session_id, parent_tool_call_id, depth)
    - Handles cleanup on completion/error

    Example:
        spawn_mgr = SpawnManager(send_fn=transport.send)

        # When task tool spawns an agent
        child_id = await spawn_mgr.spawn(
            parent_session_id="sess_123",
            agent_name="foundation:explorer",
            parent_tool_call_id="tool_456",
        )

        # Child events are automatically forwarded with context
        # Client sees: {
        #   "type": "content_delta",
        #   "child_session_id": "sess_789",
        #   "parent_tool_call_id": "tool_456",
        #   "nesting_depth": 1,
        #   ...
        # }
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]] | None = None,
    ):
        """Initialize spawn manager.

        Args:
            send_fn: Async function to send events to client
        """
        self._send = send_fn
        self._sessions: dict[str, SpawnedSession] = {}
        self._children: dict[str, list[str]] = {}  # parent_id -> [child_ids]

    async def spawn(
        self,
        parent_session_id: str,
        agent_name: str,
        parent_tool_call_id: str | None = None,
        instruction: str | None = None,
    ) -> str:
        """Register a new spawned session.

        Args:
            parent_session_id: ID of the parent session
            agent_name: Name of the agent being spawned
            parent_tool_call_id: Tool call ID that triggered the spawn
            instruction: Optional instruction for the agent

        Returns:
            The new child session ID
        """
        child_session_id = f"spawn_{uuid.uuid4().hex[:12]}"

        # Calculate nesting depth
        parent = self._sessions.get(parent_session_id)
        nesting_depth = (parent.nesting_depth + 1) if parent else 1

        # Create session record
        session = SpawnedSession(
            child_session_id=child_session_id,
            parent_session_id=parent_session_id,
            parent_tool_call_id=parent_tool_call_id,
            agent_name=agent_name,
            nesting_depth=nesting_depth,
        )
        self._sessions[child_session_id] = session

        # Track parent-child relationship
        if parent_session_id not in self._children:
            self._children[parent_session_id] = []
        self._children[parent_session_id].append(child_session_id)

        logger.info(
            f"Spawned session {child_session_id} "
            f"(agent={agent_name}, parent={parent_session_id}, depth={nesting_depth})"
        )

        # Notify client of spawn
        if self._send:
            from ..transport.base import Event

            await self._send(
                Event(
                    type="session:fork",
                    properties={
                        "child_session_id": child_session_id,
                        "parent_session_id": parent_session_id,
                        "parent_tool_call_id": parent_tool_call_id,
                        "agent_name": agent_name,
                        "nesting_depth": nesting_depth,
                        "instruction": instruction,
                    },
                )
            )

        return child_session_id

    async def forward_event(
        self,
        child_session_id: str,
        event_type: str,
        event_data: dict[str, Any],
    ) -> None:
        """Forward an event from a child session to the parent's client.

        Args:
            child_session_id: The child session that emitted the event
            event_type: The event type
            event_data: The event data
        """
        session = self._sessions.get(child_session_id)
        if not session:
            logger.warning(f"Unknown child session: {child_session_id}")
            return

        if not self._send:
            return

        from ..transport.base import Event

        # Add nesting context to event
        enriched_data = {
            **event_data,
            "child_session_id": child_session_id,
            "parent_session_id": session.parent_session_id,
            "parent_tool_call_id": session.parent_tool_call_id,
            "nesting_depth": session.nesting_depth,
            "agent_name": session.agent_name,
        }

        await self._send(Event(type=event_type, properties=enriched_data))

    async def complete(
        self,
        child_session_id: str,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Mark a spawned session as completed.

        Args:
            child_session_id: The child session ID
            result: Optional result from the session
            error: Optional error message if failed
        """
        session = self._sessions.get(child_session_id)
        if not session:
            logger.warning(f"Unknown child session: {child_session_id}")
            return

        session.status = "error" if error else "completed"

        logger.info(
            f"Session {child_session_id} completed (status={session.status}, error={error})"
        )

        # Notify client
        if self._send:
            from ..transport.base import Event

            await self._send(
                Event(
                    type="session:end",
                    properties={
                        "child_session_id": child_session_id,
                        "parent_session_id": session.parent_session_id,
                        "parent_tool_call_id": session.parent_tool_call_id,
                        "nesting_depth": session.nesting_depth,
                        "status": session.status,
                        "result": result,
                        "error": error,
                    },
                )
            )

    def cancel(self, child_session_id: str) -> bool:
        """Cancel a spawned session.

        Args:
            child_session_id: The child session ID

        Returns:
            True if cancelled, False if not found
        """
        session = self._sessions.get(child_session_id)
        if not session:
            return False

        session.status = "cancelled"
        logger.info(f"Session {child_session_id} cancelled")
        return True

    def cancel_children(self, parent_session_id: str) -> int:
        """Cancel all children of a parent session.

        Args:
            parent_session_id: The parent session ID

        Returns:
            Number of children cancelled
        """
        child_ids = self._children.get(parent_session_id, [])
        count = 0
        for child_id in child_ids:
            if self.cancel(child_id):
                count += 1
        return count

    def get_session(self, session_id: str) -> SpawnedSession | None:
        """Get a spawned session by ID."""
        return self._sessions.get(session_id)

    def get_children(self, parent_session_id: str) -> list[SpawnedSession]:
        """Get all children of a parent session."""
        child_ids = self._children.get(parent_session_id, [])
        return [self._sessions[cid] for cid in child_ids if cid in self._sessions]

    def get_nesting_depth(self, session_id: str) -> int:
        """Get the nesting depth for a session."""
        session = self._sessions.get(session_id)
        return session.nesting_depth if session else 0

    def set_send_function(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]],
    ) -> None:
        """Set or update the send function."""
        self._send = send_fn

    def cleanup_completed(self) -> int:
        """Remove completed/cancelled sessions from tracking.

        Returns:
            Number of sessions cleaned up
        """
        completed = [
            sid
            for sid, s in self._sessions.items()
            if s.status in ("completed", "error", "cancelled")
        ]

        for sid in completed:
            session = self._sessions.pop(sid, None)
            if session:
                # Remove from parent's children list
                parent_children = self._children.get(session.parent_session_id, [])
                if sid in parent_children:
                    parent_children.remove(sid)

        return len(completed)

    @property
    def active_count(self) -> int:
        """Number of active (running) spawned sessions."""
        return sum(1 for s in self._sessions.values() if s.status == "running")
