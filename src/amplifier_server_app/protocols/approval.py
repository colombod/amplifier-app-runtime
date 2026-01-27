"""Approval system for server-side approval handling.

Provides the approval interface required by amplifier-core for tool
execution approvals and other user confirmation requests.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from typing import Any

from ..transport.base import Event

logger = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    """A pending approval request waiting for user response."""

    request_id: str
    tool_name: str
    tool_args: dict[str, Any]
    options: list[str]
    future: asyncio.Future[str]
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ServerApprovalSystem:
    """Approval system that sends approval requests to connected clients.

    Implements the approval system interface expected by amplifier-core.
    Approval requests are sent as events to clients, and responses are
    collected via the handle_response method.
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Awaitable[None]] | None = None,
        timeout: float = 300.0,
    ) -> None:
        """Initialize the approval system.

        Args:
            send_fn: Async function to send events to the client
            timeout: Default timeout for approval requests (seconds)
        """
        self._send_fn = send_fn
        self._timeout = timeout
        self._pending: dict[str, PendingApproval] = {}

    def set_send_fn(self, send_fn: Callable[[Event], Awaitable[None]]) -> None:
        """Set the send function after initialization."""
        self._send_fn = send_fn

    async def request_approval(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        options: list[str] | None = None,
        message: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Request approval from the user.

        Args:
            tool_name: Name of the tool requesting approval
            tool_args: Arguments to the tool
            options: Available choices (default: ["approve", "deny"])
            message: Optional message to display
            timeout: Timeout for this request (uses default if not specified)

        Returns:
            The user's chosen option

        Raises:
            asyncio.TimeoutError: If approval times out
            RuntimeError: If no send function is configured
        """
        if not self._send_fn:
            logger.warning("No send function configured, auto-denying approval")
            return "deny"

        options = options or ["approve", "deny"]
        timeout = timeout or self._timeout
        request_id = f"approval_{uuid.uuid4().hex[:12]}"

        # Create future for response
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()

        # Store pending request
        pending = PendingApproval(
            request_id=request_id,
            tool_name=tool_name,
            tool_args=tool_args,
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
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "options": options,
                    "message": message or f"Approve execution of {tool_name}?",
                    "timeout": timeout,
                },
            )
            await self._send_fn(event)
            logger.debug(f"Sent approval request {request_id} for {tool_name}")

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            logger.debug(f"Received approval response for {request_id}: {result}")

            # Send confirmation event
            confirmation_event = Event(
                type="approval:granted" if result == "approve" else "approval:denied",
                properties={
                    "request_id": request_id,
                    "choice": result,
                },
            )
            await self._send_fn(confirmation_event)

            return result

        except asyncio.TimeoutError:
            logger.warning(f"Approval request {request_id} timed out")
            # Send timeout event
            if self._send_fn:
                await self._send_fn(
                    Event(
                        type="approval:denied",
                        properties={
                            "request_id": request_id,
                            "choice": "deny",
                            "reason": "timeout",
                        },
                    )
                )
            raise

        finally:
            # Clean up pending request
            self._pending.pop(request_id, None)

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
            pass

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
                "tool_name": p.tool_name,
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
