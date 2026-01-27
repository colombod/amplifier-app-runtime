"""Display system for server-side notifications.

Provides the display interface required by amplifier-core for
user notifications and status updates.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Awaitable
from typing import Any

from ..transport.base import Event

logger = logging.getLogger(__name__)


class ServerDisplaySystem:
    """Display system that sends notifications to connected clients.

    Implements the display system interface expected by amplifier-core.
    Notifications are sent as events to clients via the send function.
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the display system.

        Args:
            send_fn: Async function to send events to the client
        """
        self._send_fn = send_fn

    def set_send_fn(self, send_fn: Callable[[Event], Awaitable[None]]) -> None:
        """Set the send function after initialization."""
        self._send_fn = send_fn

    async def notify(
        self,
        message: str,
        level: str = "info",
        title: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification to the user.

        Args:
            message: The notification message
            level: Notification level (info, warning, error, success)
            title: Optional title for the notification
            details: Optional additional details
        """
        if not self._send_fn:
            logger.debug(f"[{level}] {message}")
            return

        try:
            event = Event(
                type="user:notification",
                properties={
                    "message": message,
                    "level": level,
                    "title": title,
                    "details": details,
                },
            )
            await self._send_fn(event)
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    async def info(self, message: str, **kwargs: Any) -> None:
        """Send an info notification."""
        await self.notify(message, level="info", **kwargs)

    async def warning(self, message: str, **kwargs: Any) -> None:
        """Send a warning notification."""
        await self.notify(message, level="warning", **kwargs)

    async def error(self, message: str, **kwargs: Any) -> None:
        """Send an error notification."""
        await self.notify(message, level="error", **kwargs)

    async def success(self, message: str, **kwargs: Any) -> None:
        """Send a success notification."""
        await self.notify(message, level="success", **kwargs)

    async def status(self, message: str, **kwargs: Any) -> None:
        """Send a status update.

        Status updates are typically transient UI states like "Loading..."
        """
        if not self._send_fn:
            logger.debug(f"[status] {message}")
            return

        try:
            event = Event(
                type="status:update",
                properties={
                    "message": message,
                    **kwargs,
                },
            )
            await self._send_fn(event)
        except Exception as e:
            logger.warning(f"Failed to send status: {e}")

    async def progress(
        self,
        current: int,
        total: int,
        message: str | None = None,
    ) -> None:
        """Send a progress update.

        Args:
            current: Current progress value
            total: Total expected value
            message: Optional progress message
        """
        if not self._send_fn:
            pct = (current / total * 100) if total > 0 else 0
            logger.debug(f"[progress] {pct:.1f}% - {message or ''}")
            return

        try:
            event = Event(
                type="progress:update",
                properties={
                    "current": current,
                    "total": total,
                    "message": message,
                    "percentage": (current / total * 100) if total > 0 else 0,
                },
            )
            await self._send_fn(event)
        except Exception as e:
            logger.warning(f"Failed to send progress: {e}")
