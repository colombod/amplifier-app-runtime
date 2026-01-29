"""ACP type definitions.

Re-exports types from the official agent-client-protocol SDK.
See: https://agentclientprotocol.com/libraries/python

Only custom types specific to this implementation are defined here.
"""

from __future__ import annotations

from acp import PROTOCOL_VERSION  # type: ignore[import-untyped]
from acp.schema import (  # type: ignore[import-untyped]
    AgentCapabilities,
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AudioContentBlock,
    AuthenticateRequest,
    AuthenticateResponse,
    AvailableCommandsUpdate,
    CancelNotification,
    ClientCapabilities,
    CurrentModeUpdate,
    EmbeddedResourceContentBlock,
    FileSystemCapability,
    ImageContentBlock,
    Implementation,
    InitializeRequest,
    InitializeResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    McpCapabilities,
    NewSessionRequest,
    NewSessionResponse,
    Plan,
    PlanEntry,
    PlanEntryPriority,
    PlanEntryStatus,
    PromptCapabilities,
    PromptRequest,
    PromptResponse,
    ResourceContentBlock,
    SessionCapabilities,
    SessionInfoUpdate,
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
    ToolKind,
    UserMessageChunk,
)

# Type alias for content blocks in prompts
ContentBlock = (
    TextContentBlock
    | ImageContentBlock
    | AudioContentBlock
    | ResourceContentBlock
    | EmbeddedResourceContentBlock
)

# Type alias for session updates
SessionUpdate = (
    UserMessageChunk
    | AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AgentPlanUpdate
    | AvailableCommandsUpdate
    | CurrentModeUpdate
    | SessionInfoUpdate
)

__all__ = [
    "PROTOCOL_VERSION",
    "AgentCapabilities",
    "AgentMessageChunk",
    "AgentPlanUpdate",
    "AgentThoughtChunk",
    "AudioContentBlock",
    "AuthenticateRequest",
    "AuthenticateResponse",
    "AvailableCommandsUpdate",
    "CancelNotification",
    "ClientCapabilities",
    "ContentBlock",
    "CurrentModeUpdate",
    "EmbeddedResourceContentBlock",
    "FileSystemCapability",
    "ImageContentBlock",
    "Implementation",
    "InitializeRequest",
    "InitializeResponse",
    "LoadSessionRequest",
    "LoadSessionResponse",
    "McpCapabilities",
    "NewSessionRequest",
    "NewSessionResponse",
    "Plan",
    "PlanEntry",
    "PlanEntryPriority",
    "PlanEntryStatus",
    "PromptCapabilities",
    "PromptRequest",
    "PromptResponse",
    "ResourceContentBlock",
    "SessionCapabilities",
    "SessionInfoUpdate",
    "SessionMode",
    "SessionModeState",
    "SessionNotification",
    "SessionUpdate",
    "SetSessionModeRequest",
    "SetSessionModeResponse",
    "StopReason",
    "TextContentBlock",
    "ToolCallProgress",
    "ToolCallStart",
    "ToolCallStatus",
    "ToolCallUpdate",
    "ToolKind",
    "UserMessageChunk",
]
