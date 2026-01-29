# ACP Feature Analysis: Missing Capabilities & Prioritization

**Branch:** `feature/acp-client-capabilities`  
**Date:** 2026-01-29

## Executive Summary

Our current ACP implementation covers the **Agent-side methods** well, but we're not utilizing the **Client-side capabilities** that the protocol exposes. These client capabilities allow the agent to request services FROM the client (IDE/editor), enabling powerful integrations.

### Critical Architecture Understanding

**Client-side operations execute ON THE IDE's MACHINE, not on the Amplifier server.**

```
┌─────────────────────────────────────────────────────────────────────┐
│                         IDE (Client Machine)                        │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────────────────────────────┐│
│  │  Editor UI      │    │  Client-Side Operations                 ││
│  │                 │    │  - Terminal: runs shell ON THIS MACHINE ││
│  │  - Shows live   │    │  - File System: reads/writes HERE       ││
│  │    terminal     │    │  - Includes unsaved editor buffers!     ││
│  │    output       │    │                                         ││
│  └─────────────────┘    └─────────────────────────────────────────┘│
│           ▲                              ▲                          │
│           │ Display                      │ Execute                  │
│           │                              │                          │
│  ┌────────┴──────────────────────────────┴────────────────────────┐│
│  │                     ACP Client                                  ││
│  │  Handles: terminal/create, fs/read_text_file, etc.             ││
│  └─────────────────────────────────────────────────────────────────┘│
│                              ▲                                      │
└──────────────────────────────┼──────────────────────────────────────┘
                               │ JSON-RPC (stdio/HTTP/WebSocket)
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                              ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                     ACP Agent (Amplifier)                       ││
│  │  - Requests terminal creation → IDE runs command                ││
│  │  - Requests file read → IDE returns content (+ unsaved state)   ││
│  │  - Gets output back → Feeds to LLM                              ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                     │
│                    Amplifier Server Machine                         │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Insight**: We need **TWO SETS of tools** - one for client-side (IDE) operations and one for server-side (Amplifier) operations.

---

## Tool Architecture: Client-Side vs Server-Side

### The Two-Tool Pattern

| Domain | Server-Side Tool | Client-Side Tool | When to Use Client |
|--------|------------------|------------------|-------------------|
| **Terminal** | `bash` | `ide_terminal` | User's project commands, needs user's env |
| **File Read** | `read_file` | `ide_read_file` | User's files, need unsaved buffer state |
| **File Write** | `write_file` | `ide_write_file` | User's files, editor should track changes |

### When to Use Each

**Client-Side Tools (`ide_*`)** - Operations on the USER's machine:
- "Run my tests" → `ide_terminal` (uses user's node_modules, PATH, etc.)
- "Read this file" → `ide_read_file` (gets unsaved editor buffer!)
- "Fix this file" → `ide_write_file` (editor tracks the change)
- User sees live terminal output in their IDE
- Commands have access to user's credentials, env vars, tools

**Server-Side Tools (existing)** - Operations on AMPLIFIER's machine:
- Agent's internal operations
- Downloading/processing files locally
- Running agent's own scripts
- Operations that don't need user's environment

### LLM Tool Selection

The LLM must understand this distinction. Tool descriptions should be clear:

```python
# Client-side tool
ide_terminal = Tool(
    name="ide_terminal",
    description="""Execute a command in the user's IDE terminal.
    
    The command runs ON THE USER'S MACHINE in their IDE's terminal panel.
    User sees live output. Use this for:
    - Running user's project commands (npm test, cargo build, etc.)
    - Commands that need user's environment (PATH, credentials, etc.)
    - When user should see the output live
    
    Do NOT use for agent's internal operations - use 'bash' instead.""",
)

