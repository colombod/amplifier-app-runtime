"""Display system for server-side notifications.

Provides the display interface required by amplifier-core for
user notifications and status updates.

Implements the DisplaySystem protocol with the same signature as
CLIDisplaySystem and WebDisplaySystem.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from ..transport.base import Event

logger = logging.getLogger(__name__)


class ServerDisplaySystem:
    """Display system that sends notifications to connected clients.

    Implements the DisplaySystem protocol expected by amplifier-core.
    Notifications are sent as events to clients via the send function.

    Interface matches CLIDisplaySystem and WebDisplaySystem:
        show_message(message, level, source) -> None
        push_nesting() / pop_nesting() for sub-session hierarchy
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Awaitable[None]] | None = None,
        nesting_depth: int = 0,
    ) -> None:
        """Initialize the display system.

        Args:
            send_fn: Async function to send events to the client
            nesting_depth: Current nesting level for sub-sessions
        """
        self._send_fn = send_fn
        self._nesting_depth = nesting_depth

    def set_send_fn(self, send_fn: Callable[[Event], Awaitable[None]]) -> None:
        """Set the send function after initialization."""
        self._send_fn = send_fn

    async def show_message(
        self,
        message: str,
        level: Literal["info", "warning", "error"] = "info",
        source: str = "hook",
    ) -> None:
        """Display message to user via event stream.

        This is the interface expected by amplifier-core's display system.

        Args:
            message: Message text to display
            level: Severity level (info/warning/error)
            source: Message source for context (e.g., "hook:python-check")
        """
        if not self._send_fn:
            # Log locally if no send function
            log_fn = getattr(logger, level, logger.info)
            log_fn(f"[{source}] {message}")
            return

        try:
            event = Event(
                type="display:message",
                properties={
                    "message": message,
                    "level": level,
                    "source": source,
                    "nesting_depth": self._nesting_depth,
                },
            )
            await self._send_fn(event)
        except Exception as e:
            logger.warning(f"Failed to send display message: {e}")

    def push_nesting(self) -> ServerDisplaySystem:
        """Create a nested display system for sub-sessions.

        Returns:
            New ServerDisplaySystem with incremented nesting depth
        """
        return ServerDisplaySystem(
            send_fn=self._send_fn,
            nesting_depth=self._nesting_depth + 1,
        )

    def pop_nesting(self) -> ServerDisplaySystem:
        """Create a display system with reduced nesting.

        Returns:
            New ServerDisplaySystem with decremented nesting depth
        """
        return ServerDisplaySystem(
            send_fn=self._send_fn,
            nesting_depth=max(0, self._nesting_depth - 1),
        )

    @property
    def nesting_depth(self) -> int:
        """Current nesting depth for visual hierarchy."""
        return self._nesting_depth

    # Convenience methods (not part of core protocol, but useful)

    async def info(self, message: str, source: str = "system") -> None:
        """Send an info message."""
        await self.show_message(message, level="info", source=source)

    async def warning(self, message: str, source: str = "system") -> None:
        """Send a warning message."""
        await self.show_message(message, level="warning", source=source)

    async def error(self, message: str, source: str = "system") -> None:
        """Send an error message."""
        await self.show_message(message, level="error", source=source)
