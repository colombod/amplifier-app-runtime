"""Spawn manager for agent delegation.

Handles spawning sub-sessions for agent delegation via the task tool.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amplifier_foundation import PreparedBundle

logger = logging.getLogger(__name__)


class ServerSpawnManager:
    """Manages spawning of sub-sessions for agent delegation.

    This enables the task tool to spawn sub-agents. Events from child
    sessions are forwarded to the parent session's hooks for streaming.
    """

    def __init__(self) -> None:
        """Initialize the spawn manager."""
        self._active_spawns: dict[str, Any] = {}

    async def spawn(
        self,
        agent_name: str,
        instruction: str,
        parent_session: Any,
        agent_configs: dict[str, dict],
        prepared_bundle: PreparedBundle,
        parent_tool_call_id: str | None = None,
        sub_session_id: str | None = None,
        tool_inheritance: dict[str, list[str]] | None = None,
        hook_inheritance: dict[str, list[str]] | None = None,
        orchestrator_config: dict | None = None,
        parent_messages: list[dict] | None = None,
        provider_override: str | None = None,
        model_override: str | None = None,
    ) -> dict:
        """Spawn a sub-session for agent delegation.

        Args:
            agent_name: Name of the agent to spawn
            instruction: Task instruction for the agent
            parent_session: The parent AmplifierSession
            agent_configs: Agent configurations from the bundle
            prepared_bundle: The PreparedBundle for creating sessions
            parent_tool_call_id: Optional tool call ID for correlation
            sub_session_id: Optional session ID to use
            tool_inheritance: Tools to inherit from parent
            hook_inheritance: Hooks to inherit from parent
            orchestrator_config: Optional orchestrator configuration
            parent_messages: Optional context messages to pass
            provider_override: Optional provider to use
            model_override: Optional model to use

        Returns:
            Result dict with status, result, and session_id
        """
        import uuid

        # Generate sub-session ID if not provided
        if not sub_session_id:
            sub_session_id = f"sub_{uuid.uuid4().hex[:12]}"

        logger.info(f"Spawning agent '{agent_name}' with session {sub_session_id}")

        # Get parent hooks for event forwarding (outside try for access in except)
        parent_hooks = parent_session.coordinator.hooks

        try:
            # Get agent config
            agent_config = agent_configs.get(agent_name)
            if not agent_config:
                return {
                    "status": "error",
                    "error": f"Unknown agent: {agent_name}",
                    "session_id": sub_session_id,
                }

            # Emit session:fork event BEFORE creating child session
            if parent_hooks:
                logger.info(
                    f"Emitting session:fork: child={sub_session_id}, "
                    f"tool_call_id={parent_tool_call_id}, agent={agent_name}"
                )
                await parent_hooks.emit(
                    "session:fork",
                    {
                        "parent_id": parent_session.session_id,
                        "child_id": sub_session_id,
                        "parent_tool_call_id": parent_tool_call_id,
                        "agent": agent_name,
                    },
                )

            # Create event forwarder to parent hooks
            def create_event_forwarder():
                """Create a hook that forwards events to parent session."""

                async def forward_event(event_type: str, data: dict) -> dict:
                    # Annotate with spawn context for TUI display
                    data = dict(data)
                    data["child_session_id"] = sub_session_id
                    data["parent_tool_call_id"] = parent_tool_call_id
                    data["agent_name"] = agent_name
                    data["nesting_depth"] = data.get("nesting_depth", 0) + 1

                    # Forward to parent hooks
                    if parent_hooks:
                        await parent_hooks.emit(event_type, data)
                    return {}

                return forward_event

            # Create child session
            child_session = await prepared_bundle.create_session(
                session_id=sub_session_id,
                parent_id=parent_session.session_id,
                agent_name=agent_name,
            )

            # Register event forwarder
            forwarder = create_event_forwarder()
            child_hooks = child_session.coordinator.hooks
            if child_hooks:
                # Forward key events to parent
                for event in [
                    "content_block:start",
                    "content_block:delta",
                    "content_block:end",
                    "tool:pre",
                    "tool:post",
                    "tool:error",
                ]:
                    child_hooks.register(
                        event=event,
                        handler=forwarder,
                        priority=50,
                        name=f"parent-forward:{event}",
                    )

            # Track active spawn
            self._active_spawns[sub_session_id] = child_session

            # Execute the instruction
            logger.info(f"Executing instruction in spawned session {sub_session_id}")
            result = await child_session.execute(instruction)

            # Clean up
            self._active_spawns.pop(sub_session_id, None)

            # Emit session:join event when spawn completes
            if parent_hooks:
                await parent_hooks.emit(
                    "session:join",
                    {
                        "parent_id": parent_session.session_id,
                        "child_id": sub_session_id,
                        "parent_tool_call_id": parent_tool_call_id,
                        "agent": agent_name,
                        "status": "success",
                    },
                )

            return {
                "status": "success",
                "result": result,
                "session_id": sub_session_id,
            }

        except Exception as e:
            logger.error(f"Spawn failed for agent '{agent_name}': {e}")
            self._active_spawns.pop(sub_session_id, None)

            # Emit session:join event with error status
            if parent_hooks:
                await parent_hooks.emit(
                    "session:join",
                    {
                        "parent_id": parent_session.session_id,
                        "child_id": sub_session_id,
                        "parent_tool_call_id": parent_tool_call_id,
                        "agent": agent_name,
                        "status": "error",
                        "error": str(e),
                    },
                )

            return {
                "status": "error",
                "error": str(e),
                "session_id": sub_session_id,
            }

    def get_active_spawns(self) -> list[str]:
        """Get list of active spawn session IDs."""
        return list(self._active_spawns.keys())

    async def cancel_spawn(self, session_id: str) -> bool:
        """Cancel an active spawn.

        Args:
            session_id: The spawn session ID to cancel

        Returns:
            True if cancelled, False if not found
        """
        session = self._active_spawns.get(session_id)
        if not session:
            return False

        try:
            if hasattr(session, "cancel"):
                await session.cancel()
            return True
        except Exception as e:
            logger.warning(f"Error cancelling spawn {session_id}: {e}")
            return False


def register_spawn_capability(
    session: Any,
    prepared_bundle: PreparedBundle,
    spawn_manager: ServerSpawnManager | None = None,
) -> ServerSpawnManager:
    """Register session spawning capability on a session.

    Args:
        session: The AmplifierSession to register on
        prepared_bundle: The PreparedBundle for creating sessions
        spawn_manager: Optional existing spawn manager to use

    Returns:
        The spawn manager instance
    """
    if spawn_manager is None:
        spawn_manager = ServerSpawnManager()

    async def spawn_capability(
        agent_name: str,
        instruction: str,
        parent_session: Any,
        agent_configs: dict[str, dict],
        sub_session_id: str | None = None,
        tool_inheritance: dict[str, list[str]] | None = None,
        hook_inheritance: dict[str, list[str]] | None = None,
        orchestrator_config: dict | None = None,
        parent_messages: list[dict] | None = None,
        provider_override: str | None = None,
        model_override: str | None = None,
        parent_tool_call_id: str | None = None,
    ) -> dict:
        return await spawn_manager.spawn(
            agent_name=agent_name,
            instruction=instruction,
            parent_session=parent_session,
            agent_configs=agent_configs,
            prepared_bundle=prepared_bundle,
            parent_tool_call_id=parent_tool_call_id,
            sub_session_id=sub_session_id,
            tool_inheritance=tool_inheritance,
            hook_inheritance=hook_inheritance,
            orchestrator_config=orchestrator_config,
            parent_messages=parent_messages,
            provider_override=provider_override,
            model_override=model_override,
        )

    session.coordinator.register_capability("session.spawn", spawn_capability)
    logger.info("Registered session spawn capability (session.spawn)")

    return spawn_manager
