# Agent Client Protocol (ACP) Support

Amplifier Server implements the [Agent Client Protocol (ACP)](https://agentclientprotocol.com) for standardized communication with code editors and AI coding tools.

## Table of Contents

- [Official Documentation](#official-documentation)
- [Quick Start](#quick-start)
- [Running Modes](#running-modes)
- [Protocol Usage](#acp-protocol-usage)
- [Client-Side Tools](#client-side-tools)
- [IDE Configuration](#editor-configuration)
- [Troubleshooting](#troubleshooting)

## Official Documentation

- **Website:** [agentclientprotocol.com](https://agentclientprotocol.com)
- **Introduction:** [Get Started](https://agentclientprotocol.com/get-started/introduction)
- **Protocol Specification:** [Specification](https://agentclientprotocol.com/specification)
- **GitHub:** [anthropics/acp](https://github.com/anthropics/acp)
- **Python SDK:** [agentclientprotocol/python-sdk](https://github.com/agentclientprotocol/python-sdk)

## Overview

ACP is a standardized protocol for communication between code editors and AI coding agents. It enables:

- **Zed** - Native ACP support
- **JetBrains AI Assistant** - ACP-compliant
- **Neovim plugins** - Via ACP adapters
- **VS Code extensions** - Custom ACP clients

**Protocol Version:** `2025-01-07`

## Quick Start

```bash
# Install
git clone https://github.com/colombod/amplifier-server-app.git
cd amplifier-server-app
uv pip install -e .

# Run with ACP enabled
amplifier-server serve --acp-enabled

# Test it works
curl http://localhost:4096/health
# {"status":"ok"}
```

## Implementation

This implementation uses the [official ACP Python SDK](https://github.com/agentclientprotocol/python-sdk) for protocol compliance:

- `AmplifierAgent` - SDK-based `Agent` interface implementation
- `conn.session_update()` - Proper streaming update delivery
- `run_agent()` - SDK's stdio transport handler

**Key modules:**

| Module | Description |
|--------|-------------|
| `amplifier_server_app.acp.agent` | Core ACP agent implementation |
| `amplifier_server_app.acp.routes` | HTTP/SSE/WebSocket endpoints |
| `amplifier_server_app.acp.tools` | Client-side tools (terminal, filesystem) |
| `amplifier_server_app.acp.__main__` | Stdio entry point with protocol isolation |

## Installation

```bash
# Clone the repository
git clone https://github.com/colombod/amplifier-server-app.git
cd amplifier-server-app

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## Running the Server

### HTTP Mode (Remote Agents)

Start the server to expose ACP endpoints over HTTP:

```bash
# Default port (4096)
amplifier-server serve

# Custom port
amplifier-server serve --port 8080

# Custom host and port
amplifier-server serve --host 0.0.0.0 --port 8080

# Development mode with auto-reload
amplifier-server serve --reload
```

The server exposes these ACP endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/acp/rpc` | POST | JSON-RPC 2.0 requests |
| `/acp/events` | GET | Server-Sent Events for notifications |
| `/acp/ws` | WebSocket | Full-duplex communication |

### Verify Server is Running

```bash
# Health check
curl http://localhost:4096/health
# Returns: {"status":"ok"}
```

## ACP Protocol Usage

### Initialize Connection

Before any other operation, initialize the ACP connection:

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-01-07",
      "clientInfo": {
        "name": "my-editor",
        "version": "1.0.0"
      },
      "clientCapabilities": {}
    }
  }'
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "protocolVersion": "2025-01-07",
    "agentInfo": {
      "name": "amplifier-server",
      "version": "0.1.0"
    },
    "agentCapabilities": {
      "loadSession": true,
      "mcpCapabilities": {
        "http": false,
        "sse": true
      },
      "promptCapabilities": {
        "audio": false,
        "embeddedContext": true,
        "image": false
      }
    },
    "authMethods": []
  }
}
```

### Create a New Session

```bash
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
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "2",
  "result": {
    "sessionId": "acp_abc123def456",
    "modes": {
      "availableModes": [
        {
          "id": "default",
          "name": "Default",
          "description": "Default agent mode"
        }
      ],
      "currentMode": "default"
    }
  }
}
```

### Load Existing Session

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "session/load",
    "params": {
      "sessionId": "acp_abc123def456",
      "cwd": "/path/to/your/project"
    }
  }'
```

### Send a Prompt

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "4",
    "method": "session/prompt",
    "params": {
      "sessionId": "acp_abc123def456",
      "prompt": [
        {
          "type": "text",
          "text": "Hello, can you help me with my code?"
        }
      ]
    }
  }'
```

### Cancel a Prompt

Send as a notification (no `id` field):

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "session/cancel",
    "params": {
      "sessionId": "acp_abc123def456"
    }
  }'
```

## WebSocket Usage

For full-duplex communication, connect via WebSocket:

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
        response = await ws.recv()
        print('Initialized:', response)
        
        # Create session
        await ws.send(json.dumps({
            'jsonrpc': '2.0',
            'id': '2',
            'method': 'session/new',
            'params': {'cwd': '/tmp'}
        }))
        response = await ws.recv()
        session = json.loads(response)
        session_id = session['result']['sessionId']
        print('Session created:', session_id)
        
        # Send prompt and receive streaming updates
        await ws.send(json.dumps({
            'jsonrpc': '2.0',
            'id': '3',
            'method': 'session/prompt',
            'params': {
                'sessionId': session_id,
                'prompt': [{'type': 'text', 'text': 'Hello!'}]
            }
        }))
        
        # Receive response and any notifications
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(msg)
                print('Received:', data)
                
                # Check if this is the final response
                if 'result' in data and data.get('id') == '3':
                    break
            except asyncio.TimeoutError:
                break

asyncio.run(acp_session())
```

## SSE Events Stream

For receiving notifications via Server-Sent Events:

```bash
# Connect to SSE stream (keep connection open)
curl -N http://localhost:4096/acp/events
```

Events are delivered in SSE format:
```
data: {"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"acp_123","type":"agent_message_chunk","data":{"content":[{"type":"text","text":"Hello"}]}}}

data: {"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"acp_123","type":"tool_call_start","data":{"id":"tc_1","name":"read_file","arguments":{"path":"/tmp/test.txt"}}}}
```

## ACP Methods Reference

### Requests (require response)

| Method | Description |
|--------|-------------|
| `initialize` | Negotiate capabilities and protocol version |
| `session/new` | Create a new agent session |
| `session/load` | Resume an existing session |
| `session/prompt` | Send a prompt to the agent |
| `session/set_mode` | Change agent mode |

### Notifications (no response)

| Method | Description |
|--------|-------------|
| `session/cancel` | Cancel ongoing prompt execution |

### Server Notifications

| Method | Description |
|--------|-------------|
| `session/update` | Streaming content, tool calls, thoughts |

## Session Update Types

The `session/update` notification includes a `type` field:

| Type | Description |
|------|-------------|
| `agent_message_chunk` | Streaming text content |
| `tool_call_start` | Tool invocation started |
| `tool_call_end` | Tool invocation completed |
| `thought_chunk` | Agent thinking/reasoning |

## Editor Configuration

### Zed

Add to your Zed settings (`~/.config/zed/settings.json`):

```json
{
  "assistant": {
    "provider": "acp",
    "acp": {
      "endpoint": "http://localhost:4096/acp/rpc",
      "events_endpoint": "http://localhost:4096/acp/events"
    }
  }
}
```

### Generic ACP Client

Any ACP-compliant client can connect using:

- **JSON-RPC endpoint:** `http://localhost:4096/acp/rpc`
- **SSE endpoint:** `http://localhost:4096/acp/events`
- **WebSocket endpoint:** `ws://localhost:4096/acp/ws`

## Capabilities

The server advertises these capabilities:

| Capability | Value | Description |
|------------|-------|-------------|
| `loadSession` | `true` | Can resume previous sessions |
| `mcpCapabilities.sse` | `true` | Supports SSE for MCP |
| `promptCapabilities.embeddedContext` | `true` | Accepts embedded context in prompts |
| `promptCapabilities.audio` | `false` | Audio input not supported |
| `promptCapabilities.image` | `false` | Image input not yet supported |

## Error Handling

ACP uses standard JSON-RPC 2.0 error codes:

| Code | Meaning |
|------|---------|
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |
| `-32001` | Session not found |

Example error response:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "error": {
    "code": -32001,
    "message": "Session not found: acp_invalid"
  }
}
```

## Troubleshooting

### Server won't start

```bash
# Check if port is in use
lsof -i :4096

# Try a different port
amplifier-server serve --port 8080
```

### Connection refused

```bash
# Verify server is running
curl http://localhost:4096/health

# Check server logs
amplifier-server serve 2>&1 | tee server.log
```

### WebSocket connection fails

Ensure you're using the correct URL scheme:
- HTTP server: `ws://localhost:4096/acp/ws`
- HTTPS server: `wss://localhost:4096/acp/ws`

## Stdio Mode (Local Agents)

For editors that spawn agents as local subprocesses, use stdio mode:

```bash
# Run agent over stdio (for editor subprocess integration)
python -m amplifier_server_app.acp
```

The agent communicates via JSON-RPC over stdin/stdout, with logs to stderr.

### CRITICAL: Stdio Protocol Isolation

When using stdio transport, **stdout is exclusively reserved for JSON-RPC messages**. The entry point (`python -m amplifier_server_app.acp`) implements several layers of protection:

1. **JSON-RPC Stdout Filter**: Only valid JSON objects starting with `{` are allowed through to stdout. Any non-JSON content (log messages, print statements, etc.) is automatically redirected to stderr with a `[stdout-filtered]` prefix.

2. **Logging Configuration**: All Python logging is configured to use stderr before any other modules are imported.

3. **Route Namespacing**: When ACP is enabled via `--acp-enabled`, Amplifier's internal HTTP/WS/SSE routes are namespaced under `/amplifier/` to prevent conflicts with ACP routes.

This ensures the ACP protocol is never corrupted by stray output.

### Architecture: ACP vs Amplifier Transports

```
┌─────────────────────────────────────────────────────────────────┐
│                     ACP ENABLED MODE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  STDIO (stdin/stdout)                                          │
│  └── Exclusively owned by ACP JSON-RPC protocol                │
│      └── JsonRpcStdoutFilter ensures only valid JSON passes    │
│                                                                 │
│  STDERR                                                        │
│  └── All logging, diagnostics, filtered content                │
│                                                                 │
│  HTTP Routes:                                                   │
│  ├── /health              - Health check (shared)              │
│  ├── /acp/rpc             - ACP JSON-RPC endpoint              │
│  ├── /acp/events          - ACP SSE notifications              │
│  ├── /acp/ws              - ACP WebSocket                      │
│  └── /amplifier/*         - Amplifier routes (namespaced)      │
│      ├── /amplifier/event - Amplifier SSE                      │
│      ├── /amplifier/ws    - Amplifier WebSocket                │
│      └── /amplifier/v1/*  - Amplifier protocol routes          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

This separation ensures that:
- ACP protocol messages never mix with Amplifier's internal transport
- Amplifier sessions forward events through ACP's `session/update` notifications
- HTTP routes don't conflict between the two systems

## Client-Side Tools

When clients advertise capabilities during initialization, the agent gains access to IDE-provided tools. This enables the agent to interact with the IDE environment directly.

### Available Capabilities

| Client Capability | Agent Tool | Description |
|-------------------|------------|-------------|
| `terminal: true` | `ide_terminal` | Run commands in IDE terminal |
| `fs.read_text_file: true` | `ide_read_file` | Read files through IDE |
| `fs.write_text_file: true` | `ide_write_file` | Write files through IDE |

### Advertising Capabilities

```bash
curl -X POST http://localhost:4096/acp/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-01-07",
      "clientInfo": {"name": "my-ide", "version": "1.0"},
      "clientCapabilities": {
        "terminal": true,
        "fs": {
          "read_text_file": true,
          "write_text_file": true
        }
      }
    }
  }'
```

### Implementing Client Methods

When the agent uses these tools, it calls back to the client. Clients must implement:

**Terminal Methods:**
- `terminal/create` - Create a terminal and run command
- `terminal/output` - Get terminal output
- `terminal/wait_for_exit` - Wait for command completion
- `terminal/release` - Release terminal resources

**Filesystem Methods:**
- `fs/read_text_file` - Read file content
- `fs/write_text_file` - Write file content

### Python Client Example

```python
from acp import Client, connect_to_agent
from acp.schema import (
    ClientCapabilities,
    FileSystemCapability,
    CreateTerminalResponse,
    ReadTextFileResponse,
    TerminalOutputResponse,
    WaitForTerminalExitResponse,
)

class MyIDEClient(Client):
    """Client that provides terminal and filesystem to the agent."""
    
    # Terminal capability
    async def create_terminal(self, session_id, command, args, cwd=None, **kwargs):
        """Create terminal and run command."""
        terminal_id = f"term_{uuid.uuid4().hex[:8]}"
        # Run command in your IDE's terminal...
        return CreateTerminalResponse(terminal_id=terminal_id)
    
    async def terminal_output(self, session_id, terminal_id, **kwargs):
        """Get output from terminal."""
        output = "command output here"
        return TerminalOutputResponse(output=output)
    
    async def wait_for_terminal_exit(self, session_id, terminal_id, **kwargs):
        """Wait for terminal to complete."""
        return WaitForTerminalExitResponse(exit_code=0)
    
    async def release_terminal(self, session_id, terminal_id, **kwargs):
        """Release terminal resources."""
        pass
    
    # Filesystem capability
    async def read_text_file(self, session_id, path, line=None, limit=None, **kwargs):
        """Read file content."""
        with open(path) as f:
            content = f.read()
        return ReadTextFileResponse(content=content)
    
    async def write_text_file(self, session_id, path, content, **kwargs):
        """Write file content."""
        with open(path, 'w') as f:
            f.write(content)
    
    # Required: receive streaming updates
    async def session_update(self, session_id, update, **kwargs):
        """Receive streaming updates from the agent."""
        print(f"Update: {type(update).__name__}")

# Connect with capabilities
client = MyIDEClient()
capabilities = ClientCapabilities(
    terminal=True,
    fs=FileSystemCapability(read_text_file=True, write_text_file=True)
)
```

## Testing

Run the end-to-end ACP tests:

```bash
# Basic ACP protocol test (initialize, session, prompt)
uv run python tests/acp/test_e2e_acp.py

# Client-side tools test (terminal, read_file, write_file)
uv run python tests/acp/test_e2e_acp_tools.py
```

These tests:
1. Spawn the agent as a subprocess (stdio transport)
2. Use the official ACP SDK client
3. Run full protocol flow: initialize → session/new → prompt → response
4. Verify streaming updates and tool callbacks work correctly
