"""Display System Protocol.

Handles notifications and display messages to the client.
Used by tools and hooks to show status, warnings, and info to users.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..transport.base import Event

logger = logging.getLogger(__name__)


class DisplaySystem:
    """Display system for sending notifications to clients.

    Provides a unified interface for tools and hooks to display
    messages to users, regardless of the transport being used.

    Levels:
    - info: General information
    - warning: Non-fatal warnings
    - error: Error messages
    - debug: Debug information (may be filtered)
    """

    def __init__(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]] | None = None,
    ):
        """Initialize display system.

        Args:
            send_fn: Async function to send events to client.
                     If None, messages are logged only.
        """
        self._send = send_fn
        self._buffer: list[dict[str, Any]] = []

    async def show(
        self,
        message: str,
        level: str = "info",
        source: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Display a message to the user.

        Args:
            message: The message text
            level: Message level (info, warning, error, debug)
            source: Optional source identifier (tool name, hook name, etc.)
            **kwargs: Additional metadata
        """
        display_data = {
            "type": "display_message",
            "level": level,
            "message": message,
            "source": source,
            **kwargs,
        }

        # Log locally
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, f"[{source or 'display'}] {message}")

        # Send to client if connected
        if self._send:
            from ..transport.base import Event

            await self._send(Event(type="display_message", properties=display_data))
        else:
            # Buffer for later delivery
            self._buffer.append(display_data)

    async def info(self, message: str, **kwargs: Any) -> None:
        """Display an info message."""
        await self.show(message, level="info", **kwargs)

    async def warning(self, message: str, **kwargs: Any) -> None:
        """Display a warning message."""
        await self.show(message, level="warning", **kwargs)

    async def error(self, message: str, **kwargs: Any) -> None:
        """Display an error message."""
        await self.show(message, level="error", **kwargs)

    async def debug(self, message: str, **kwargs: Any) -> None:
        """Display a debug message."""
        await self.show(message, level="debug", **kwargs)

    def set_send_function(
        self,
        send_fn: Callable[[Event], Coroutine[Any, Any, None]],
    ) -> None:
        """Set or update the send function.

        Args:
            send_fn: Async function to send events
        """
        self._send = send_fn

    async def flush_buffer(self) -> None:
        """Send any buffered messages."""
        if not self._send:
            return

        from ..transport.base import Event

        for data in self._buffer:
            await self._send(Event(type="display_message", properties=data))

        self._buffer.clear()

    def get_buffered_messages(self) -> list[dict[str, Any]]:
        """Get buffered messages without clearing."""
        return list(self._buffer)
