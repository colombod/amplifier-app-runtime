"""stdio Protocol Adapter.

Thin adapter layer that maps stdio JSON lines to protocol commands
and protocol events to stdout JSON lines.

This enables CLI tools and other processes to communicate with
Amplifier using the same protocol as HTTP/WebSocket clients.

Wire format (newline-delimited JSON):
- Input (stdin):  {"id": "cmd_123", "cmd": "session.create", "params": {...}}
- Output (stdout): {"id": "evt_456", "type": "result", "correlation_id": "cmd_123", ...}
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING, TextIO

from ..protocol import Command, CommandHandler, Event
from ..session import session_manager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StdioProtocolAdapter:
    """Bidirectional stdio adapter using the protocol layer.

    Reads JSON commands from stdin, processes via CommandHandler,
    writes JSON events to stdout.

    All business logic is delegated to CommandHandler - this adapter
    only handles serialization and I/O.

    Usage:
        adapter = StdioProtocolAdapter()
        await adapter.run()  # Blocks until stdin closes

    Wire Protocol:
        Commands: One JSON object per line on stdin
        Events: One JSON object per line on stdout
        Errors: Written to stderr (not protocol events)

    Example session:
        → {"id":"c1","cmd":"session.create","params":{"bundle":"amplifier-dev"}}
        ← {"id":"e1","type":"result","correlation_id":"c1","data":{"session_id":"sess_abc"}}
        → {"id":"c2","cmd":"prompt.send","params":{"session_id":"sess_abc","content":"hello"}}
        ← {"id":"e2","type":"ack","correlation_id":"c2"}
        ← {"id":"e3","type":"content.delta","correlation_id":"c2","data":{"delta":"Hi"}}
        ← {"id":"e4","type":"content.delta","correlation_id":"c2","data":{"delta":" there"}}
        ← {"id":"e5","type":"result","correlation_id":"c2","final":true}
    """

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ):
        """Initialize stdio adapter.

        Args:
            stdin: Input stream (default: sys.stdin)
            stdout: Output stream (default: sys.stdout)
            stderr: Error stream (default: sys.stderr)
        """
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._handler = CommandHandler(session_manager)
        self._running = False

    async def run(self) -> None:
        """Run the adapter, processing commands until stdin closes."""
        self._running = True

        # Send connected event
        await self._send_event(Event.connected({"transport": "stdio"}))

        try:
            # Process stdin line by line
            while self._running:
                line = await self._read_line()
                if line is None:
                    break  # EOF

                line = line.strip()
                if not line:
                    continue  # Skip empty lines

                await self._process_line(line)

        except asyncio.CancelledError:
            logger.info("stdio adapter cancelled")
        except Exception as e:
            logger.exception(f"stdio adapter error: {e}")
            self._log_error(f"Fatal error: {e}")
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the adapter."""
        self._running = False

    async def _read_line(self) -> str | None:
        """Read a line from stdin asynchronously."""
        loop = asyncio.get_event_loop()
        try:
            # Run blocking readline in executor
            line = await loop.run_in_executor(None, self._stdin.readline)
            return line if line else None
        except Exception:
            return None

    async def _process_line(self, line: str) -> None:
        """Process a single input line."""
        try:
            # Parse command
            command = Command.model_validate_json(line)
            logger.debug(f"Received command: {command.cmd} (id={command.id})")

            # Process and stream events
            async for event in self._handler.handle(command):
                await self._send_event(event)

        except Exception as e:
            # Send error event for parse/validation failures
            error_event = Event.error(
                correlation_id=None,  # Can't correlate if we couldn't parse
                error=f"Invalid command: {e}",
                code="PARSE_ERROR",
            )
            await self._send_event(error_event)
            self._log_error(f"Parse error: {e}")

    async def _send_event(self, event: Event) -> None:
        """Send an event to stdout."""
        try:
            json_line = event.model_dump_json()
            self._stdout.write(json_line + "\n")
            self._stdout.flush()
        except Exception as e:
            self._log_error(f"Failed to send event: {e}")

    def _log_error(self, message: str) -> None:
        """Log error to stderr."""
        self._stderr.write(f"ERROR: {message}\n")
        self._stderr.flush()


async def run_stdio_adapter() -> None:
    """Run the stdio adapter as main entry point."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,  # Logs go to stderr, protocol to stdout
    )

    adapter = StdioProtocolAdapter()
    await adapter.run()


def main() -> None:
    """Synchronous entry point for CLI."""
    asyncio.run(run_stdio_adapter())


if __name__ == "__main__":
    main()
