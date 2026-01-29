# Amplifier Server

A server application that exposes [Amplifier](https://github.com/microsoft/amplifier) AI agent capabilities through multiple transports: HTTP REST API, WebSocket, Server-Sent Events (SSE), and the [Agent Client Protocol (ACP)](https://agentclientprotocol.com).

## Features

- **Agent Client Protocol (ACP)** - Standardized protocol for IDE integrations (Zed, JetBrains, VS Code, Neovim)
- **Multiple Transports** - HTTP, WebSocket, SSE, and stdio for different use cases
- **Session Management** - Create, resume, and manage AI agent sessions
- **Real-time Streaming** - Stream agent responses as they're generated
- **Client-side Tools** - IDE can provide terminal, filesystem, and other capabilities to the agent

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/colombod/amplifier-server-app.git
cd amplifier-server-app

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

### Run the Server

```bash
# Start HTTP server with ACP support
amplifier-server serve --acp-enabled

# Server is now running at http://localhost:4096
```

### Verify It's Working

```bash
# Health check
curl http://localhost:4096/health
# Returns: {"status":"ok"}

# Initialize ACP connection
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-01-07",
      "clientInfo": {"name": "test", "version": "1.0"},
      "clientCapabilities": {}
    }
  }'
```

## Usage Modes

### 1. HTTP Mode (Remote Server)

Best for: Web applications, remote IDE connections, multi-client scenarios.

```bash
# Start server
amplifier-server serve --acp-enabled

# Or with custom host/port
amplifier-server serve --acp-enabled --host 0.0.0.0 --port 8080

# Development mode with auto-reload
amplifier-server serve --acp-enabled --reload
```

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/acp/rpc` | POST | ACP JSON-RPC requests |
| `/acp/events` | GET | ACP SSE notifications |
| `/acp/ws` | WebSocket | ACP full-duplex communication |

### 2. Stdio Mode (Local Subprocess)

Best for: IDE integrations that spawn the agent as a local subprocess.

```bash
# Run agent over stdio
python -m amplifier_server_app.acp
```

The agent communicates via JSON-RPC over stdin/stdout. All logs go to stderr.

**IDE Configuration Example (Zed):**

```json
{
  "assistant": {
    "provider": "acp",
    "acp": {
      "command": ["python", "-m", "amplifier_server_app.acp"]
    }
  }
}
```

## ACP Protocol Examples

### Complete Session Flow

```bash
# 1. Initialize connection
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

# Response:
# {
#   "jsonrpc": "2.0",
#   "id": "1",
#   "result": {
#     "protocolVersion": 1,
#     "agentInfo": {"name": "amplifier-server", "version": "0.1.0"},
#     "agentCapabilities": {
#       "loadSession": true,
#       "mcpCapabilities": {"http": false, "sse": true},
#       "promptCapabilities": {"audio": false, "embeddedContext": true, "image": false}
#     }
#   }
# }

# 2. Create a new session
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "session/new",
    "params": {
      "cwd": "/path/to/your/project"
    }
  }'

# Response:
# {
#   "jsonrpc": "2.0",
#   "id": "2",
#   "result": {
#     "sessionId": "acp_abc123def456",
#     "modes": {
#       "availableModes": [{"id": "default", "name": "Default"}],
#       "currentMode": "default"
#     }
#   }
# }

# 3. Send a prompt
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "session/prompt",
    "params": {
      "sessionId": "acp_abc123def456",
      "prompt": [{"type": "text", "text": "Hello! Can you help me with my code?"}]
    }
  }'

# 4. Cancel a running prompt (notification - no id)
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "session/cancel",
    "params": {"sessionId": "acp_abc123def456"}
  }'
```

### WebSocket Client (Python)

```python
import asyncio
import json
import websockets

