# Amplifier Server

HTTP API server with event streaming for AI agent sessions.

## Overview

Amplifier Server provides the backend infrastructure for AI agent interactions:

- **HTTP REST API** for session management
- **Server-Sent Events (SSE)** for real-time updates  
- **Transport abstraction** designed for future HTTP/3 + WebTransport
- **SDK** for both remote and embedded (in-process) modes

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Applications                       │
│  (amplifier-tui, web apps, IDE extensions, etc.)            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                    SDK (HTTP or Embedded)
                              │
┌─────────────────────────────┴───────────────────────────────┐
│                    Amplifier Server                          │
├─────────────────────────────────────────────────────────────┤
│  HTTP Server (Starlette)                                    │
│  ├── /session     - Session CRUD + prompts                  │
│  ├── /event       - SSE event stream                        │
│  └── /health      - Health check                            │
├─────────────────────────────────────────────────────────────┤
│  Event Bus                                                   │
│  └── publish() ──► [subscribers] ──► SSE stream             │
├─────────────────────────────────────────────────────────────┤
│  Transport Layer                                             │
│  ├── SSE (current)                                          │
│  └── HTTP/3 + WebTransport (future)                         │
└─────────────────────────────────────────────────────────────┘
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
```

### Health Check

```bash
amplifier-server health
amplifier-server health --url http://localhost:8080
```

### SDK Usage

```python
from amplifier_server.sdk import create_client, create_embedded_client

# Remote mode (connect to running server)
client = create_client("http://localhost:4096")

# Embedded mode (in-process, no network)
client = create_embedded_client()

# Create session
session = await client.session.create(title="My Session")

# Send prompt
await client.session.prompt(
    session.id,
    parts=[{"type": "text", "text": "Hello!"}]
)

# Subscribe to events
async for event in client.event.subscribe():
    print(f"Event: {event.type}")
    if event.type == "session.idle":
        break
```

## API Endpoints

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/session` | List sessions |
| POST | `/session` | Create session |
| GET | `/session/{id}` | Get session |
| PATCH | `/session/{id}` | Update session |
| DELETE | `/session/{id}` | Delete session |
| POST | `/session/{id}/message` | Send prompt |
| GET | `/session/{id}/message` | Get messages |
| POST | `/session/{id}/abort` | Abort session |

### Events

| Method | Path | Description |
|--------|------|-------------|
| GET | `/event` | SSE event stream |

### System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |

## Event Types

Events are streamed via SSE on `/event`:

```
server.connected    - Connection established
server.heartbeat    - Keep-alive ping
session.created     - Session created
session.updated     - Session metadata changed
session.deleted     - Session deleted
session.idle        - Session finished processing
session.error       - Error occurred
message.created     - New message
message.part.updated - Streaming content update
tool.started        - Tool execution started
tool.completed      - Tool execution finished
approval.requested  - Approval needed
approval.resolved   - Approval granted/denied
```

## Transport Abstraction

The transport layer is designed for future HTTP/3 + WebTransport support:

```python
from amplifier_server.transport import TransportConfig, SSEEventStream

# Current: SSE over HTTP/2
config = TransportConfig(
    base_url="http://localhost:4096",
    reconnect=True,
    reconnect_delay=1.0,
)

# Future: HTTP/3 (when available)
config = TransportConfig(
    base_url="https://localhost:4096",
    prefer_http3=True,
)
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Type checking
pyright src/

# Linting
ruff check src/
ruff format src/
```

## License

MIT
