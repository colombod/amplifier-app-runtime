# ACP Feature Analysis: Missing Capabilities & Prioritization

**Branch:** `feature/acp-client-capabilities`  
**Date:** 2026-01-29

## Executive Summary

Our current ACP implementation covers the **Agent-side methods** well, but we're not utilizing the **Client-side capabilities** that the protocol exposes. These client capabilities allow the agent to request services FROM the client (editor), enabling powerful integrations like:

- Executing commands in the editor's terminal (with live output)
- Reading files including **unsaved editor state**
- Writing files through the editor (with change tracking)
- Requesting user permissions via editor UI

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
| `create_terminal` | ❌ Not used | HIGH - Live command execution |
| `terminal_output` | ❌ Not used | HIGH - Get command output |
| `wait_for_terminal_exit` | ❌ Not used | HIGH - Process control |
| `kill_terminal` | ❌ Not used | MEDIUM - Process control |
| `release_terminal` | ❌ Not used | MEDIUM - Cleanup |
| `read_text_file` | ❌ Not used | HIGH - Includes unsaved state! |
| `write_text_file` | ❌ Not used | HIGH - Editor-tracked writes |
| `request_permission` | ❌ Not used | MEDIUM - Native approval UI |

---

## Priority 1: Client Terminal Integration (HIGH)

### What It Enables

The ACP terminal methods allow our agent to execute commands **via the client's terminal** instead of internally. This provides:

1. **Live Output Streaming**: User sees command output in real-time in their editor
2. **Visual Feedback**: Terminal can be embedded in tool calls for visual progress
3. **Process Control**: Kill, timeout, wait for completion
4. **Editor Integration**: Commands run in editor's environment

### Protocol Flow

```
Agent                                   Client (Editor)
  |                                         |
  |-- terminal/create {command, args} ---->|
  |<---- {terminalId: "term_123"} ---------|
  |                                         |
  |-- session/update {toolCall with        |
  |     content: [{type: "terminal",       |
  |               terminalId: "term_123"}]}|
  |                                         | (User sees live output)
  |                                         |
  |-- terminal/wait_for_exit ------------->|
  |<---- {exitCode: 0} -------------------|
  |                                         |
  |-- terminal/release ------------------->|
```

### Implementation Plan

```python
class ClientTerminalBashTool:
    """Bash tool that executes via client terminal."""
    
    async def execute(self, command: str, args: list[str] = None) -> str:
        # Check client capability
        if not self._client_caps.terminal:
            # Fall back to internal execution
            return await self._internal_execute(command)
        
        # Create terminal via client
        result = await self._conn.create_terminal(
            session_id=self._session_id,
            command=command,
            args=args or [],
            cwd=self._cwd,
        )
        terminal_id = result.terminal_id
        
        # Report tool call with embedded terminal
        await self._conn.session_update(
            self._session_id,
            ToolCallStart(
                id=self._call_id,
                name="bash",
                content=[{"type": "terminal", "terminalId": terminal_id}],
            ),
        )
        
        # Wait for completion
        exit_result = await self._conn.wait_for_terminal_exit(
            session_id=self._session_id,
            terminal_id=terminal_id,
        )
        
        # Get final output
        output = await self._conn.terminal_output(
            session_id=self._session_id,
            terminal_id=terminal_id,
        )
        
        # Cleanup
        await self._conn.release_terminal(
            session_id=self._session_id,
            terminal_id=terminal_id,
        )
        
        return output.output
```

### Benefits
- Users see commands executing live
- Better debugging (output visible in editor)
- Commands use editor's environment (PATH, env vars)
- Proper process lifecycle management

---

## Priority 2: Client File System Integration (HIGH)

### What It Enables

The ACP file system methods allow reading/writing files **through the client**. The killer feature: **reading unsaved editor state**.

### Why This Matters

When a user has a file open with unsaved changes:
- Our internal `read_file` tool reads the **disk version**
- Client `fs/read_text_file` reads the **buffer version** (what user sees)

This is critical for code assistance - we want to see what the user is actually editing, not what's saved on disk.

### Protocol Flow

```
Agent                                   Client (Editor)
  |                                         |
  |-- fs/read_text_file {path} ----------->| 
  |<---- {content: "..."} (with unsaved   |
  |        changes!) ---------------------|
  |                                         |
  |-- fs/write_text_file {path, content}->|
  |<---- null (success) ------------------|
  |                                         | (Editor shows file changed)
```

### Implementation Plan

```python
class ClientFileSystemTool:
    """File tool that uses client's file system."""
    
    async def read_file(self, path: str, line: int = None, limit: int = None) -> str:
        # Check client capability
        if not self._client_caps.fs or not self._client_caps.fs.read_text_file:
            return await self._internal_read(path)
        
        result = await self._conn.read_text_file(
            session_id=self._session_id,
            path=path,
            line=line,
            limit=limit,
        )
        return result.content
    
    async def write_file(self, path: str, content: str) -> None:
        if not self._client_caps.fs or not self._client_caps.fs.write_text_file:
            return await self._internal_write(path, content)
        
        await self._conn.write_text_file(
            session_id=self._session_id,
            path=path,
            content=content,
        )
```

### Benefits
- Read unsaved editor changes (huge for code assistance)
- Editor tracks file modifications
- Editor's file watchers are notified
- Works with editor's virtual file system (if any)

---

## Priority 3: Permission Request Integration (MEDIUM)

