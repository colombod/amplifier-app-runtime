"""ACP type definitions.

Defines all types for the Agent Client Protocol following the official schema.
See: https://agentclientprotocol.com/protocol/schema

Note: Field names use camelCase to match the ACP protocol specification.
This is required for protocol compatibility - do not change to snake_case.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# Protocol version
PROTOCOL_VERSION = "2025-01-07"


class AcpModel(BaseModel):
    """Base model for ACP types with camelCase serialization."""

    model_config = ConfigDict(
        populate_by_name=True,
        # Allow camelCase field names (required by ACP protocol)
    )


# =============================================================================
# JSON-RPC 2.0 Base Types
# =============================================================================


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: str
    params: dict[str, Any] | None = None


class JsonRpcNotification(BaseModel):
    """JSON-RPC 2.0 notification (no response expected)."""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: Any | None = None
    error: JsonRpcError | None = None


# Standard JSON-RPC error codes
class JsonRpcErrorCode:
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # ACP-specific error codes
    AUTH_REQUIRED = -32000
    SESSION_NOT_FOUND = -32001
    PERMISSION_DENIED = -32002


# =============================================================================
# Capability Types
# =============================================================================


class FileSystemCapabilities(BaseModel):
    """Client file system capabilities."""

    readTextFile: bool = False
    writeTextFile: bool = False


class PromptCapabilities(BaseModel):
    """Agent prompt capabilities."""

    audio: bool = False
    embeddedContext: bool = False
    image: bool = False


class McpCapabilities(BaseModel):
    """Agent MCP capabilities."""

    http: bool = False
    sse: bool = False


class SessionCapabilities(BaseModel):
    """Agent session capabilities."""

    # Add session-specific capabilities as needed
    pass


class ClientCapabilities(BaseModel):
    """Capabilities supported by the client."""

    fs: FileSystemCapabilities = Field(default_factory=FileSystemCapabilities)
    terminal: bool = False


class AgentCapabilities(BaseModel):
    """Capabilities supported by the agent."""

    loadSession: bool = False
    mcpCapabilities: McpCapabilities = Field(default_factory=McpCapabilities)
    promptCapabilities: PromptCapabilities = Field(default_factory=PromptCapabilities)
    sessionCapabilities: SessionCapabilities = Field(default_factory=SessionCapabilities)


class ClientInfo(BaseModel):
    """Information about the client."""

    name: str
    version: str


class AgentInfo(BaseModel):
    """Information about the agent."""

    name: str
    version: str


class AuthMethod(BaseModel):
    """Authentication method."""

    id: str
    name: str
    description: str | None = None


# =============================================================================
# Initialize
# =============================================================================


class InitializeRequest(BaseModel):
    """Request parameters for the initialize method."""

    protocolVersion: str
    clientInfo: ClientInfo | None = None
    clientCapabilities: ClientCapabilities = Field(default_factory=ClientCapabilities)
    _meta: dict[str, Any] | None = None


class InitializeResponse(BaseModel):
    """Response to the initialize method."""

    protocolVersion: str
    agentInfo: AgentInfo | None = None
    agentCapabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    authMethods: list[AuthMethod] = Field(default_factory=list)
    _meta: dict[str, Any] | None = None


# =============================================================================
# Authentication
# =============================================================================


class AuthenticateRequest(BaseModel):
    """Request parameters for the authenticate method."""

    methodId: str
    _meta: dict[str, Any] | None = None


class AuthenticateResponse(BaseModel):
    """Response to the authenticate method."""

    _meta: dict[str, Any] | None = None


# =============================================================================
# MCP Server Configuration
# =============================================================================


class McpServerConfig(BaseModel):
    """MCP server configuration."""

    name: str
    uri: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


# =============================================================================
# Session Mode
# =============================================================================


class SessionMode(BaseModel):
    """Session mode definition."""

    id: str
    name: str
    description: str | None = None


class SessionModes(BaseModel):
    """Session modes state."""

    availableModes: list[SessionMode] = Field(default_factory=list)
    currentMode: str | None = None


# =============================================================================
# Session Management
# =============================================================================


class NewSessionRequest(BaseModel):
    """Request parameters for creating a new session."""

    cwd: str
    mcpServers: list[McpServerConfig] = Field(default_factory=list)
    _meta: dict[str, Any] | None = None


class NewSessionResponse(BaseModel):
    """Response from creating a new session."""

    sessionId: str
    modes: SessionModes | None = None
    _meta: dict[str, Any] | None = None


class LoadSessionRequest(BaseModel):
    """Request parameters for loading an existing session."""

    sessionId: str
    cwd: str
    mcpServers: list[McpServerConfig] = Field(default_factory=list)
    _meta: dict[str, Any] | None = None


class LoadSessionResponse(BaseModel):
    """Response from loading an existing session."""

    modes: SessionModes | None = None
    _meta: dict[str, Any] | None = None


class SetSessionModeRequest(BaseModel):
    """Request parameters for setting a session mode."""

    sessionId: str
    modeId: str
    _meta: dict[str, Any] | None = None


class SetSessionModeResponse(BaseModel):
    """Response to session/set_mode method."""

    _meta: dict[str, Any] | None = None


# =============================================================================
# Content Types
# =============================================================================


class TextContent(BaseModel):
    """Text content block."""

    type: Literal["text"] = "text"
    text: str


class ResourceContent(BaseModel):
    """Resource content block (embedded content)."""

    type: Literal["resource"] = "resource"
    uri: str
    mimeType: str | None = None
    text: str | None = None
    blob: str | None = None  # Base64 encoded


class ResourceLinkContent(BaseModel):
    """Resource link content block (reference to external resource)."""

    type: Literal["resource_link"] = "resource_link"
    uri: str
    name: str | None = None
    mimeType: str | None = None


class ImageContent(BaseModel):
    """Image content block."""

    type: Literal["image"] = "image"
    data: str  # Base64 encoded
    mimeType: str


# Union of all content types
ContentBlock = Union[TextContent, ResourceContent, ResourceLinkContent, ImageContent]


# =============================================================================
# Tool Calls
# =============================================================================


class ToolCallStatus(str, Enum):
    """Status of a tool call."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolCall(BaseModel):
    """Tool call information."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatus = ToolCallStatus.PENDING


class ToolCallUpdate(BaseModel):
    """Update about a tool call."""

    id: str
    status: ToolCallStatus
    result: Any | None = None
    error: str | None = None


# =============================================================================
# Prompt Turn
# =============================================================================


class PromptRequest(BaseModel):
    """Request parameters for sending a user prompt."""

    sessionId: str
    prompt: list[ContentBlock]
    _meta: dict[str, Any] | None = None


class StopReason(str, Enum):
    """Reason why the agent stopped processing."""

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    TOOL_USE = "tool_use"
    CANCELLED = "cancelled"
    ERROR = "error"


class PromptResponse(BaseModel):
    """Response from processing a user prompt."""

    stopReason: StopReason
    _meta: dict[str, Any] | None = None


# =============================================================================
# Cancel
# =============================================================================


class CancelNotification(BaseModel):
    """Notification to cancel ongoing operations."""

    sessionId: str
    _meta: dict[str, Any] | None = None


# =============================================================================
# Session Update (Server -> Client notifications)
# =============================================================================


class SessionUpdateType(str, Enum):
    """Types of session updates."""

    # Message chunks
    AGENT_MESSAGE_CHUNK = "agent_message_chunk"
    USER_MESSAGE_CHUNK = "user_message_chunk"
    THOUGHT_CHUNK = "thought_chunk"

    # Tool calls
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_UPDATE = "tool_call_update"
    TOOL_CALL_END = "tool_call_end"

    # Plans
    PLAN_UPDATE = "plan_update"

    # Commands
    COMMANDS_UPDATE = "commands_update"

    # Mode
    CURRENT_MODE_UPDATE = "current_mode_update"


class MessageChunk(BaseModel):
    """Message chunk content."""

    content: list[ContentBlock]


class SessionUpdate(BaseModel):
    """Session update notification."""

    sessionId: str
    type: SessionUpdateType
    data: dict[str, Any] = Field(default_factory=dict)
    _meta: dict[str, Any] | None = None


# =============================================================================
# File System Operations (Client Methods)
# =============================================================================


class ReadTextFileRequest(BaseModel):
    """Request to read content from a text file."""

    sessionId: str
    path: str
    line: int | None = None  # 1-based line number
    limit: int | None = None  # Max lines to read
    _meta: dict[str, Any] | None = None


class ReadTextFileResponse(BaseModel):
    """Response containing the contents of a text file."""

    content: str
    totalLines: int | None = None
    _meta: dict[str, Any] | None = None


class WriteTextFileRequest(BaseModel):
    """Request to write content to a text file."""

    sessionId: str
    path: str
    content: str
    _meta: dict[str, Any] | None = None


class WriteTextFileResponse(BaseModel):
    """Response from writing a text file."""

    success: bool
    _meta: dict[str, Any] | None = None


# =============================================================================
# Permission Request (Client Method)
# =============================================================================


class RequestPermissionRequest(BaseModel):
    """Request user authorization for tool calls."""

    sessionId: str
    toolCall: ToolCall
    _meta: dict[str, Any] | None = None


class RequestPermissionResponse(BaseModel):
    """Response to permission request."""

    granted: bool
    _meta: dict[str, Any] | None = None
