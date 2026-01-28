"""Agent Client Protocol (ACP) implementation.

ACP standardizes communication between code editors and AI coding agents.
This module provides full ACP support for amplifier-server-app, enabling
compatibility with editors like Zed, JetBrains AI Assistant, Neovim, etc.

Protocol: JSON-RPC 2.0 over stdio (local) or HTTP/WebSocket (remote)

See: https://agentclientprotocol.com
"""

from .handler import AcpHandler, AcpSession
from .routes import acp_routes, run_acp_stdio
from .transport import (
    AcpTransport,
    HttpAcpTransport,
    JsonRpcProcessor,
    JsonRpcProtocolError,
    StdioAcpTransport,
    WebSocketAcpTransport,
)
from .types import (
    # Protocol version
    PROTOCOL_VERSION,
    # Capabilities
    AgentCapabilities,
    AgentInfo,
    # Cancel
    CancelNotification,
    ClientCapabilities,
    ClientInfo,
    # Content
    ContentBlock,
    ImageContent,
    # Initialize
    InitializeRequest,
    InitializeResponse,
    JsonRpcError,
    JsonRpcNotification,
    # JSON-RPC
    JsonRpcRequest,
    JsonRpcResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    # MCP
    McpServerConfig,
    # Session
    NewSessionRequest,
    NewSessionResponse,
    # Prompt
    PromptRequest,
    PromptResponse,
    # File System
    ReadTextFileRequest,
    ReadTextFileResponse,
    # Permission
    RequestPermissionRequest,
    RequestPermissionResponse,
    ResourceContent,
    ResourceLinkContent,
    # Modes
    SessionMode,
    SessionModes,
    # Session Update
    SessionUpdate,
    SessionUpdateType,
    SetSessionModeRequest,
    SetSessionModeResponse,
    StopReason,
    TextContent,
    # Tool Calls
    ToolCall,
    ToolCallStatus,
    ToolCallUpdate,
    WriteTextFileRequest,
    WriteTextFileResponse,
)

__all__ = [
    # Handler & Session
    "AcpHandler",
    "AcpSession",
    # Routes
    "acp_routes",
    "run_acp_stdio",
    # Transport
    "AcpTransport",
    "HttpAcpTransport",
    "StdioAcpTransport",
    "WebSocketAcpTransport",
    "JsonRpcProcessor",
    "JsonRpcProtocolError",
    # JSON-RPC
    "JsonRpcRequest",
    "JsonRpcResponse",
    "JsonRpcError",
    "JsonRpcNotification",
    # Capabilities
    "AgentCapabilities",
    "ClientCapabilities",
    "AgentInfo",
    "ClientInfo",
    # Initialize
    "InitializeRequest",
    "InitializeResponse",
    # Session
    "NewSessionRequest",
    "NewSessionResponse",
    "LoadSessionRequest",
    "LoadSessionResponse",
    # Prompt
    "PromptRequest",
    "PromptResponse",
    "StopReason",
    # Cancel
    "CancelNotification",
    # Session Update
    "SessionUpdate",
    "SessionUpdateType",
    # Content
    "ContentBlock",
    "TextContent",
    "ResourceContent",
    "ResourceLinkContent",
    "ImageContent",
    # Tool Calls
    "ToolCall",
    "ToolCallUpdate",
    "ToolCallStatus",
    # Modes
    "SessionMode",
    "SessionModes",
    "SetSessionModeRequest",
    "SetSessionModeResponse",
    # File System
    "ReadTextFileRequest",
    "ReadTextFileResponse",
    "WriteTextFileRequest",
    "WriteTextFileResponse",
    # Permission
    "RequestPermissionRequest",
    "RequestPermissionResponse",
    # MCP
    "McpServerConfig",
    # Protocol version
    "PROTOCOL_VERSION",
]