# Server-side tool  
bash = Tool(
    name="bash",
    description="""Execute a command on the agent's server.
    
    The command runs WHERE AMPLIFIER IS RUNNING, not on user's machine.
    Use this for:
    - Agent's internal operations
    - Processing files the agent has downloaded
    - Operations that don't need user's environment
    
    For user's project commands, use 'ide_terminal' instead.""",
)
```

---

## Current Implementation Status

### Agent Methods (Client → Agent) ✅ Complete

| Method | Status | Notes |
|--------|--------|-------|
| `initialize` | ✅ Full | Capability negotiation works |
| `new_session` | ✅ Full | Creates Amplifier session |
| `load_session` | ✅ Full | Loads existing session |
| `list_sessions` | ✅ Full | Lists cached sessions |
| `prompt` | ✅ Full | Executes prompts, streams updates |
| `set_session_mode` | ✅ Basic | Stores mode but doesn't affect behavior |
| `set_session_model` | ⚠️ Stub | Logs but doesn't switch model |
| `authenticate` | ⚠️ Stub | Returns empty response |
| `fork_session` | ✅ Basic | Creates new session (no context copy) |
| `resume_session` | ✅ Full | Delegates to load_session |
| `cancel` | ✅ Full | Cancels execution |
| `ext_method/notification` | ⚠️ Stub | Logs only |

### Client Methods (Agent → Client) ❌ Not Utilized

| Method | Status | Impact |
|--------|--------|--------|
| `create_terminal` | ❌ Not used | HIGH - Execute on user's machine |
| `terminal_output` | ❌ Not used | HIGH - Get command output |
| `wait_for_terminal_exit` | ❌ Not used | HIGH - Process control |
| `kill_terminal` | ❌ Not used | MEDIUM - Process control |
| `release_terminal` | ❌ Not used | MEDIUM - Cleanup |
| `read_text_file` | ❌ Not used | HIGH - Includes unsaved state! |
| `write_text_file` | ❌ Not used | HIGH - Editor-tracked writes |
| `request_permission` | ❌ Not used | MEDIUM - Native approval UI |

---

## Priority 1: Client Terminal (`ide_terminal` tool)

### What It Is

A tool that executes commands **on the IDE's machine** via the ACP terminal protocol. The IDE:
1. Creates a shell process on its machine
2. Runs the command
3. Streams output back to agent AND displays in IDE's terminal panel
4. Agent gets output to feed to LLM

### Protocol Flow (from ACP spec)

```
Agent (Amplifier)                        Client (IDE)
      |                                       |
      |-- terminal/create ------------------>|
      |   {command: "npm", args: ["test"],   |
      |    cwd: "/user/project"}             |
      |                                       | IDE creates shell process
      |<-- {terminalId: "term_xyz"} ---------|
      |                                       |
      |-- session/update ------------------->| (optional: embed in tool call)
      |   {toolCall: {content: [{type:       |
      |    "terminal", terminalId: "..."}]}} |
      |                                       | User sees live output!
      |                                       |
      |-- terminal/wait_for_exit ----------->|
      |                                       | (blocks until done)
      |<-- {exitCode: 0} --------------------|
      |                                       |
      |-- terminal/output ------------------>|
      |<-- {output: "...", truncated: false} |
      |                                       |
      |-- terminal/release ----------------->|
      |                                       | IDE cleans up
