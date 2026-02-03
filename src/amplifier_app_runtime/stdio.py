"""Native protocol stdio server.

Runs the Amplifier protocol over stdin/stdout using JSON lines:
- Reads Command JSON objects from stdin (one per line)
- Writes Event JSON objects to stdout (one per line)

This is the native Amplifier protocol, NOT ACP.
Use this for TUI subprocess communication.

Wire format:
    stdin:  {"id": "cmd_1", "cmd": "session.list", "params": {}}\n
    stdout: {"id": "evt_1", "type": "result", "correlation_id": "cmd_1", ...}\n
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TextIO

from .protocol import Command, CommandHandler, Event
from .session import session_manager

logger = logging.getLogger(__name__)


class StdioProtocolServer:
    """Native protocol server over stdio.

    Reads commands from stdin, processes them through CommandHandler,
    writes events to stdout.
    """

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ):
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._handler = CommandHandler(session_manager)
        self._running = False

    async def run(self) -> None:
        """Run the stdio server loop."""
        self._running = True
        self._log("Amplifier runtime ready (native protocol)")

        # Use asyncio for non-blocking stdin reading
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        await loop.connect_read_pipe(lambda: protocol, self._stdin)

        try:
            while self._running:
                # Read a line from stdin
                try:
                    line = await reader.readline()
                    if not line:
                        # EOF - stdin closed
                        self._log("stdin closed, shutting down")
                        break

                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue

                    # Parse and handle command
                    await self._handle_line(line_str)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._log(f"Error reading stdin: {e}")
                    # Send error event
                    error_event = Event.error(None, str(e), code="stdin_error")
                    self._write_event(error_event)

        finally:
            self._running = False
            self._log("Shutdown complete")

    async def _handle_line(self, line: str) -> None:
        """Parse and handle a single command line."""
        try:
            data = json.loads(line)
            command = Command.model_validate(data)

            # Process command and stream events
            async for event in self._handler.handle(command):
                self._write_event(event)

        except json.JSONDecodeError as e:
            self._log(f"Invalid JSON: {e}")
            error_event = Event.error(None, f"Invalid JSON: {e}", code="parse_error")
            self._write_event(error_event)

        except Exception as e:
            self._log(f"Error handling command: {e}")
            error_event = Event.error(None, str(e), code="handler_error")
            self._write_event(error_event)

    def _write_event(self, event: Event) -> None:
        """Write an event to stdout as JSON line."""
        try:
            line = event.model_dump_json() + "\n"
            self._stdout.write(line)
            self._stdout.flush()
        except Exception as e:
            self._log(f"Error writing event: {e}")

    def _log(self, message: str) -> None:
        """Write log message to stderr."""
        self._stderr.write(f"[amplifier-runtime] {message}\n")
        self._stderr.flush()

    def stop(self) -> None:
        """Signal the server to stop."""
        self._running = False


async def run_native_stdio() -> None:
    """Run the native protocol stdio server.

    This is the entry point for subprocess mode with native protocol.
    """
    server = StdioProtocolServer()

    try:
        await server.run()
    except KeyboardInterrupt:
        server.stop()
