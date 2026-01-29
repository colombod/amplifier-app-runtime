# Amplifier Server

HTTP API server with event streaming for AI agent sessions.

## Overview

Amplifier Server provides the backend infrastructure for AI agent interactions:

- **HTTP REST API** for session management
- **Server-Sent Events (SSE)** for real-time streaming
- **WebSocket** for full-duplex communication
- **stdio transport** for embedded/CLI use
- **Protocol layer** with Command/Event types for client interoperability
- **SDK** for both remote and embedded (in-process) modes
- **Agent Client Protocol (ACP)** support for editor integrations

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Client Applications                              │
│  (amplifier-tui, web apps, IDE extensions, etc.)                    │
└─────────────────────────────────────────────────┬───────────────────┘
                                                  │
                        SDK (HTTP, WebSocket, or Embedded)
                                                  │
┌─────────────────────────────────────────────────┴───────────────────┐
│                    Amplifier Server                                 │
├─────────────────────────────────────────────────────────────────────┤
│  Protocol Layer                                                     │
│  ├── Commands (session.create, prompt.send, approval.respond, etc.) │
│  └── Events (result, error, content.delta, tool.call, etc.)         │
├─────────────────────────────────────────────────────────────────────┤
│  Transport Layer                                                    │
│  ├── HTTP + SSE (primary)                                           │
│  ├── WebSocket (full-duplex)                                        │
│  └── stdio (for embedded/subprocess use)                            │
├─────────────────────────────────────────────────────────────────────┤
│  Session Manager                                                    │
│  └── Manages Amplifier sessions with persistence                    │
└─────────────────────────────────────────────────────────────────────┘
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

### One-Shot Execution

```bash
# Execute a prompt and exit
amplifier-server run "What is 2+2?"

# With specific bundle
amplifier-server run "Analyze this code" --bundle foundation

# Continue existing session
amplifier-server run "And what about 3+3?" --session sess_abc123

# JSON output for scripting
amplifier-server run "List files" --json
```

### Session Management

```bash
# List saved sessions
amplifier-server session list

# Include agent sub-sessions
amplifier-server session list --all

# Show session details
amplifier-server session info sess_abc123

# Include transcript
amplifier-server session info sess_abc123 --transcript

# Resume a session
amplifier-server session resume sess_abc123

# Resume and continue conversation
amplifier-server session resume sess_abc123 "What else can you tell me?"

# Delete a session
amplifier-server session delete sess_abc123

# Clear all sessions
amplifier-server session clear --yes
```

### Bundle Management

```bash
# List available bundles
amplifier-server bundle list

# Show bundle information
amplifier-server bundle info foundation
```

### Provider Management

```bash
# List available providers
amplifier-server provider list

# Check if a provider is configured
amplifier-server provider check anthropic
```

### Configuration

```bash
# Show current configuration
amplifier-server config

# JSON output
amplifier-server config --json
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
session = await client.session.create(title="my-session")

# List sessions
sessions = await client.session.list()

# Get session by ID
session = await client.session.get(session_id)

# Send prompt
result = await client.session.prompt(
    session_id=session.session_id,
    parts=[MessagePart(type="text", text="Hello!")]
)

# Abort session
await client.session.abort(session_id)

# Delete session
await client.session.delete(session_id)

# Subscribe to event stream
async for event in client.event.subscribe():
    print(f"Event: {event.type}")
    if event.type == "session.idle":
        break

# Close client
await client.close()
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
| `approval.respond` | Respond to an approval request |

### Events (Server → Client)

| Event | Description |
|-------|-------------|
| `connected` | Connection established |
| `pong` | Response to ping |
| `result` | Command completed successfully |
| `error` | Command failed |
| `ack` | Command received, processing |
| `stream.start` | Streaming started |
| `stream.delta` | Streaming content chunk |
| `stream.end` | Streaming complete |
| `content.start` | Content block started |
| `content.delta` | Content chunk (text) |
| `content.end` | Content block complete |
| `thinking.delta` | Reasoning/thinking chunk |
| `thinking.end` | Reasoning complete |
| `tool.call` | Tool invocation started |
| `tool.result` | Tool completed |
| `tool.error` | Tool execution failed |
| `session.created` | Session was created |
| `session.updated` | Session was updated |
| `session.deleted` | Session was deleted |
| `session.state` | Session state changed |
| `approval.required` | User approval needed |
| `approval.resolved` | Approval was handled |
| `agent.spawned` | Sub-agent was spawned |
| `agent.completed` | Sub-agent completed |
| `notification` | Server notification |
| `heartbeat` | Connection heartbeat |

### Event Correlation

All events include:
- `id` - Unique event ID
- `correlation_id` - Links to originating command (optional for server-initiated events)
- `timestamp` - ISO 8601 timestamp
- `sequence` - Position in stream (for ordered events)
- `final` - True if this is the last event for the command

## API Endpoints

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/ping` | Ping/pong |
| GET | `/session` | List sessions |
| POST | `/session` | Create session |
| POST | `/session/cleanup` | Clean up old sessions (admin) |
| GET | `/session/{id}` | Get session |
| PATCH | `/session/{id}` | Update session |
| DELETE | `/session/{id}` | Delete session |
| POST | `/session/{id}/prompt` | Send prompt (SSE stream) |
| POST | `/session/{id}/prompt/sync` | Send prompt (non-streaming) |
| POST | `/session/{id}/abort` | Abort active session |
| GET | `/session/{id}/state` | Get session state |
| POST | `/session/{id}/approval` | Handle approval response |