```

### Key Features

1. **Non-blocking creation**: `terminal/create` returns immediately with `terminalId`
2. **Embed in tool calls**: Terminal can be embedded in tool call content for live display
3. **Timeout support**: Agent can implement timeouts using `kill_terminal`
4. **Output capture**: Get final output to feed back to LLM

### Implementation Plan

```python
class IdeTerminalTool:
    """Tool that executes commands in the IDE's terminal.
    
    Commands run ON THE USER'S MACHINE, not on Amplifier's server.
    User sees live output in their IDE's terminal panel.
    """
    
    name = "ide_terminal"
    description = """Execute a command in the user's IDE terminal.
    
    The command runs on the USER'S MACHINE in their IDE. Use for:
    - User's project commands (npm test, make build, etc.)
    - Commands needing user's environment/credentials
    - When user should see live output
    
    For agent's internal operations, use 'bash' instead."""
    
    def __init__(self, conn: Client, session_id: str, client_caps: ClientCapabilities):
        self._conn = conn
        self._session_id = session_id
        self._has_terminal = client_caps and client_caps.terminal
    
    async def execute(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ToolResult:
        if not self._has_terminal:
            return ToolResult(
                error="IDE does not support terminal capability. Use 'bash' tool instead."
            )
        
        # 1. Create terminal (returns immediately)
        env_vars = [{"name": k, "value": v} for k, v in (env or {}).items()]
        result = await self._conn.create_terminal(
            session_id=self._session_id,
            command=command,
            args=args or [],
            cwd=cwd,
            env=env_vars,
        )
        terminal_id = result.terminal_id
        
        try:
            # 2. Wait for completion (with optional timeout)
            if timeout:
                exit_result = await self._wait_with_timeout(terminal_id, timeout)
            else:
                exit_result = await self._conn.wait_for_terminal_exit(
                    session_id=self._session_id,
                    terminal_id=terminal_id,
                )
            
            # 3. Get output
            output_result = await self._conn.terminal_output(
                session_id=self._session_id,
                terminal_id=terminal_id,
            )
            
            return ToolResult(
                output=output_result.output,
                exit_code=exit_result.exit_code,
                truncated=output_result.truncated,
            )
            
        finally:
            # 4. Always release
            await self._conn.release_terminal(
                session_id=self._session_id,
                terminal_id=terminal_id,
            )
    
    async def _wait_with_timeout(self, terminal_id: str, timeout: int):
        """Wait for exit with timeout, killing if exceeded."""
        try:
            return await asyncio.wait_for(
                self._conn.wait_for_terminal_exit(
                    session_id=self._session_id,
                    terminal_id=terminal_id,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Kill and get partial output
            await self._conn.kill_terminal(
                session_id=self._session_id,
                terminal_id=terminal_id,
            )
            return await self._conn.wait_for_terminal_exit(
                session_id=self._session_id,
                terminal_id=terminal_id,
            )
```

---

## Priority 2: Client File System (`ide_read_file`, `ide_write_file` tools)

### What It Is

Tools that read/write files **on the IDE's machine** via the ACP file system protocol.

**Critical feature**: `ide_read_file` returns **unsaved editor buffer content**, not just disk content!

### Why This Matters

```
User has file open in editor with unsaved changes:
┌─────────────────────────────────────────┐
│  editor.py (modified)                   │
│  ─────────────────────────────────────  │
│  def calculate():        ← User added   │
│      return x + y        ← this line    │
│                                         │
│  [Unsaved changes]                      │
└─────────────────────────────────────────┘

On disk (saved version):
def calculate():
    return x  # Old version

read_file (server-side):     → returns "return x" (disk)
ide_read_file (client-side): → returns "return x + y" (buffer!)
```

### Protocol Flow

```
Agent                                   Client (IDE)
  |                                         |
  |-- fs/read_text_file {path} ----------->|
  |                                         | IDE checks: is file open?
  |                                         | YES → return buffer content
  |                                         | NO  → return disk content
  |<-- {content: "..."} -------------------|
  |                                         |
  |-- fs/write_text_file {path, content} ->|
  |                                         | IDE writes file
  |                                         | IDE marks as modified
  |                                         | File watchers notified
  |<-- null (success) ---------------------|
```

### Implementation Plan

```python
class IdeReadFileTool:
    """Tool that reads files from the IDE's file system.
    
    Reads files ON THE USER'S MACHINE, including unsaved editor buffers!
    """
    
    name = "ide_read_file"
    description = """Read a file from the user's IDE.
    
    Reads from THE USER'S MACHINE, not Amplifier's server.
    IMPORTANT: Returns unsaved editor buffer content if file is open!
    
    Use for reading user's project files. For agent's own files, use 'read_file'."""
    
    async def execute(
        self,
        path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> ToolResult:
        if not self._has_fs_read:
            return ToolResult(error="IDE does not support file reading.")
        
        result = await self._conn.read_text_file(
            session_id=self._session_id,
            path=path,
            line=line,
            limit=limit,
        )
        return ToolResult(content=result.content)


class IdeWriteFileTool:
    """Tool that writes files to the IDE's file system.
    
    Writes files ON THE USER'S MACHINE. Editor tracks the change.
    """
    
    name = "ide_write_file"
    description = """Write a file in the user's IDE.
    
    Writes to THE USER'S MACHINE, not Amplifier's server.
    The editor will track this change and show it as modified.
    
    Use for modifying user's project files. For agent's own files, use 'write_file'."""
    
    async def execute(self, path: str, content: str) -> ToolResult:
        if not self._has_fs_write:
            return ToolResult(error="IDE does not support file writing.")
        
        await self._conn.write_text_file(
            session_id=self._session_id,
            path=path,
            content=content,
        )
        return ToolResult(success=True)
```

---

## Priority 3: Permission Requests

### What It Is

Instead of internal approval hooks, ask the IDE to show a native permission dialog.

### When to Use

- Before executing potentially dangerous operations
- Before writing to important files
- Before running commands that modify system state

```python
class IdePermissionRequest:
    """Request user permission via IDE's native UI."""
    
    async def request_permission(
        self,
        tool_name: str,
        tool_args: dict,
        message: str,
    ) -> bool:
        result = await self._conn.request_permission(
            session_id=self._session_id,
            tool_call=ToolCallUpdate(
                id=str(uuid.uuid4()),
                name=tool_name,
                input=tool_args,
            ),
            options=[
                PermissionOption(
                    option_id="allow",
                    name=f"Allow: {message}",
                    kind="allow_once",
                ),
                PermissionOption(
                    option_id="deny",
                    name="Deny",
                    kind="reject_once",
                ),
            ],
        )
        
        if result.outcome.outcome == "cancelled":
            return False
        return result.outcome.option_id == "allow"
```

---

## Priority 4: MCP Server Integration

Clients can pass MCP server configurations during session creation. We currently ignore them.

```python
async def new_session(
    self,
    cwd: str,
    mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio],  # ← Currently ignored!
    **kwargs: Any,
) -> NewSessionResponse:
```

### What It Would Enable

- IDE registers its own tools with our agent
- Dynamic tool discovery
- Editor-specific capabilities exposed via MCP

---

## Implementation Phases

### Phase 1: Core Client Tools (Week 1)

1. **Capability detection** - Store and check client capabilities
2. **`ide_terminal` tool** - Full terminal lifecycle
3. **`ide_read_file` tool** - Read with unsaved buffer support
4. **`ide_write_file` tool** - Write with editor tracking

### Phase 2: Enhanced Features (Week 2)

5. **Terminal embedding** - Embed in tool calls for live display
6. **Permission requests** - Native IDE permission dialogs
7. **Timeout handling** - Proper timeout with kill/cleanup

### Phase 3: Advanced (Week 3+)

8. **MCP server integration** - Connect to client-provided servers
9. **Model selection** - Actually switch models mid-session

---

## Testing Strategy

### Mock Client for Testing

```python
class MockIdeClient:
    """Mock IDE client for testing client-side tools."""
    
    def __init__(self):
        self.terminals: dict[str, MockTerminal] = {}
        self.files: dict[str, str] = {}  # path → buffer content
        self.disk_files: dict[str, str] = {}  # path → disk content
    
    async def create_terminal(self, command, args, cwd, **kwargs):
        terminal_id = f"term_{uuid.uuid4().hex[:8]}"
        self.terminals[terminal_id] = MockTerminal(command, args, cwd)
        return CreateTerminalResponse(terminal_id=terminal_id)
    
    async def read_text_file(self, path, **kwargs):
        # Return buffer content if exists, else disk content
        content = self.files.get(path) or self.disk_files.get(path, "")
        return ReadTextFileResponse(content=content)
    
    def set_unsaved_buffer(self, path: str, content: str):
        """Simulate user editing a file without saving."""
        self.files[path] = content
```

### E2E Test Cases

1. **Terminal execution**: Create, run, get output, release
2. **Terminal timeout**: Create, timeout, kill, get partial output
3. **File read with unsaved**: Set buffer, read, verify buffer returned
4. **File write**: Write, verify editor would be notified
5. **Capability fallback**: Client without terminal → error message

---

## References

- [ACP Protocol Overview](https://agentclientprotocol.com/protocol/overview)
- [ACP Terminals](https://agentclientprotocol.com/protocol/terminals)
- [ACP File System](https://agentclientprotocol.com/protocol/file-system)
- [ACP Tool Calls](https://agentclientprotocol.com/protocol/tool-calls)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk)
