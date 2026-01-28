"""Approval system for server-side approval handling.

Provides the approval interface required by amplifier-core for tool
execution approvals and other user confirmation requests.

Implements the ApprovalSystem protocol with the same signature as
CLIApprovalSystem and WebApprovalSystem.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..transport.base import Event

logger = logging.getLogger(__name__)


class ApprovalTimeoutError(Exception):
    """Raised when user approval times out."""

    pass


@dataclass
class PendingApproval:
    """A pending approval request waiting for user response."""

    request_id: str
    prompt: str
    options: list[str]
    future: asyncio.Future[str]
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ServerApprovalSystem:
    """Approval system that sends approval requests to connected clients.

    Implements the ApprovalSystem protocol expected by amplifier-core.
    Approval requests are sent as events to clients, and responses are
    collected via the handle_response method.

    Interface matches CLIApprovalSystem and WebApprovalSystem:
        request_approval(prompt, options, timeout, default) -> str
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the approval system.

        Args:
            send_fn: Async function to send events to the client
        """
        self._send_fn = send_fn
        self._pending: dict[str, PendingApproval] = {}
        self._cache: dict[int, str] = {}  # Session-scoped approval cache

    def set_send_fn(self, send_fn: Callable[[Event], Awaitable[None]]) -> None:
        """Set the send function after initialization."""
        self._send_fn = send_fn

    async def request_approval(
        self,
        prompt: str,
        options: list[str],
        timeout: float,
        default: Literal["allow", "deny"],
    ) -> str:
        """Request approval from the user.

        This is the interface expected by amplifier-core's approval system.

        Args:
            prompt: Question to ask user (e.g., "Allow tool X to run?")
            options: Available choices (e.g., ["Allow once", "Allow always", "Deny"])
            timeout: Seconds to wait for response
            default: Action to take on timeout ("allow" or "deny")

        Returns:
            The user's chosen option string

        Raises:
            ApprovalTimeoutError: If approval times out and we want to raise
        """
        # Check cache for "Allow always" decisions
        cache_key = hash((prompt, tuple(options)))
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug(f"Using cached approval: {cached}")
            return cached

        if not self._send_fn:
            logger.warning("No send function configured, using default")
            return self._resolve_default(default, options)

        request_id = f"approval_{uuid.uuid4().hex[:12]}"

        # Create future for response
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()

        # Store pending request
        pending = PendingApproval(
            request_id=request_id,
            prompt=prompt,
            options=options,
            future=future,
        )
        self._pending[request_id] = pending

        try:
            # Send approval request to client
            event = Event(
                type="approval:required",
                properties={
                    "request_id": request_id,
                    "prompt": prompt,
                    "options": options,
                    "timeout": timeout,
                    "default": default,
                },
            )
            await self._send_fn(event)
            logger.debug(f"Sent approval request {request_id}")

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            logger.debug(f"Received approval response for {request_id}: {result}")

            # Cache "always" decisions
            if "always" in result.lower():
                self._cache[cache_key] = result
                logger.debug(f"Cached 'always' approval: {result}")

            # Send confirmation event
            confirmation_event = Event(
                type="approval:resolved",
                properties={
                    "request_id": request_id,
                    "choice": result,
                },
            )
            await self._send_fn(confirmation_event)

            return result

        except TimeoutError:
            logger.warning(f"Approval request {request_id} timed out")
            # Send timeout event
            if self._send_fn:
                await self._send_fn(
                    Event(
                        type="approval:timeout",
                        properties={
                            "request_id": request_id,
                            "applied_default": default,
                        },
                    )
                )
            return self._resolve_default(default, options)

        finally:
            # Clean up pending request
            self._pending.pop(request_id, None)

    def _resolve_default(
        self,
        default: Literal["allow", "deny"],
        options: list[str],
    ) -> str:
        """Find the best matching option for the default action.

        Args:
            default: The default action ("allow" or "deny")
            options: Available options

        Returns:
            The option string that best matches the default
        """
        # Try to find option matching default
        for option in options:
            option_lower = option.lower()
            if default == "allow" and ("allow" in option_lower or "yes" in option_lower):
                return option
            if default == "deny" and ("deny" in option_lower or "no" in option_lower):
                return option

        # Fall back to last option (typically "deny") or first
        return options[-1] if default == "deny" else options[0]

    def handle_response(self, request_id: str, choice: str) -> bool:
        """Handle an approval response from the client.

        Args:
            request_id: The approval request ID
            choice: The user's chosen option

        Returns:
            True if the response was handled, False if request not found
        """
        pending = self._pending.get(request_id)
        if not pending:
            logger.warning(f"No pending approval for request {request_id}")
            return False

        if pending.future.done():
            logger.warning(f"Approval {request_id} already completed")
            return False

        # Validate choice
        if choice not in pending.options:
            logger.warning(
                f"Invalid choice '{choice}' for approval {request_id}, "
                f"expected one of {pending.options}"
            )
            # Still accept it but log the warning

        pending.future.set_result(choice)
        logger.debug(f"Handled approval response for {request_id}: {choice}")
        return True

    def get_pending_count(self) -> int:
        """Get the number of pending approval requests."""
        return len(self._pending)

    def get_pending_requests(self) -> list[dict[str, Any]]:
        """Get list of pending approval requests.

        Returns:
            List of pending request info dicts
        """
        return [
            {
                "request_id": p.request_id,
                "prompt": p.prompt,
                "options": p.options,
            }
            for p in self._pending.values()
        ]

    def cancel_all(self) -> int:
        """Cancel all pending approval requests.

        Returns:
            Number of requests cancelled
        """
        count = 0
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_result("deny")
                count += 1
        self._pending.clear()
        return count
