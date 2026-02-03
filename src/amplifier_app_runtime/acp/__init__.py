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
from .content_converter import AcpToAmplifierContentConverter, ConversionResult
from .event_mapper import AmplifierToAcpEventMapper, EventMapResult
from .protocols import (
    ACPConnectionProtocol,
    AmplifierSessionProtocol,
    ContentConverterProtocol,
    EventMapperProtocol,
    ManagedSessionProtocol,
    SlashCommandHandlerProtocol,
    ToolTrackerProtocol,
)
from .routes import acp_routes, run_acp_stdio
from .session_discovery import (
    AMPLIFIER_PROJECTS_DIR,
    decode_project_path,
    discover_sessions,
    encode_project_path,
    find_session_directory,
)
from .tool_metadata import (
    TOOL_METADATA,
    ToolMeta,
    get_tool_category,
    get_tool_kind,
    get_tool_title,
    register_tool_metadata,
)
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
    # Content Converter (extracted module)
    "AcpToAmplifierContentConverter",
    "ConversionResult",
    # Event Mapper (extracted module)
    "AmplifierToAcpEventMapper",
    "EventMapResult",
    # Protocols (type safety)
    "ACPConnectionProtocol",
    "AmplifierSessionProtocol",
    "ContentConverterProtocol",
    "EventMapperProtocol",
    "ManagedSessionProtocol",
    "SlashCommandHandlerProtocol",
    "ToolTrackerProtocol",
    # Session Discovery (extracted module)
    "AMPLIFIER_PROJECTS_DIR",
    "decode_project_path",
    "discover_sessions",
    "encode_project_path",
    "find_session_directory",
    # Tool Metadata (shared module)
    "TOOL_METADATA",
    "ToolMeta",
    "get_tool_category",
    "get_tool_kind",
    "get_tool_title",
    "register_tool_metadata",
]
