# ACP Protocol Coverage Review

This document provides a comprehensive analysis of ACP protocol implementation in `amplifier-app-runtime`, highlighting what's implemented, what's missing, and where Amplifier's capabilities are a **superset** of ACP.

> **Protocol Version**: ACP v0.10.3

---

## Executive Summary

| Category | ACP Protocol | Implemented | Amplifier Superset |
|----------|-------------|-------------|-------------------|
| **Agent Methods** | 11 | 11 (100%) | ✅ Extensions via bundles |
| **Client Methods** | 9 | 9 (100%) | ✅ Additional callbacks |
| **Session Updates** | 8 types | 8 (100%) | ✅ Extended event taxonomy |
| **Content Types** | 5 | 4 (80%) | Audio pending |
| **IDE Tools** | 3 | 3 (100%) | ✅ Full Amplifier tool ecosystem |
| **Slash Commands** | Not in ACP | N/A | ✅ 15+ commands (Amplifier extension) |
| **Recipes** | Not in ACP | N/A | ✅ Multi-step workflows (Amplifier extension) |
| **Multi-Agent** | Not in ACP | N/A | ✅ Agent spawning (Amplifier extension) |

---

## 1. Agent Methods (Client → Agent)

### ✅ Fully Implemented

| Method | Status | Notes |
|--------|--------|-------|
| `initialize` | ✅ | Returns agent capabilities, supports all capability flags |
| `session/new` | ✅ | Creates Amplifier session with MCP server support |
| `session/load` | ✅ | Loads existing session from Amplifier's session store |
| `session/list` | ✅ | Lists sessions (currently returns empty, session discovery pending) |
| `session/prompt` | ✅ | Full multimodal support (text, image, embedded resources) |
| `session/fork` | ✅ | Forks session state (maps to Amplifier's session spawning) |
| `session/resume` | ✅ | Resumes paused session |
| `session/cancel` | ✅ | Cancels ongoing prompt |
| `session/set_mode` | ✅ | Sets session mode (maps to Amplifier's mode system) |
| `session/set_model` | ✅ | Changes LLM model mid-session |
| `authenticate` | ✅ | Stub - authentication handled externally |

### Amplifier Superset: Agent Methods

Amplifier extends agent functionality beyond ACP:

| Amplifier Capability | ACP Equivalent | Notes |
|---------------------|----------------|-------|
| **Bundle composition** | None | Dynamic capability loading via bundles |
| **Behavior mounting** | None | Contextual capability injection |
| **Multi-provider support** | Single model | Can switch providers, not just models |
| **Session persistence** | `load_session` | Full transcript and state persistence |
| **Recipe execution** | None | Multi-step orchestrated workflows |

---

## 2. Client Methods (Agent → Client)

### ✅ Fully Implemented

| Method | Status | Notes |
|--------|--------|-------|
| `session/update` | ✅ | Streams all update types |
| `session/request_permission` | ✅ | Full approval bridge to Amplifier's approval system |
| `terminal/create` | ✅ | Via `ide_terminal` tool |
| `terminal/output` | ✅ | Streamed terminal output |
| `terminal/wait_for_exit` | ✅ | Exit code capture |
| `terminal/kill` | ✅ | Process termination |
| `terminal/release` | ✅ | Resource cleanup |
| `fs/read_text_file` | ✅ | Via `ide_read_file` tool |
| `fs/write_text_file` | ✅ | Via `ide_write_file` tool |

### Amplifier Superset: Client Callbacks

Amplifier's event system provides richer callbacks than ACP:

| Amplifier Event | ACP Equivalent | Notes |
|-----------------|----------------|-------|
| `turn:start/end` | Implicit in prompt | Explicit turn lifecycle |
| `provider:*` | None | LLM provider-level events |
| `tool:pre/post` | `tool_call` update | More granular tool lifecycle |
| `mcp:*` | None | MCP server connection events |
| `hook:*` | None | Hook execution events |
| **53 event types** | ~8 update types | 6x more event granularity |

---

## 3. Session Update Types

### ✅ Fully Implemented

| Update Type | Status | Amplifier Mapping |
|-------------|--------|-------------------|
| `agent_message_chunk` | ✅ | `stream:text_delta` event |
| `agent_thought_chunk` | ✅ | Extended thinking events |
| `tool_call` (start) | ✅ | `tool:pre` event |
| `tool_call_progress` | ✅ | `tool:stream` event |
| `plan` (AgentPlanUpdate) | ✅ | `todo:update` event |
| `user_message_chunk` | ✅ | Input echo |
| `available_commands` | ✅ | Slash command list |
| `current_mode` | ✅ | Mode change notification |
| `session_info` | ✅ | Session metadata |

### Amplifier Superset: Event Types

Amplifier provides 53 distinct event types vs ACP's ~8 update types:

```
Amplifier Event Categories (not in ACP):
├── session:* (6 events) - Lifecycle management
├── provider:* (5 events) - LLM interactions  
├── tool:* (6 events) - Tool execution details
├── mcp:* (4 events) - MCP server management
├── hook:* (3 events) - Hook lifecycle
├── context:* (4 events) - Context management
├── spawn:* (3 events) - Multi-agent coordination
└── approval:* (3 events) - Permission workflow
```

---

## 4. Content Types (Prompt Input)

### Implementation Status

| Content Type | Status | Notes |
|--------------|--------|-------|
| `TextContentBlock` | ✅ | Full support |
| `ImageContentBlock` | ✅ | Base64 + URL support |
| `ResourceContentBlock` | ✅ | Embedded file references |
| `EmbeddedResourceContentBlock` | ✅ | Inline resource content |
| `AudioContentBlock` | ⚠️ Pending | Capability advertised as `false` |

### Amplifier Superset: Content Handling

| Amplifier Capability | ACP Equivalent | Notes |
|---------------------|----------------|-------|
| **Multi-provider image routing** | Single provider | Routes to vision-capable providers |
| **Context prepopulation** | Embedded resources | Adds resources to context before prompt |
| **File attachment processing** | Resource blocks | Automatic content extraction |

---

## 5. IDE Tools (ACP Client-Side Tools)

### ✅ Fully Implemented

| Tool | ACP Method | Status | Notes |
|------|------------|--------|-------|
| `ide_terminal` | `terminal/*` | ✅ | Full terminal lifecycle |
| `ide_read_file` | `fs/read_text_file` | ✅ | With line/limit support |
| `ide_write_file` | `fs/write_text_file` | ✅ | Full file write |

### Amplifier Superset: Tool Ecosystem

ACP defines 3 client-side tools. Amplifier provides **dozens** of tools:

| Amplifier Tool Category | Examples | ACP Equivalent |
|------------------------|----------|----------------|
| **File Operations** | `read_file`, `write_file`, `edit_file`, `glob`, `grep` | `fs/*` (limited) |
| **Shell Execution** | `bash`, `python_check` | `terminal/*` |
| **Web Operations** | `web_fetch`, `web_search` | None |
| **Task Management** | `todo`, `task` (agent spawning) | None |
| **Recipe Orchestration** | `recipes` | None |
| **MCP Integration** | Dynamic MCP tools | Via `mcpServers` |

**Key Difference**: ACP tools execute on the CLIENT (IDE). Amplifier tools execute on the SERVER and can call back to the client via ACP tools when needed.

---

## 6. Slash Commands (Amplifier Extension)

### ⭐ Not in ACP - Pure Amplifier Extension

ACP has no concept of slash commands. Amplifier provides 15+ built-in commands:

| Command | Function | Notes |
|---------|----------|-------|
| `/help` | List available commands | |
| `/tools` | List available tools | |
| `/agents` | List spawnable agents | |
| `/status` | Session status | |
| `/clear` | Clear context | |
| `/mode <name>` | Switch mode | |
| `/modes` | List available modes | |
| `/plan` | Show/update task plan | |
| `/explore` | Enable exploration mode | |
| `/careful` | Enable careful mode | |
| `/skills` | List available skills | |
| `/skill <name>` | Load a skill | |
| `/config` | Show configuration | |
| `/recipe <action>` | Recipe management | Nested: list, run, resume, approve, cancel |

### Exposed to ACP via `available_commands` Update

Slash commands are exposed to ACP clients via the `AvailableCommandsUpdate`:

```json
{
  "sessionUpdate": "available_commands",
  "commands": [
    {"name": "help", "description": "Show available commands"},
    {"name": "mode", "description": "Switch mode", "args": ["name"]},
    ...
  ]
}
```

---

## 7. Modes (Amplifier Extension)

### ⭐ Extended Beyond ACP

ACP defines `session/set_mode` and `CurrentModeUpdate`. Amplifier extends this:

| ACP Mode Concept | Amplifier Extension |
|------------------|---------------------|
| Mode ID only | Mode with full context injection |
| No mode definition | Mode files with tool policies |
| No tool restrictions | Tool policies: `safe`, `warn`, `confirm`, `block` |

### Amplifier Mode Features

```yaml
# Example mode file (.amplifier/modes/careful.md)
mode:
  name: careful
  description: "Confirm before destructive operations"
  tool_policies:
    bash: confirm
    write_file: warn
    edit_file: warn
    default: safe
```

---

## 8. Recipes (Amplifier Extension)

### ⭐ Not in ACP - Pure Amplifier Extension

Multi-step orchestrated workflows with:

| Feature | Description |
|---------|-------------|
| **Declarative YAML** | Define workflows in YAML |
| **Agent Delegation** | Each step can use different agents |
| **Context Accumulation** | Results flow between steps |
| **Approval Gates** | Human-in-loop checkpoints |
| **Resumability** | Continue after interruption |
| **Parallel Execution** | Run steps concurrently |
| **Foreach Loops** | Iterate over collections |

### Exposed via Slash Commands

```
/recipe list          - List available recipes
/recipe run <path>    - Execute a recipe  
/recipe resume <id>   - Resume interrupted recipe
/recipe approve <id>  - Approve pending gate
/recipe cancel <id>   - Cancel running recipe
```

---

## 9. Multi-Agent Spawning (Amplifier Extension)

### ⭐ Not in ACP - Pure Amplifier Extension

ACP has no concept of agent-to-agent communication. Amplifier provides:

| Capability | Description |
|------------|-------------|
| **`task` tool** | Spawn child agents for complex tasks |
| **Context inheritance** | Control what context children see |
| **Session linking** | Parent-child session relationships |
| **Result aggregation** | Child results returned to parent |

### Exposed to ACP

Child agent spawning is transparent to ACP clients - they see tool calls and results but don't need to know about the multi-agent orchestration.

---

## 10. Permission/Approval System

### ✅ Fully Implemented with Extensions

| ACP Feature | Status | Amplifier Extension |
|-------------|--------|---------------------|
| `request_permission` | ✅ | Full approval bridge |
| Permission options | ✅ | `allow_once`, `allow_always`, `reject_once`, `reject_always` |
| Tool call context | ✅ | Full tool details in request |

### Amplifier Superset: Approval System

| Amplifier Feature | ACP Equivalent | Notes |
|-------------------|----------------|-------|
| **Hooks-based approval** | `request_permission` | Flexible approval hooks |
| **Rule-based auto-approval** | Manual only | Can configure auto-approve rules |
| **Approval persistence** | `allow_always` | Persists across sessions |
| **Multi-level approval** | Single request | Can require multiple approvals |

---

## 11. MCP Server Integration

### ✅ Fully Implemented

| MCP Type | Status | Notes |
|----------|--------|-------|
| `McpServerStdio` | ✅ | Subprocess-based MCP servers |
| `McpServerSse` | ✅ | SSE-based MCP servers |
| `McpServerHttp` | ⚠️ Advertised as `false` | HTTP polling not implemented |

### Amplifier Superset: MCP Management

| Amplifier Feature | ACP Equivalent | Notes |
|-------------------|----------------|-------|
| **Dynamic MCP discovery** | Static list at session start | Can add MCP servers mid-session |
| **MCP tool namespacing** | Flat namespace | Tools prefixed with server name |
| **MCP health monitoring** | None | Connection health events |

---

## 12. Missing/Incomplete Features

### Not Yet Implemented

| Feature | Status | Notes |
|---------|--------|-------|
| Audio content blocks | ⚠️ | Capability advertised as `false` |
| HTTP MCP servers | ⚠️ | SSE and stdio only |
| Session listing | ⚠️ | Returns empty list (discovery pending) |

### Protocol Features Requiring Attention

1. **Session Discovery**: `session/list` returns empty - need to integrate with Amplifier's session store

2. **Audio Support**: If audio input is needed, requires provider that supports audio

3. **HTTP MCP**: Lower priority - SSE is preferred for real-time

---

## 13. Capability Negotiation

### Agent Capabilities Advertised

```json
{
  "agentCapabilities": {
    "loadSession": true,
    "mcpCapabilities": {
      "http": false,
      "sse": true
    },
    "promptCapabilities": {
      "audio": false,
      "embeddedContext": true,
      "image": true
    },
    "sessionCapabilities": {
      "fork": { "supported": true },
      "list": { "supported": true },
      "resume": { "supported": true }
    }
  }
}
```

### Client Capabilities Expected

```json
{
  "clientCapabilities": {
    "terminal": true,
    "fs": {
      "sandboxedRoots": ["/project"],
      "readTextFile": true,
      "writeTextFile": true
    }
  }
}
```

---

## 14. Architecture: ACP as Thin Transport Layer

### Design Philosophy

```
┌─────────────────────────────────────────────────────────────┐
│                        ACP CLIENT (IDE)                      │
│  - VS Code, Cursor, JetBrains, etc.                         │
│  - Provides: Terminal, File System, UI                       │
└─────────────────────────────┬───────────────────────────────┘
                              │ ACP Protocol (JSON-RPC/stdio)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    ACP TRANSPORT LAYER                       │
│  - Protocol translation                                      │
│  - Capability negotiation                                    │
│  - Session mapping                                           │
└─────────────────────────────┬───────────────────────────────┘
                              │ Internal APIs
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    AMPLIFIER RUNTIME                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Bundles   │  │    Tools    │  │   Recipes   │         │
│  │  (50+)      │  │   (30+)     │  │  Workflows  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Providers  │  │    Hooks    │  │   Agents    │         │
│  │  (5+)       │  │   (10+)     │  │  Spawning   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### Key Insight

**ACP is a capability interface, not a limit.** The ACP layer exposes a standardized subset of Amplifier's capabilities to IDE clients. The full Amplifier ecosystem remains accessible:

- **Via tools**: All Amplifier tools are available to the LLM
- **Via bundles**: Custom capabilities can be composed
- **Via recipes**: Complex workflows can be orchestrated
- **Via agents**: Child agents can be spawned for delegation

---

## 15. Recommendations

### Short-term

1. **Implement session listing**: Integrate with Amplifier's session discovery
2. **Add HTTP MCP support**: If clients need it
3. **Test audio content**: When providers support it

### Medium-term

1. **Expose more Amplifier features via ACP extensions**: 
   - Recipe execution status
   - Agent spawning visibility
   - Mode details

2. **Enhance permission UX**:
   - Batch permission requests
   - Permission presets

### Long-term

1. **Bidirectional MCP**: Allow ACP clients to expose MCP servers to the agent
2. **Streaming improvements**: Sub-token streaming for faster perceived response
3. **Multi-session coordination**: Expose Amplifier's multi-agent patterns to ACP

---

## Appendix: File Locations

| Component | Location |
|-----------|----------|
| ACP Agent | `src/amplifier_app_runtime/acp/agent.py` |
| ACP Tools | `src/amplifier_app_runtime/acp/tools.py` |
| Slash Commands | `src/amplifier_app_runtime/acp/slash_commands.py` |
| Approval Bridge | `src/amplifier_app_runtime/acp/approval_bridge.py` |
| Transport | `src/amplifier_app_runtime/acp/transport.py` |
| Routes (HTTP) | `src/amplifier_app_runtime/acp/routes.py` |
| Types | `src/amplifier_app_runtime/acp/types.py` |
| Entry Point | `src/amplifier_app_runtime/acp/__main__.py` |
