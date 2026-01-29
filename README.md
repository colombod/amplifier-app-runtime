# Amplifier Runtime

A runtime server that exposes [Amplifier](https://github.com/microsoft/amplifier) AI agent capabilities through multiple transports: stdio (default), HTTP, WebSocket, Server-Sent Events (SSE), and the [Agent Client Protocol (ACP)](https://agentclientprotocol.com).

## Features

- **Stdio Mode (Default)** - For IDE subprocess integrations (Zed, JetBrains, VS Code, Neovim)
- **Agent Client Protocol (ACP)** - Standardized protocol for IDE integrations
- **HTTP Server Mode** - REST API, WebSocket, SSE for remote clients
- **Session Management** - Create, resume, and manage AI agent sessions
- **Real-time Streaming** - Stream agent responses as they're generated

## Installation

```bash
# Install with uv (recommended)
uv tool install git+https://github.com/microsoft/amplifier-app-runtime.git

# Or clone and install locally
git clone https://github.com/microsoft/amplifier-app-runtime.git
cd amplifier-app-runtime
uv pip install -e .
```

## Quick Start

### Stdio Mode (Default)

Best for: IDE integrations that spawn the agent as a local subprocess.

```bash
# Run in stdio mode (default)
amplifier-runtime
```

The agent communicates via JSON-RPC over stdin/stdout. All logs go to stderr.

**IDE Configuration Example (Zed):**

```json
{
  "assistant": {
    "provider": "acp",
    "acp": {
      "command": ["amplifier-runtime"]
    }
  }
}
```

### HTTP Server Mode

Best for: Web applications, remote IDE connections, multi-client scenarios.

```bash
# Start HTTP server
amplifier-runtime --http

# With custom host/port
amplifier-runtime --http --host 0.0.0.0 --port 8080

# With ACP endpoints enabled
amplifier-runtime --http --acp

# Development mode with auto-reload
amplifier-runtime --http --reload
```

**Endpoints (HTTP mode):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/acp/rpc` | POST | ACP JSON-RPC requests (when --acp) |
| `/acp/events` | GET | ACP SSE notifications (when --acp) |
| `/acp/ws` | WebSocket | ACP full-duplex communication (when --acp) |

### Health Check

```bash
# Check if HTTP server is running
amplifier-runtime --health

# Check specific URL
amplifier-runtime --health --health-url http://localhost:8080
```

## CLI Reference

```
amplifier-runtime                     # Stdio mode (default)
amplifier-runtime --http              # HTTP server mode
amplifier-runtime --http --port 8080  # HTTP with custom port
amplifier-runtime --http --acp        # HTTP with ACP endpoints
amplifier-runtime --health            # Check HTTP server health

amplifier-runtime session list        # List saved sessions
amplifier-runtime session info <id>   # Show session details
amplifier-runtime session resume <id> # Resume a session
amplifier-runtime session delete <id> # Delete a session
amplifier-runtime session clear --yes # Delete all sessions

amplifier-runtime bundle list         # List available bundles
amplifier-runtime bundle info <name>  # Show bundle details

amplifier-runtime provider list       # List providers
amplifier-runtime provider check <n>  # Check provider status

amplifier-runtime config              # Show configuration
```

## ACP Protocol Examples

### Initialize Connection (HTTP mode with --acp)

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-01-07",
      "clientInfo": {"name": "my-editor", "version": "1.0"},
      "clientCapabilities": {}
    }
  }'
```

### Create Session

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "session/new",
    "params": {"cwd": "/path/to/project"}
  }'
```

### Send Prompt

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "session/prompt",
    "params": {
      "sessionId": "acp_abc123",
      "prompt": [{"type": "text", "text": "Hello!"}]
    }
  }'
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Client Applications                             │
│  (Zed, VS Code, JetBrains, Neovim, Web Apps, CLI tools)             │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    ACP Protocol (JSON-RPC 2.0)
                                │
┌───────────────────────────────┴─────────────────────────────────────┐
│                      Amplifier Runtime                               │
├─────────────────────────────────────────────────────────────────────┤
│  Transports                                                          │
│  ├── stdio (default - subprocess/IPC)                               │
│  ├── HTTP + SSE (--http flag)                                       │
│  └── WebSocket (--http flag)                                        │
├─────────────────────────────────────────────────────────────────────┤
│  ACP Agent                                                           │
│  ├── Protocol handling (initialize, session/*, etc.)                │
│  ├── Client capability negotiation                                  │
│  └── Session update streaming                                       │
├─────────────────────────────────────────────────────────────────────┤
│  Session Manager                                                     │
│  └── Amplifier sessions (LLM, tools, context)                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Client-Side Tools (ACP Capabilities)

When clients advertise capabilities, the agent gains access to IDE-provided tools:

| Client Capability | Agent Tool | Description |
|-------------------|------------|-------------|
| `terminal: true` | `ide_terminal` | Run commands in IDE terminal |
| `fs.read_text_file: true` | `ide_read_file` | Read files through IDE |
| `fs.write_text_file: true` | `ide_write_file` | Write files through IDE |

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest

# Type checking
uv run pyright src/

# Linting and formatting
uv run ruff check src/
uv run ruff format src/
```

## Project Structure

```
src/amplifier_app_runtime/
├── acp/               # Agent Client Protocol implementation
│   ├── agent.py       # ACP agent (SDK-based)
│   ├── routes.py      # HTTP/SSE/WebSocket endpoints
│   ├── tools.py       # Client-side tools (terminal, filesystem)
│   └── __main__.py    # Stdio entry point
├── protocol/          # Internal protocol types
├── transport/         # Transport implementations
├── routes/            # HTTP API routes
├── sdk/               # Client SDK
├── session.py         # Session management
└── app.py             # Starlette application
```

## Documentation

- [ACP Protocol Details](docs/ACP.md) - Complete ACP implementation documentation
- [Agent Client Protocol](https://agentclientprotocol.com) - Official ACP specification

## License

MIT
