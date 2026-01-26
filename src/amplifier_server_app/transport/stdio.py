"""stdio Transport Implementation.

Provides stdin/stdout based communication for:
- Editor/IDE integration (VS Code, Neovim, etc.)
- MCP-style subprocess spawning
- Pipe-based IPC
- CLI embedding

Protocol:
- Input: JSON objects, one per line (newline-delimited JSON)
- Output: JSON objects, one per line (newline-delimited JSON)
- Follows same event schema as other transports
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, TextIO

from .base import Event, Transport, TransportMode

logger = logging.getLogger(__name__)


@dataclass
class StdioConfig:
    """Configuration for stdio transport."""

    mode: TransportMode = TransportMode.STDIO
    input_stream: TextIO | None = None  # Default: sys.stdin
    output_stream: TextIO | None = None  # Default: sys.stdout
    buffer_size: int = 8192


class StdioTransport(Transport):
    """Bidirectional stdio transport.

    Combines reader and writer for full duplex communication.
    Used when server runs as subprocess communicating via pipes.

    Example usage:
        # Start server in stdio mode
        $ amplifier-server --stdio

        # From parent process (Python)
        proc = subprocess.Popen(
            ["amplifier-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        # Send message
        proc.stdin.write(json.dumps({"type": "prompt", "content": "Hello"}) + "\\n")
        proc.stdin.flush()

        # Read response
        for line in proc.stdout:
            event = json.loads(line)
            print(event)
    """

    def __init__(
        self,
        config: StdioConfig | None = None,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ):
        self._config = config or StdioConfig()
        self._input = input_stream or self._config.input_stream or sys.stdin
        self._output = output_stream or self._config.output_stream or sys.stdout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._running = False

    async def connect(self) -> None:
        """Set up async stdin reader and stdout writer."""
        loop = asyncio.get_event_loop()

        # Set up stdin reader
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, self._input)

        # Set up stdout writer
        transport, proto = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin,
            self._output,
        )
        self._writer = asyncio.StreamWriter(transport, proto, None, loop)

        self._running = True
        logger.info("stdio transport connected")

    async def disconnect(self) -> None:
        """Close the transport."""
        self._running = False

        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()

        logger.info("stdio transport disconnected")

    async def send(self, event: Event) -> None:
        """Send event to stdout as JSON line."""
        if not self._writer:
            raise RuntimeError("Transport not connected")

        async with self._write_lock:
            message = {"type": event.type, **event.properties}
            line = json.dumps(message, ensure_ascii=False) + "\n"
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()

    async def receive(self) -> AsyncIterator[Event]:
        """Receive events from stdin."""
        if not self._reader:
            raise RuntimeError("Transport not connected")

        while self._running:
            try:
                line = await self._reader.readline()
                if not line:
                    # EOF
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    yield Event(
                        type=data.pop("type", "unknown"),
                        properties=data,
                    )
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON on stdin: {e}")
                    yield Event(
                        type="transport:error",
                        properties={"error": "json_parse_error", "message": str(e)},
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading stdin: {e}")
                yield Event(
                    type="transport:error",
                    properties={"error": "read_error", "message": str(e)},
                )
                break

    async def run_loop(self, handler: Any) -> None:
        """Run request/response loop.

        Args:
            handler: Async callable that takes an event and returns optional response event
        """
        await self.connect()

        try:
            async for event in self.receive():
                try:
                    response = await handler(event)
                    if response:
                        await self.send(response)
                except Exception as e:
                    logger.error(f"Handler error: {e}")
                    await self.send(
                        Event(
                            type="error",
                            properties={"error": str(e)},
                        )
                    )
        finally:
            await self.disconnect()


async def run_stdio_server(handler: Any) -> None:
    """Convenience function to run a stdio server.

    Args:
        handler: Async callable that handles events and returns responses

    Example:
        async def handle(event):
            if event.type == "prompt":
                # Process prompt...
                return Event(type="response", properties={"text": "Hello!"})
            return None

        asyncio.run(run_stdio_server(handle))
    """
    transport = StdioTransport()
    await transport.run_loop(handler)