async def acp_session():
    async with websockets.connect('ws://localhost:4096/acp/ws') as ws:
        # Initialize
        await ws.send(json.dumps({
            'jsonrpc': '2.0',
            'id': '1',
            'method': 'initialize',
            'params': {
                'protocolVersion': '2025-01-07',
                'clientInfo': {'name': 'my-client', 'version': '1.0'},
                'clientCapabilities': {}
            }
        }))
        init_response = json.loads(await ws.recv())
        print('Initialized:', init_response)
        
        # Create session
        await ws.send(json.dumps({
            'jsonrpc': '2.0',
            'id': '2',
            'method': 'session/new',
            'params': {'cwd': '/tmp'}
        }))
        session_response = json.loads(await ws.recv())
        session_id = session_response['result']['sessionId']
        print('Session created:', session_id)
        
        # Send prompt
        await ws.send(json.dumps({
            'jsonrpc': '2.0',
            'id': '3',
            'method': 'session/prompt',
            'params': {
                'sessionId': session_id,
                'prompt': [{'type': 'text', 'text': 'Hello!'}]
            }
        }))
        
        # Receive streaming updates
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                data = json.loads(msg)
                print('Received:', data)
                
                # Check for final response
                if 'result' in data and data.get('id') == '3':
                    break
            except asyncio.TimeoutError:
                break

asyncio.run(acp_session())
```

### Client with Terminal & Filesystem Capabilities

When clients advertise capabilities, the agent can use IDE-provided tools:

```python
from acp import Client, connect_to_agent
from acp.schema import (
    ClientCapabilities,
    FileSystemCapability,
    CreateTerminalResponse,
    ReadTextFileResponse,
)

class MyIDEClient(Client):
    """Client that provides terminal and filesystem to the agent."""
    
    async def create_terminal(self, session_id, command, args, **kwargs):
        """Agent wants to run a command in the IDE's terminal."""
        terminal_id = "term_1"
        # Create terminal in your IDE...
        return CreateTerminalResponse(terminal_id=terminal_id)
    
    async def read_text_file(self, session_id, path, **kwargs):
        """Agent wants to read a file through the IDE."""
        content = open(path).read()
        return ReadTextFileResponse(content=content)
    
    async def write_text_file(self, session_id, path, content, **kwargs):
        """Agent wants to write a file through the IDE."""
        with open(path, 'w') as f:
            f.write(content)
    
    async def session_update(self, session_id, update, **kwargs):
        """Receive streaming updates from the agent."""
        print(f"Update: {update}")

# Connect with capabilities
capabilities = ClientCapabilities(
    terminal=True,
    fs=FileSystemCapability(read_text_file=True, write_text_file=True)
)

# The agent will now have access to ide_terminal, ide_read_file, ide_write_file tools
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Client Applications                         │
│  (Zed, VS Code, JetBrains, Neovim, Web Apps, CLI tools)         │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                    ACP Protocol (JSON-RPC 2.0)
                                │
┌───────────────────────────────┴─────────────────────────────────┐
│                      Amplifier Server                            │
├─────────────────────────────────────────────────────────────────┤
│  Transports                                                      │
│  ├── HTTP + SSE (remote clients)                                │
│  ├── WebSocket (full-duplex)                                    │
│  └── stdio (subprocess/IPC)                                     │
├─────────────────────────────────────────────────────────────────┤
│  ACP Agent                                                       │
│  ├── Protocol handling (initialize, session/*, etc.)            │
│  ├── Client capability negotiation                              │
│  └── Session update streaming                                   │
├─────────────────────────────────────────────────────────────────┤
│  Session Manager                                                 │
│  └── Amplifier sessions (LLM, tools, context)                   │
└─────────────────────────────────────────────────────────────────┘
```

## Client-Side Tools (ACP Capabilities)

When clients advertise capabilities, the agent gains access to IDE-provided tools:

| Client Capability | Agent Tool | Description |
|-------------------|------------|-------------|
| `terminal: true` | `ide_terminal` | Run commands in IDE terminal |
| `fs.read_text_file: true` | `ide_read_file` | Read files through IDE |
| `fs.write_text_file: true` | `ide_write_file` | Write files through IDE |

This enables the agent to interact with the IDE environment directly.

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest

# Run ACP end-to-end tests
uv run python tests/acp/test_e2e_acp.py
uv run python tests/acp/test_e2e_acp_tools.py

# Type checking
uv run pyright src/

# Linting and formatting
uv run ruff check src/
uv run ruff format src/
```

## Project Structure

```
src/amplifier_server_app/
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
- [ACP Feature Analysis](docs/ACP_FEATURE_ANALYSIS.md) - Feature comparison and analysis
- [Agent Client Protocol](https://agentclientprotocol.com) - Official ACP specification

## License

MIT
