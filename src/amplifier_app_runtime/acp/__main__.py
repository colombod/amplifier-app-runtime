"""ACP Agent entry point with proper stdio isolation.

CRITICAL: This module implements a JSON-RPC stdout filter to ensure ONLY valid
JSON-RPC messages reach stdout. Any non-JSON content is redirected to stderr.

When using stdio transport, stdout must be reserved exclusively for JSON-RPC
protocol messages. Any log output to stdout will corrupt the protocol and
cause JSON parse errors on the client side.

Usage:
    python -m amplifier_app_runtime.acp
"""

from __future__ import annotations

import io
import json
import logging
import sys
import threading

# =============================================================================
# CRITICAL: Install stdout filter FIRST, before ANY imports
# =============================================================================
# This filter ensures that only valid JSON-RPC messages reach stdout.
# Any non-JSON content (log messages, print statements, etc.) is redirected
# to stderr to prevent protocol corruption.


class JsonRpcStdoutFilter(io.TextIOBase):
    """A stdout filter that only allows valid JSON-RPC messages through.

    Any content that is not a valid JSON object starting with '{' is
    redirected to stderr with a warning prefix.

    This is the LAST LINE OF DEFENSE against stdout corruption when using
    stdio transport for ACP JSON-RPC protocol.
    """

    def __init__(self, real_stdout: io.TextIOBase, stderr: io.TextIOBase) -> None:
        super().__init__()
        self._real_stdout = real_stdout
        self._stderr = stderr
        self._lock = threading.Lock()
        self._buffer = ""

    def write(self, data: str) -> int:
        """Write data, filtering non-JSON content to stderr."""
        if not data:
            return 0

        with self._lock:
            # Add to buffer
            self._buffer += data

            # Process complete lines
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._process_line(line)

            return len(data)

    def _process_line(self, line: str) -> None:
        """Process a single line, routing to stdout or stderr."""
        stripped = line.strip()

        if not stripped:
            # Empty lines are DROPPED - JSON-RPC doesn't expect them
            # and they cause "Expecting value: line 2 column 1" errors
            return

        # Check if it's valid JSON starting with '{'
        if stripped.startswith("{"):
            try:
                # Validate it's actually JSON
                json.loads(stripped)
                # Valid JSON-RPC message - send to real stdout (stripped, no extra whitespace)
                self._real_stdout.write(stripped + "\n")
                self._real_stdout.flush()
                return
            except json.JSONDecodeError:
                pass  # Fall through to stderr

        # Non-JSON content - redirect to stderr with marker
        # This prevents log messages from corrupting the protocol
        self._stderr.write(f"[stdout-filtered] {line}\n")
        self._stderr.flush()

    def flush(self) -> None:
        """Flush both streams."""
        with self._lock:
            # Flush any remaining buffer content to stderr
            if self._buffer:
                self._stderr.write(f"[stdout-filtered] {self._buffer}\n")
                self._buffer = ""
            self._real_stdout.flush()
            self._stderr.flush()

    def fileno(self) -> int:
        """Return the file descriptor of the real stdout."""
        return self._real_stdout.fileno()

    def get_encoding(self) -> str:
        """Return the encoding of the real stdout."""
        return getattr(self._real_stdout, "encoding", "utf-8")


def _install_stdout_filter() -> None:
    """Install the JSON-RPC stdout filter.

    This MUST be called before ANY imports that might write to stdout.
    """
    # Only install if stdout is a TTY or pipe (not already redirected)
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = JsonRpcStdoutFilter(sys.stdout, sys.stderr)  # type: ignore[assignment]


def _configure_stdio_safe_logging() -> None:
    """Configure ALL logging to use stderr, ensuring stdout is clean for JSON-RPC.

    This function:
    1. Removes ALL existing handlers from ALL loggers (to undo any prior config)
    2. Sets up the root logger to ONLY write to stderr
    3. Ensures all loggers propagate to root (so they use stderr too)

    This must be called BEFORE any imports that might configure logging.
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Remove ALL existing handlers from the root logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Also clear handlers from any loggers that might have been configured
    # (e.g., by previously imported modules)
    for logger_name in list(logging.Logger.manager.loggerDict.keys()):
        logger_instance = logging.getLogger(logger_name)
        for handler in logger_instance.handlers[:]:
            logger_instance.removeHandler(handler)
        # Ensure propagation to root (which uses stderr)
        logger_instance.propagate = True

    # Configure root logger with ONLY a stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root_logger.addHandler(stderr_handler)
    root_logger.setLevel(logging.INFO)


# =============================================================================
# INSTALL PROTECTIONS IMMEDIATELY - before any other imports
# =============================================================================
# Order matters:
# 1. Install stdout filter first (catches any rogue stdout writes)
# 2. Configure logging to stderr (proper channel for logs)
_install_stdout_filter()
_configure_stdio_safe_logging()

# =============================================================================
# Now it's safe to import the agent module
# =============================================================================

import asyncio  # noqa: E402

from .agent import run_stdio_agent  # noqa: E402


def main() -> None:
    """Run the ACP agent with stdio transport."""
    # Log startup to stderr (safe, won't corrupt protocol)
    logging.getLogger(__name__).info("Starting Amplifier ACP agent (stdio mode)")

    # Run the agent
    asyncio.run(run_stdio_agent())


if __name__ == "__main__":
    main()
