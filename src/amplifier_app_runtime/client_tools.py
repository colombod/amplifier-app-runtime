"""Client-side tool support for HTTP SDK.

Client-side tools are tools where:
- Tool schema (name, description, parameters) is sent from SDK client
- Tool handler runs CLIENT-SIDE (in browser/app), not in runtime
- Runtime creates proxy tools that emit events
- SDK intercepts tool.call events and executes handler client-side
- SDK sends result back via tool.result event

Architecture:
1. SDK sends clientTools with schemas in bundle_definition
2. Runtime creates ClientToolProxy for each
3. Proxy emits tool.call event (runtime doesn't execute)
4. SDK intercepts event, runs handler, emits tool.result
5. Runtime receives result and continues orchestration
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_core.models import ToolResult

logger = logging.getLogger(__name__)


class ClientToolProxy:
    """Proxy tool that delegates execution to SDK client.

    This implements the Amplifier Tool protocol but doesn't execute locally.
    Instead, it signals the orchestrator to emit a tool.call event that the
    SDK client will handle.
    """

    def __init__(self, name: str, description: str, parameters: dict[str, Any] | None = None):
        """Initialize client tool proxy.

        Args:
            name: Tool name
            description: Tool description (for LLM)
            parameters: JSON Schema for tool parameters
        """
        self._name = name
        self._description = description
        self._parameters = parameters or {"type": "object"}

    @property
    def name(self) -> str:
        """Tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Tool description."""
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        """Input schema (JSON Schema)."""
        return self._parameters

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        """Execute is a no-op - actual execution happens client-side.

        The orchestrator will:
        1. Emit tool.call event with this tool's name and input
        2. SDK client intercepts the event
        3. SDK executes the handler client-side
        4. SDK emits tool.result event
        5. Orchestrator receives result and continues

        This method should NEVER be called by the orchestrator for client tools.
        The orchestrator detects client tools and handles them specially.

        If this IS called, something is wrong with the orchestrator's client
        tool detection.
        """
        logger.warning(
            f"ClientToolProxy.execute() called for '{self._name}' - "
            "this should not happen. Orchestrator should handle client tools via events."
        )

        return ToolResult(
            output="",
            error={"message": f"Client tool '{self._name}' execute() called unexpectedly"},
        )


async def register_client_tools(
    session: Any,  # AmplifierSession
    client_tools: list[dict[str, Any]],
) -> list[str]:
    """Register client-side tools on a session.

    Args:
        session: AmplifierSession to register tools on
        client_tools: List of client tool definitions from bundle
                      Each dict should have: {name, description, parameters}

    Returns:
        List of registered tool names
    """
    if not client_tools:
        return []

    coordinator = session.coordinator
    registered = []

    for tool_def in client_tools:
        name = tool_def.get("name")
        if not name:
            logger.warning(f"Client tool missing name: {tool_def}")
            continue

        description = tool_def.get("description", f"Client-side tool: {name}")
        parameters = tool_def.get("parameters", {"type": "object"})

        # Create proxy tool
        proxy = ClientToolProxy(
            name=name,
            description=description,
            parameters=parameters,
        )

        # Mount to coordinator (makes it visible to LLM)
        try:
            await coordinator.mount("tools", proxy)
            registered.append(name)
            logger.info(f"Registered client-side tool: {name}")
        except Exception as e:
            logger.error(f"Failed to register client tool {name}: {e}")

    return registered
