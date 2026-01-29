# Amplifier Server

HTTP API server with event streaming for AI agent sessions.

## Overview

Amplifier Server provides the backend infrastructure for AI agent interactions:

- **HTTP REST API** for session management
- **Server-Sent Events (SSE)** for real-time streaming
- **stdio transport** for embedded/CLI use
- **Protocol layer** with Command/Event types for client interoperability
- **SDK** for both remote and embedded (in-process) modes

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Client Applications                          │
│  (amplifier-tui, web apps, IDE extensions, etc.)                │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                    SDK (HTTP or Embedded)
                                  │
┌─────────────────────────────────┴───────────────────────────────┐
│                    Amplifier Server                             │
├─────────────────────────────────────────────────────────────────┤
│  Protocol Layer                                                 │
│  ├── Commands (session.create, prompt.send, etc.)               │
│  └── Events (result, error, content.delta, etc.)                │
├─────────────────────────────────────────────────────────────────┤
│  Transport Layer                                                │
│  ├── HTTP + SSE (primary)                                       │
│  └── stdio (for embedded/subprocess use)                        │
├─────────────────────────────────────────────────────────────────┤
│  Session Manager                                                │
│  └── Manages Amplifier sessions (or mock mode without core)     │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
# Install with uv
uv pip install -e .

# Or with pip
pip install -e .
```

## Usage

### Run Server

```bash
# Start server on default port (4096)
amplifier-server serve

# Custom host/port
amplifier-server serve --host 0.0.0.0 --port 8080

# Development mode with auto-reload
amplifier-server serve --reload

# Enable Agent Client Protocol (ACP) endpoints
amplifier-server serve --acp-enabled
```

### Agent Client Protocol (ACP)

ACP is a standardized protocol for communication between code editors and AI coding agents.
Enable it with `--acp-enabled` to expose ACP endpoints for editor integrations (Zed, JetBrains, etc).

```bash
# Start with ACP enabled
amplifier-server serve --acp-enabled

# ACP endpoints will be available at:
# - POST /acp/rpc    - JSON-RPC endpoint for requests
# - GET  /acp/events - SSE endpoint for streaming notifications
# - WS   /acp/ws     - WebSocket for full-duplex communication
```

**ACP Protocol Flow:**

```bash
# 1. Initialize connection
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": 1,
      "clientInfo": {"name": "my-editor", "version": "1.0.0"}
    }
  }'

# 2. Create a session
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "session/new",
    "params": {
      "cwd": "/path/to/project",
      "mcpServers": []
    }
  }'

# 3. Submit a prompt
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "session/prompt",
    "params": {
      "sessionId": "<session-id>",
      "prompt": [{"type": "text", "text": "Hello!"}]
    }
  }'

# 4. Stream updates via SSE (in another terminal)
curl -N http://localhost:4096/acp/events
```

See: https://agentclientprotocol.com for protocol documentation.

### stdio Mode

```bash
# Run with stdio transport (for subprocess/IPC)
amplifier-server stdio
```

### Health Check

```bash
amplifier-server health
amplifier-server health --url http://localhost:8080
```

### SDK Usage

```python
from amplifier_server_app.sdk import create_client, create_embedded_client

# Remote mode (connect to running server)
client = create_client("http://localhost:4096")

# Embedded mode (in-process, no network)
client = create_embedded_client()

# Create session
session = await client.create_session(bundle="my-bundle")

# Send prompt and stream events
async for event in client.prompt(session.session_id, "Hello!"):
    print(f"Event: {event.type}")
    if event.final:
        break
```

## Protocol

The server uses a Command/Event protocol for all communication:

### Commands (Client → Server)

| Command | Description |
|---------|-------------|
| `ping` | Health check, returns `pong` |
| `capabilities` | Get server capabilities |
| `session.create` | Create new session |
| `session.get` | Get session info |
| `session.list` | List all sessions |
| `session.delete` | Delete session |
| `prompt.send` | Send prompt, streams events |
| `prompt.cancel` | Cancel running prompt |

### Events (Server → Client)

| Event | Description |
|-------|-------------|
| `connected` | Connection established |
| `pong` | Response to ping |
| `result` | Command completed successfully |
| `error` | Command failed |
| `ack` | Command received, processing |
| `content.delta` | Streaming content chunk |
| `content.end` | Streaming complete |
| `tool.call` | Tool invocation |
| `tool.result` | Tool completed |
| `approval.required` | User approval needed |

### Event Correlation

All events include:
- `id` - Unique event ID
- `correlation_id` - Links to originating command
- `timestamp` - ISO 8601 timestamp
- `final` - True if this is the last event for the command

## API Endpoints

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/ping` | Ping/pong |
| POST | `/session` | Create session |
| GET | `/session` | List sessions |
| GET | `/session/{id}` | Get session |
| DELETE | `/session/{id}` | Delete session |
| POST | `/session/{id}/prompt` | Send prompt (SSE stream) |

### Streaming Formats

The `/session/{id}/prompt` endpoint supports:
- `Accept: text/event-stream` → SSE format
- `Accept: application/x-ndjson` → NDJSON format

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=amplifier_server_app

# Type checking
pyright src/

# Linting
ruff check src/
ruff format src/
```

## Project Structure

```
src/amplifier_server_app/
├── protocol/          # Command/Event types
│   ├── commands.py    # Command definitions
│   ├── events.py      # Event definitions
│   └── handler.py     # Command processing
├── transport/         # Transport implementations
│   ├── base.py        # Abstract interfaces
│   ├── sse.py         # SSE streaming
│   └── stdio.py       # stdio for IPC
├── routes/            # HTTP routes
├── sdk/               # Client SDK
├── session.py         # Session management
└── app.py             # Starlette application
```

## License

MIT
