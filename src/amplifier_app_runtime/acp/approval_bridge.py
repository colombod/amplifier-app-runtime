"""ACP Approval Bridge - Implements ApprovalSystem for ACP protocol.

This module bridges Amplifier's ApprovalSystem protocol to ACP's
session/request_permission method, enabling native IDE permission dialogs
when tools require user approval.

Flow:
1. Hook returns HookResult(action="ask_user")
2. Coordinator calls approval_system.request_approval()
3. ACPApprovalBridge calls client.request_permission()
4. IDE shows native permission dialog
5. User selects option
6. Response mapped back to Amplifier option string
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from acp import Client  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class ToolCallContext:
    """Context for the currently executing tool call.

    This is captured when tool:pre events fire and used to include
    proper context in ACP permission requests.
    """

    call_id: str
    tool_name: str
    arguments: dict[str, Any]


# Context variable for tracking current tool call (async-safe)
_current_tool_call: ContextVar[ToolCallContext | None] = ContextVar(
    "current_tool_call", default=None
)


class ToolCallTracker:
    """Tracks the current tool call for approval context.

    This is used to include toolCallId in ACP permission requests.
    The tracker is updated when tool:pre events fire and cleared
    when tools complete.

    Uses contextvars for async-safe tracking across concurrent tasks.
    """

    @staticmethod
    def track(call_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        """Set the current tool call context."""
        _current_tool_call.set(
            ToolCallContext(
                call_id=call_id,
                tool_name=tool_name,
                arguments=arguments,
            )
        )

    @staticmethod
    def clear() -> None:
        """Clear the current tool call context."""
        _current_tool_call.set(None)

    @staticmethod
    def get_current() -> ToolCallContext | None:
        """Get the current tool call context."""
        return _current_tool_call.get()


class ACPApprovalBridge:
    """Bridges Amplifier's ApprovalSystem to ACP's request_permission.

    Implements the same interface as ServerApprovalSystem and CLIApprovalSystem:
        request_approval(prompt, options, timeout, default) -> str

    Instead of sending custom events, this calls the ACP Client's
    request_permission() method which triggers native IDE permission dialogs.

    Features:
    - Maps Amplifier options to ACP PermissionOption format
    - Caches "Allow always" decisions for the session
    - Falls back gracefully on timeout or error
    - Includes tool call context in permission requests
    """

    # Standard option mappings from Amplifier to ACP kinds
    OPTION_KIND_MAP = {
        "allow once": "allow_once",
        "allow always": "allow_always",
        "allow session": "allow_always",  # Map session-scoped to always
        "allow": "allow_once",  # Default "allow" to once
        "yes": "allow_once",
        "deny": "reject_once",
        "deny once": "reject_once",
        "deny always": "reject_always",
        "no": "reject_once",
        "reject": "reject_once",
    }

    def __init__(
        self,
        session_id: str,
        get_client: Callable[[], Client | None],
    ) -> None:
        """Initialize the approval bridge.

        Args:
            session_id: The ACP session ID for permission requests
            get_client: Callable that returns the ACP Client (lazy access)
        """
        self._session_id = session_id
        self._get_client = get_client
        self._cache: dict[int, str] = {}  # Session-scoped approval cache

    async def request_approval(
        self,
        prompt: str,
        options: list[str],
        timeout: float,
        default: Literal["allow", "deny"],
    ) -> str:
        """Request approval from the user via ACP permission request.

        Args:
            prompt: Question to ask user (e.g., "Allow tool X to run?")
            options: Available choices (e.g., ["Allow once", "Allow always", "Deny"])
            timeout: Seconds to wait for response
            default: Action to take on timeout ("allow" or "deny")

        Returns:
            The user's chosen option string (from the original options list)
        """
        # Check cache for "Allow always" decisions
        cache_key = hash((prompt, tuple(options)))
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug(f"Using cached approval: {cached}")
            return cached

        client = self._get_client()
        if not client:
            logger.warning("No ACP client available, using default")
            return self._resolve_default(default, options)

        try:
            # Build ACP permission request
            permission_options = self._build_permission_options(options)
            tool_call = self._build_tool_call_context(prompt)

            # Call ACP request_permission with timeout
            response = await asyncio.wait_for(
                client.request_permission(
                    session_id=self._session_id,
                    tool_call=tool_call,
                    options=permission_options,
                ),
                timeout=timeout,
            )

            # Map response back to Amplifier option string
            selected_id = response.outcome.option_id
            result = self._map_option_id_to_string(selected_id, options)

            logger.debug(f"ACP permission response: {selected_id} -> {result}")

            # Cache "always" decisions
            if "always" in result.lower():
                self._cache[cache_key] = result
                logger.debug(f"Cached 'always' approval: {result}")

            return result

        except TimeoutError:
            logger.warning(f"ACP permission request timed out after {timeout}s")
            return self._resolve_default(default, options)
        except Exception as e:
            logger.warning(f"ACP permission request failed: {e}")
            return self._resolve_default(default, options)

    def _build_permission_options(self, options: list[str]) -> list[dict[str, Any]]:
        """Convert Amplifier options to ACP PermissionOption format.

        Args:
            options: List of option strings (e.g., ["Allow once", "Deny"])

        Returns:
            List of PermissionOption dicts for ACP
        """
        result = []
        # Sort patterns by length (longest first) to match "deny always" before "deny"
        sorted_patterns = sorted(
            self.OPTION_KIND_MAP.items(), key=lambda x: len(x[0]), reverse=True
        )

        for i, option in enumerate(options):
            option_lower = option.lower()

            # Determine option kind by matching patterns (longest first)
            kind = "allow_once"  # Default
            for pattern, acp_kind in sorted_patterns:
                if pattern in option_lower:
                    kind = acp_kind
                    break

            result.append(
                {
                    "optionId": f"opt_{i}",
                    "name": option,
                    "kind": kind,
                }
            )

        return result

    def _build_tool_call_context(self, prompt: str) -> dict[str, Any]:
        """Build the toolCall context for the permission request.

        Args:
            prompt: The approval prompt to include

        Returns:
            ToolCallUpdate dict for ACP
        """
        # Get current tool call context if available
        ctx = ToolCallTracker.get_current()

        if ctx:
            return {
                "sessionUpdate": "tool_call",
                "toolCallId": ctx.call_id,
                "title": self._generate_title(ctx.tool_name, ctx.arguments),
                "kind": self._infer_kind(ctx.tool_name),
                "status": "pending",
                "content": [{"type": "text", "text": prompt}],
            }
        else:
            # Fallback when no tool context (shouldn't happen normally)
            return {
                "sessionUpdate": "tool_call",
                "toolCallId": f"approval_{uuid.uuid4().hex[:8]}",
                "title": "Permission Required",
                "kind": "other",
                "status": "pending",
                "content": [{"type": "text", "text": prompt}],
            }

    def _map_option_id_to_string(
        self,
        option_id: str,
        options: list[str],
    ) -> str:
        """Map ACP option ID back to Amplifier option string.

        Args:
            option_id: The selected option ID (e.g., "opt_0")
            options: Original options list

        Returns:
            The corresponding option string
        """
        # Option IDs are "opt_0", "opt_1", etc.
        try:
            index = int(option_id.split("_")[1])
            if 0 <= index < len(options):
                return options[index]
        except (ValueError, IndexError):
            pass

        # Fallback: return first option
        logger.warning(f"Unknown option ID: {option_id}, using first option")
        return options[0] if options else "Deny"

    def _resolve_default(
        self,
        default: Literal["allow", "deny"],
        options: list[str],
    ) -> str:
        """Find the best matching option for the default action.

        Args:
            default: The default action ("allow" or "deny")
            options: Available options to choose from

        Returns:
            The best matching option string
        """
        for option in options:
            option_lower = option.lower()
            if default == "allow" and ("allow" in option_lower or "yes" in option_lower):
                return option
            if default == "deny" and ("deny" in option_lower or "no" in option_lower):
                return option

        # Fall back to last option (typically "deny") or first
        return options[-1] if default == "deny" else options[0]

    def _generate_title(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Generate human-readable title for the tool.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Human-readable title
        """
        # Common tool title patterns
        title_map = {
            "bash": f"Run: {arguments.get('command', 'shell command')[:50]}",
            "write_file": f"Write to {arguments.get('file_path', 'file')}",
            "edit_file": f"Edit {arguments.get('file_path', 'file')}",
            "read_file": f"Read {arguments.get('file_path', 'file')}",
            "glob": f"Search files: {arguments.get('pattern', '*')}",
            "grep": f"Search content: {arguments.get('pattern', '')}",
            "web_fetch": f"Fetch URL: {arguments.get('url', '')}",
            "web_search": f"Search web: {arguments.get('query', '')}",
        }
        return title_map.get(tool_name, tool_name.replace("_", " ").title())

    def _infer_kind(self, tool_name: str) -> str:
        """Infer ACP tool kind from tool name.

        Args:
            tool_name: Name of the tool

        Returns:
            ACP tool kind string
        """
        kind_map = {
            "bash": "execute",
            "write_file": "edit",
            "edit_file": "edit",
            "read_file": "read",
            "glob": "read",
            "grep": "read",
            "web_fetch": "fetch",
            "web_search": "fetch",
            "task": "delegate",
        }
        return kind_map.get(tool_name, "other")
