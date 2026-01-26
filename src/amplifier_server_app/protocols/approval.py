"""Approval System Protocol.

Handles user approval requests for tool execution and sensitive operations.
Provides async/await interface for requesting and receiving approvals.
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
class ApprovalRequest:
    """A pending approval request."""

    request_id: str
    prompt: str
    options: list[str]
    timeout: float
    default: str | None
    future: asyncio.Future[str] = field(default_factory=lambda: asyncio.Future())
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ApprovalSystem:
    """Approval system for requesting user consent.

    Used by tools and hooks to pause execution and wait for
    user approval before proceeding with sensitive operations.

    Example:
        approval = ApprovalSystem(send_fn=transport.send)

        # In a tool
        choice = await approval.request(
            "Delete 10 files?",
            options=["yes", "no", "preview"],
            default="no",
            timeout=60.0,
        )

        if choice == "yes":
            # Proceed with deletion
            ...
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]] | None = None,
    ):
        """Initialize approval system.

        Args:
            send_fn: Async function to send events to client
        """
        self._send = send_fn
        self._pending: dict[str, ApprovalRequest] = {}

    async def request(
        self,
        prompt: str,
        options: list[str] | None = None,
        default: str | None = None,
        timeout: float = 30.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Request approval from the user.

        Args:
            prompt: The question/prompt to display
            options: Available choices (default: ["yes", "no"])
            default: Default option if timeout (default: None = raises)
            timeout: Timeout in seconds
            context: Additional context to send with request

        Returns:
            The user's chosen option

        Raises:
            asyncio.TimeoutError: If timeout and no default
            RuntimeError: If no send function configured
        """
        if options is None:
            options = ["yes", "no"]

        request_id = str(uuid.uuid4())[:8]

        # Create pending request
        request = ApprovalRequest(
            request_id=request_id,
            prompt=prompt,
            options=options,
            timeout=timeout,
            default=default,
        )
        self._pending[request_id] = request

        # Send approval request to client
        if self._send:
            from ..transport.base import Event

            await self._send(
                Event(
                    type="approval:required",
                    properties={
                        "request_id": request_id,
                        "prompt": prompt,
                        "options": options,
                        "timeout": timeout,
                        "default": default,
                        **(context or {}),
                    },
                )
            )

        logger.info(f"Approval requested: {prompt} (id={request_id})")

        # Wait for response
        try:
            choice = await asyncio.wait_for(request.future, timeout=timeout)
            logger.info(f"Approval {request_id}: user chose '{choice}'")
            return choice

        except TimeoutError:
            logger.warning(f"Approval {request_id}: timeout")
            self._pending.pop(request_id, None)

            if default is not None:
                # Send timeout event with default choice
                if self._send:
                    from ..transport.base import Event

                    await self._send(
                        Event(
                            type="approval:granted",
                            properties={
                                "request_id": request_id,
                                "choice": default,
                                "reason": "timeout_default",
                            },
                        )
                    )
                return default

            raise

        finally:
            self._pending.pop(request_id, None)

    def handle_response(self, request_id: str, choice: str) -> bool:
        """Handle an approval response from the client.

        Args:
            request_id: The request ID from the approval request
            choice: The user's chosen option

        Returns:
            True if response was handled, False if request not found
        """
        request = self._pending.get(request_id)
        if not request:
            logger.warning(f"Unknown approval request: {request_id}")
            return False

        if choice not in request.options:
            logger.warning(
                f"Invalid choice '{choice}' for approval {request_id}, "
                f"valid options: {request.options}"
            )
            return False

        # Complete the future
        if not request.future.done():
            request.future.set_result(choice)

        return True

    def cancel(self, request_id: str, reason: str = "cancelled") -> bool:
        """Cancel a pending approval request.

        Args:
            request_id: The request ID to cancel
            reason: Cancellation reason

        Returns:
            True if cancelled, False if not found
        """
        request = self._pending.pop(request_id, None)
        if not request:
            return False

        if not request.future.done():
            request.future.cancel()

        logger.info(f"Approval {request_id} cancelled: {reason}")
        return True

    def cancel_all(self, reason: str = "session_ended") -> int:
        """Cancel all pending approvals.

        Args:
            reason: Cancellation reason

        Returns:
            Number of approvals cancelled
        """
        count = 0
        for request_id in list(self._pending.keys()):
            if self.cancel(request_id, reason):
                count += 1
        return count

    def set_send_function(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]],
    ) -> None:
        """Set or update the send function."""
        self._send = send_fn

    @property
    def pending_count(self) -> int:
        """Number of pending approval requests."""
        return len(self._pending)

    def get_pending(self, request_id: str) -> ApprovalRequest | None:
        """Get a pending request by ID."""
        return self._pending.get(request_id)
