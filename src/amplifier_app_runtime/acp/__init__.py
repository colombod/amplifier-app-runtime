"""Agent Client Protocol (ACP) implementation.

ACP standardizes communication between code editors and AI coding agents.
This module provides full ACP support for amplifier-runtime-app, enabling
compatibility with editors like Zed, JetBrains AI Assistant, Neovim, etc.

Protocol: JSON-RPC 2.0 over stdio (local) or HTTP/WebSocket (remote)

Types are re-exported from the official agent-client-protocol SDK.
See: https://agentclientprotocol.com
"""

from acp import PROTOCOL_VERSION  # type: ignore[import-untyped]
from acp.schema import (  # type: ignore[import-untyped]
    AgentCapabilities,
    AgentMessageChunk,
    CancelNotification,
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    NewSessionRequest,
    NewSessionResponse,
    PromptRequest,
    PromptResponse,
    SessionMode,
    SessionModeState,
    SessionNotification,
    SetSessionModeRequest,
    SetSessionModeResponse,
    StopReason,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    ToolCallStatus,
    ToolCallUpdate,
)

from .agent import AmplifierAgent, AmplifierAgentSession, run_stdio_agent
from .routes import acp_routes, run_acp_stdio
from .transport import (
    AcpTransport,
    HttpAcpTransport,
    JsonRpcProcessor,
    JsonRpcProtocolError,
    StdioAcpTransport,
    WebSocketAcpTransport,
)

# Type aliases
from .types import ContentBlock, SessionUpdate

__all__ = [
    # Agent & Session (new SDK-based implementation)
    "AmplifierAgent",
    "AmplifierAgentSession",
    "run_stdio_agent",
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
    # Protocol version
    "PROTOCOL_VERSION",
    # Capabilities
    "AgentCapabilities",
    "ClientCapabilities",
    "Implementation",
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
    "SessionNotification",
    "SessionUpdate",
    "AgentMessageChunk",
    # Content
    "ContentBlock",
    "TextContentBlock",
    # Tool Calls
    "ToolCallStart",
    "ToolCallProgress",
    "ToolCallUpdate",
    "ToolCallStatus",
    # Modes
    "SessionMode",
    "SessionModeState",
    "SetSessionModeRequest",
    "SetSessionModeResponse",
]
