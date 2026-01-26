"""Event Bus - Central pub/sub for all system events.

All events flow through this bus. SSE subscribers receive everything.
Inspired by OpenCode's Bus pattern.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class EventDefinition(Generic[T]):
    """Typed event definition.

    Usage:
        SessionCreated = Bus.define("session.created", SessionCreatedProps)
        await Bus.publish(SessionCreated, SessionCreatedProps(session_id="..."))
    """

    type: str
    schema: type[T]


# Type for event callbacks
EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class Bus:
    """Simple event bus with wildcard subscription support.

    Thread-safe via asyncio.Lock. All subscriptions and publishes
    are handled asynchronously.
    """

    _subscriptions: dict[str, list[EventCallback]] = {}
    _lock: asyncio.Lock | None = None

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """Get or create the lock (lazy init for event loop safety)."""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    def define(cls, event_type: str, schema: type[T]) -> EventDefinition[T]:
        """Define a typed event.

        Args:
            event_type: Dot-separated event name (e.g., "session.created")
            schema: Pydantic model for event properties

        Returns:
            EventDefinition that can be used with publish/subscribe
        """
        return EventDefinition(type=event_type, schema=schema)

    @classmethod
    async def publish(cls, event_def: EventDefinition[T], properties: T) -> None:
        """Publish event to all subscribers.

        Args:
            event_def: The event definition (created via Bus.define)
            properties: Event properties (must match the schema)
        """
        payload = {"type": event_def.type, "properties": properties.model_dump()}

        async with cls._get_lock():
            # Get copies of subscriber lists to avoid mutation during iteration
            specific_subs = list(cls._subscriptions.get(event_def.type, []))
            wildcard_subs = list(cls._subscriptions.get("*", []))

        # Notify specific subscribers
        for callback in specific_subs:
            try:
                await callback(payload)
            except Exception:
                logger.exception(f"Error in subscriber for {event_def.type}")

        # Notify wildcard subscribers (for SSE)
        for callback in wildcard_subs:
            try:
                await callback(payload)
            except Exception:
                logger.exception(f"Error in wildcard subscriber for {event_def.type}")

    @classmethod
    async def subscribe(
        cls, event_def: EventDefinition[T], callback: EventCallback
    ) -> Callable[[], None]:
        """Subscribe to a specific event type.

        Args:
            event_def: The event definition to subscribe to
            callback: Async function called with event payload

        Returns:
            Unsubscribe function
        """
        return await cls._subscribe(event_def.type, callback)

    @classmethod
    async def subscribe_all(cls, callback: EventCallback) -> Callable[[], None]:
        """Subscribe to ALL events (used by SSE endpoint).

        Args:
            callback: Async function called with every event payload

        Returns:
            Unsubscribe function
        """
        return await cls._subscribe("*", callback)

    @classmethod
    async def _subscribe(cls, key: str, callback: EventCallback) -> Callable[[], None]:
        """Internal subscribe implementation."""
        async with cls._get_lock():
            if key not in cls._subscriptions:
                cls._subscriptions[key] = []
            cls._subscriptions[key].append(callback)

        def unsubscribe() -> None:
            # Synchronous unsubscribe (safe because we're just removing)
            if key in cls._subscriptions and callback in cls._subscriptions[key]:
                cls._subscriptions[key].remove(callback)

        return unsubscribe

    @classmethod
    async def stream(cls) -> AsyncIterator[dict[str, Any]]:
        """Create an async iterator that yields all events.

        Useful for SSE endpoints. Yields events as they are published.

        Usage:
            async for event in Bus.stream():
                yield f"data: {json.dumps(event)}\\n\\n"
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def on_event(payload: dict[str, Any]) -> None:
            await queue.put(payload)

        unsubscribe = await cls.subscribe_all(on_event)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            unsubscribe()

    @classmethod
    def reset(cls) -> None:
        """Reset bus state (for testing)."""
        cls._subscriptions = {}
        cls._lock = None