### WebSocket Endpoint

| Path | Description |
|------|-------------|
| `/ws` | WebSocket for full-duplex communication |

### ACP Endpoints (when enabled)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/acp/rpc` | JSON-RPC endpoint |
| GET | `/acp/events` | SSE event stream |
| WS | `/acp/ws` | WebSocket endpoint |

### Streaming Formats

The `/session/{id}/prompt` endpoint supports:
- `Accept: text/event-stream` → SSE format
- `Accept: application/x-ndjson` → NDJSON format

## Development

```bash
# Install dev dependencies
uv sync --group dev

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
├── __init__.py            # Package initialization
├── app.py                 # Starlette application factory
├── cli.py                 # CLI commands (serve, run, session, bundle, etc.)
├── session.py             # Session management and lifecycle
├── session_store.py       # Session persistence
├── bundle_manager.py      # Bundle loading and management
├── bus.py                 # Event bus for internal communication
├── events.py              # Event handling
├── event_types.py         # Event type definitions
├── resolvers.py           # Configuration resolvers
├── project_utils.py       # Project utilities
├── acp/                   # Agent Client Protocol implementation
│   ├── __init__.py
│   ├── agent.py           # ACP agent adapter
│   ├── routes.py          # ACP HTTP routes
│   ├── transport.py       # ACP transport layer
│   └── types.py           # ACP type definitions
├── protocol/              # Command/Event protocol layer
│   ├── __init__.py
│   ├── commands.py        # Command definitions
│   ├── events.py          # Event definitions
│   └── handler.py         # Command processing
├── protocols/             # Protocol implementations
│   ├── __init__.py
│   ├── approval.py        # Approval flow handling
│   ├── display.py         # Display protocol
│   ├── hooks.py           # Hook integration
│   ├── spawn.py           # Agent spawning
│   └── streaming.py       # Streaming protocol
├── routes/                # HTTP route handlers
│   ├── __init__.py
│   ├── events.py          # SSE event routes
│   ├── health.py          # Health check routes
│   ├── protocol_adapter.py # Protocol-to-HTTP adapter
│   ├── session.py         # Session CRUD routes
│   └── websocket.py       # WebSocket handler
├── sdk/                   # Client SDK
│   ├── __init__.py
│   ├── client.py          # SDK client implementation
│   └── types.py           # SDK type definitions
└── transport/             # Transport implementations
    ├── __init__.py
    ├── base.py            # Abstract transport interface
    ├── sse.py             # SSE streaming
    ├── stdio.py           # stdio for IPC
    ├── stdio_adapter.py   # stdio protocol adapter
    └── websocket.py       # WebSocket transport

docs/
└── ACP.md                 # Agent Client Protocol documentation

tests/
├── conftest.py            # Test fixtures
├── test_session_store.py  # Session store tests
├── acp/                   # ACP tests
├── integration/           # Integration tests
└── unit/                  # Unit tests
```

## License

MIT