### What It Enables

Instead of our internal approval hooks, we can ask the client to show a permission dialog. This provides:

1. **Native UI**: Permission dialog appears in the editor
2. **User Control**: Users can "Allow Once", "Allow Always", "Deny"
3. **Consistency**: Same UX as other editor permissions

### Protocol Flow

```
Agent                                   Client (Editor)
  |                                         |
  |-- session/request_permission --------->|
  |     {toolCall: {...},                  |
  |      options: [                        |
  |        {id: "allow-once", kind: "allow_once"},
  |        {id: "deny", kind: "reject_once"}
  |      ]}                                |
  |                                         | (Editor shows permission dialog)
  |<---- {outcome: {selected: "allow-once"}}|
```

### Implementation Plan

```python
class ClientPermissionHook:
    """Hook that requests permissions via client UI."""
    
    async def request_approval(self, tool_name: str, args: dict) -> bool:
        # Build permission request
        result = await self._conn.request_permission(
            session_id=self._session_id,
            tool_call=ToolCallUpdate(
                id=str(uuid.uuid4()),
                name=tool_name,
                input=args,
            ),
            options=[
                PermissionOption(
                    option_id="allow-once",
                    name="Allow",
                    kind="allow_once",
                ),
                PermissionOption(
                    option_id="deny",
                    name="Deny",
                    kind="reject_once",
                ),
            ],
        )
        
        return result.outcome.outcome == "selected" and \
               result.outcome.option_id == "allow-once"
```

---

## Priority 4: MCP Server Integration (MEDIUM)

### What It Enables

Clients can pass MCP server configurations during session creation. This allows:

1. **Dynamic Tools**: Client provides additional tools to the agent
2. **Editor Tools**: Editor can expose its own capabilities as MCP tools
3. **Context Servers**: Editor can provide context via MCP resources

### Current State

We receive `mcp_servers` in `new_session` but don't connect to them:

```python
async def new_session(
    self,
    cwd: str,
    mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio],  # ← Ignored!
    **kwargs: Any,
) -> NewSessionResponse:
```

### Implementation Plan

1. Parse MCP server configs from session creation
2. Connect to stdio/SSE/HTTP MCP servers
3. Discover tools from connected servers
4. Register tools with Amplifier session
5. Handle tool calls by routing to appropriate MCP server

---

## Priority 5: Model Selection (LOW)

### Current State

We have a stub that logs but doesn't switch:

```python
async def set_session_model(self, model_id: str, session_id: str, **kwargs):
    logger.info(f"Model change requested: {model_id}")  # Just logs
    return SetSessionModelResponse()
```

### Implementation Plan

Would require:
1. Mapping ACP model IDs to provider-specific models
2. Reconfiguring the provider mid-session
3. Handling provider switch (Anthropic → OpenAI, etc.)

---

## Recommended Implementation Order

### Phase 1: Core Client Capabilities (1-2 weeks)
1. **Client capability detection** - Check what client supports
2. **File system methods** - `read_text_file`, `write_text_file`
3. **Basic terminal** - `create_terminal`, `wait_for_exit`, `release`

### Phase 2: Enhanced Integration (1 week)
4. **Terminal embedding** - Embed terminals in tool calls
5. **Permission requests** - Native approval UI

### Phase 3: Advanced Features (1-2 weeks)
6. **MCP server integration** - Connect to client-provided servers
7. **Model selection** - Switch models mid-session

---

## Architecture Considerations

### Capability Detection Pattern

```python
class AmplifierAgentSession:
    def __init__(self, ..., client_capabilities: ClientCapabilities | None):
        self._client_caps = client_capabilities
        
        # Select tool implementations based on client capabilities
        self._file_tool = (
            ClientFileSystemTool(self._conn, client_capabilities)
            if client_capabilities and client_capabilities.fs
            else InternalFileSystemTool()
        )
```

### Fallback Strategy

When client doesn't support a capability:
1. Check capability during initialization
2. Fall back to internal implementation
3. Log which mode is being used

```python
if self._client_caps and self._client_caps.terminal:
    logger.info("Using client terminal for command execution")
else:
    logger.info("Using internal bash execution (client terminal not supported)")
```

---

## Test Strategy

### E2E Tests Needed

1. **Terminal integration test**: Create terminal, execute command, verify output
2. **File system test**: Read file, verify unsaved state handling
3. **Permission test**: Request permission, verify UI interaction
4. **Fallback test**: Verify internal tools work when client lacks capabilities

### Mock Client for Testing

```python
class TestClient(Client):
    """Test client that simulates editor capabilities."""
    
    def __init__(self):
        self.terminals: dict[str, TerminalState] = {}
        self.files: dict[str, str] = {}  # Simulated unsaved state
        
    async def create_terminal(self, command, args, **kwargs):
        terminal_id = f"term_{uuid.uuid4().hex[:8]}"
        # Simulate command execution
        self.terminals[terminal_id] = TerminalState(command=command)
        return CreateTerminalResponse(terminal_id=terminal_id)
```

---

## References

- [ACP Protocol Specification](https://agentclientprotocol.com/protocol/overview)
- [ACP File System Methods](https://agentclientprotocol.com/protocol/file-system)
- [ACP Terminal Methods](https://agentclientprotocol.com/protocol/terminals)
- [ACP Tool Calls](https://agentclientprotocol.com/protocol/tool-calls)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk)
