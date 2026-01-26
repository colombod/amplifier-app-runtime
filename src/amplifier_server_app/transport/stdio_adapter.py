"""stdio Protocol Adapter.

Thin adapter layer that maps stdio JSON lines to protocol commands
and protocol events to stdout JSON lines.

This enables CLI tools and other processes to communicate with
Amplifier using the same protocol as HTTP/WebSocket clients.

Wire format (newline-delimited JSON, UTF-8 encoded):
- Input (stdin):  {"id": "cmd_123", "cmd": "session.create", "params": {...}}
- Output (stdout): {"id": "evt_456", "type": "result", "correlation_id": "cmd_123", ...}

Cross-platform considerations:
- All JSON is UTF-8 encoded (no BOM)
- Newlines are always LF (\\n), never CRLF
- Input accepts both LF and CRLF (normalized to LF)
- Binary mode used internally for consistent behavior
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
from typing import TYPE_CHECKING, BinaryIO

from ..protocol import Command, CommandHandler, Event
from ..session import session_manager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# UTF-8 encoding for all JSON operations
ENCODING = "utf-8"

# Newline character (always LF for cross-platform consistency)
NEWLINE = "\n"


def _ensure_binary_stream(stream: BinaryIO | None, default_fd: int, mode: str) -> BinaryIO:
    """Ensure we have a binary stream for consistent encoding.

    Args:
        stream: Provided stream or None
        default_fd: File descriptor for default (0=stdin, 1=stdout, 2=stderr)
        mode: 'rb' for read, 'wb' for write

    Returns:
        Binary stream
    """
    if stream is not None:
        return stream

    # Get raw binary stream, bypassing any text wrapper
    if default_fd == 0:
        return sys.stdin.buffer
    elif default_fd == 1:
        return sys.stdout.buffer
    else:
        return sys.stderr.buffer


class StdioProtocolAdapter:
    """Bidirectional stdio adapter using the protocol layer.

    Reads JSON commands from stdin, processes via CommandHandler,
    writes JSON events to stdout.

    All business logic is delegated to CommandHandler - this adapter
    only handles serialization and I/O.

    Encoding:
        - All I/O uses UTF-8 encoding explicitly
        - Binary streams used internally for cross-platform consistency
        - Output uses LF newlines (not CRLF) regardless of platform
        - Input accepts both LF and CRLF (stripped during processing)

    Usage:
        adapter = StdioProtocolAdapter()
        await adapter.run()  # Blocks until stdin closes

    Wire Protocol:
        Commands: One JSON object per line on stdin (UTF-8, LF or CRLF)
        Events: One JSON object per line on stdout (UTF-8, LF only)
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
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        stderr: BinaryIO | None = None,
    ):
        """Initialize stdio adapter.

        Args:
            stdin: Binary input stream (default: sys.stdin.buffer)
            stdout: Binary output stream (default: sys.stdout.buffer)
            stderr: Binary error stream (default: sys.stderr.buffer)
        """
        self._stdin = _ensure_binary_stream(stdin, 0, "rb")
        self._stdout = _ensure_binary_stream(stdout, 1, "wb")
        self._stderr = _ensure_binary_stream(stderr, 2, "wb")

        # Wrap binary streams with UTF-8 text readers/writers
        self._reader = io.TextIOWrapper(
            self._stdin,
            encoding=ENCODING,
            errors="replace",  # Replace invalid UTF-8 with replacement char
            newline="",  # Universal newline mode - accepts LF, CRLF, CR
        )
        self._writer = io.TextIOWrapper(
            self._stdout,
            encoding=ENCODING,
            errors="replace",
            newline=NEWLINE,  # Always output LF
            write_through=True,  # Don't buffer
        )
        self._error_writer = io.TextIOWrapper(
            self._stderr,
            encoding=ENCODING,
            errors="replace",
            newline=NEWLINE,
            write_through=True,
        )

        self._handler = CommandHandler(session_manager)
        self._running = False

    async def run(self) -> None:
        """Run the adapter, processing commands until stdin closes."""
        self._running = True

        # Send connected event
        await self._send_event(Event.connected({"transport": "stdio", "encoding": ENCODING}))

        try:
            # Process stdin line by line
            while self._running:
                line = await self._read_line()
                if line is None:
                    break  # EOF

                # Normalize line endings and strip whitespace
                line = line.strip()
                if not line:
                    continue  # Skip empty lines

                # Skip UTF-8 BOM if present at start
                if line.startswith("\ufeff"):
                    line = line[1:]

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
            line = await loop.run_in_executor(None, self._reader.readline)
            return line if line else None
        except Exception:
            return None

    async def _process_line(self, line: str) -> None:
        """Process a single input line."""
        try:
            # Parse command from UTF-8 JSON
            command = Command.model_validate_json(line.encode(ENCODING))
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
        """Send an event to stdout as UTF-8 JSON."""
        try:
            # Serialize to JSON with ensure_ascii=False for proper Unicode
            json_str = event.model_dump_json()
            self._writer.write(json_str + NEWLINE)
            self._writer.flush()
        except Exception as e:
            self._log_error(f"Failed to send event: {e}")

    def _log_error(self, message: str) -> None:
        """Log error to stderr."""
        self._error_writer.write(f"ERROR: {message}{NEWLINE}")
        self._error_writer.flush()


async def run_stdio_adapter() -> None:
    """Run the stdio adapter as main entry point."""
    # Configure logging to stderr (protocol goes to stdout)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    adapter = StdioProtocolAdapter()
    await adapter.run()


def main() -> None:
    """Synchronous entry point for CLI."""
    # On Windows, ensure binary mode for stdin/stdout
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stderr.fileno(), os.O_BINARY)

    asyncio.run(run_stdio_adapter())


if __name__ == "__main__":
    main()
