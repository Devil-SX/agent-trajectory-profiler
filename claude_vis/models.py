"""
Type-safe Pydantic models for Claude Code session data.

This module defines comprehensive data models for parsing and validating
Claude Code session files, including support for nested subagent sessions,
tool calls, and message structures.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class MessageRole(str, Enum):
    """Message role types in Claude sessions."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageSource(str, Enum):
    """Source of a message (main session or subagent)."""

    MAIN = "main"
    SUBAGENT = "subagent"


class SubagentType(str, Enum):
    """Types of subagents that can be invoked."""

    EXPLORE = "Explore"
    BASH = "Bash"
    GENERAL_PURPOSE = "general-purpose"
    PLAN = "Plan"
    TEST_RUNNER = "test-runner"
    BUILD_VALIDATOR = "build-validator"
    STATUSLINE_SETUP = "statusline-setup"
    PROMPT_SUGGESTION = "aprompt_suggestion"
    OTHER = "other"


class MessageType(str, Enum):
    """Type of message in session."""

    USER = "user"
    ASSISTANT = "assistant"
    FILE_HISTORY_SNAPSHOT = "file-history-snapshot"
    SUMMARY = "summary"


class ContentBlock(BaseModel):
    """Base class for message content blocks."""

    type: str


class TextContent(ContentBlock):
    """Text content block."""

    type: Literal["text"] = "text"
    text: str


class ThinkingContent(ContentBlock):
    """Thinking content block (internal reasoning)."""

    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None


class ToolUseContent(ContentBlock):
    """Tool use content block."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultContent(ContentBlock):
    """Tool result content block."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[dict[str, Any]]
    is_error: bool | None = None


# Union of all content types
MessageContent = (
    TextContent | ThinkingContent | ToolUseContent | ToolResultContent
)


class TokenUsage(BaseModel):
    """Token usage statistics for a message."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    service_tier: str | None = None

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens used."""
        return self.input_tokens + self.output_tokens


class ClaudeMessage(BaseModel):
    """Claude API message structure."""

    role: MessageRole
    content: str | list[dict[str, Any]]
    model: str | None = None
    id: str | None = None
    type: str | None = None
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: TokenUsage | None = None


class ThinkingMetadata(BaseModel):
    """Metadata for thinking/reasoning."""

    maxThinkingTokens: int | None = None


class TodoItem(BaseModel):
    """Todo item in session."""

    content: str
    status: Literal["pending", "in_progress", "completed"]
    activeForm: str


class MessageRecord(BaseModel):
    """
    A single message record from a Claude Code session.

    This represents one JSONL line from a session file, including all metadata.
    """

    # Session context
    sessionId: str
    uuid: str
    timestamp: str
    type: MessageType
    parentUuid: str | None = None

    # User/environment context
    userType: str | None = None
    cwd: str | None = None
    version: str | None = None
    gitBranch: str | None = None

    # Subagent context
    isSidechain: bool | None = None
    agentId: str | None = None

    # Message content
    message: ClaudeMessage | None = None

    # Metadata flags
    isMeta: bool | None = None
    isSnapshotUpdate: bool | None = None

    # Additional metadata
    thinkingMetadata: ThinkingMetadata | None = None
    todos: list[TodoItem] | None = None
    permissionMode: str | None = None

    # Snapshot specific
    snapshot: dict[str, Any] | None = None
    messageId: str | None = None

    # Summary specific
    summary: str | None = None
    leafUuid: str | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate timestamp is in ISO format."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"Invalid timestamp format: {v}") from e
        return v

    @property
    def parsed_timestamp(self) -> datetime:
        """Parse timestamp as datetime object."""
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))

    @property
    def is_user_message(self) -> bool:
        """Check if this is a user message."""
        return self.type == MessageType.USER

    @property
    def is_assistant_message(self) -> bool:
        """Check if this is an assistant message."""
        return self.type == MessageType.ASSISTANT

    @property
    def is_subagent_message(self) -> bool:
        """Check if this message is from a subagent."""
        return self.isSidechain is True

    @property
    def source(self) -> MessageSource:
        """Determine message source."""
        return MessageSource.SUBAGENT if self.is_subagent_message else MessageSource.MAIN


class ToolCallStatistics(BaseModel):
    """Statistics about tool calls in a session."""

    tool_name: str
    count: int
    total_tokens: int = 0
    success_count: int = 0
    error_count: int = 0


class SubagentSession(BaseModel):
    """
    A subagent session nested within a main session.

    Subagents are spawned for specific tasks (e.g., exploration, bash commands).
    """

    agent_id: str
    agent_type: SubagentType
    messages: list[MessageRecord]
    start_time: datetime
    end_time: datetime | None = None
    parent_message_uuid: str

    @property
    def duration_seconds(self) -> float | None:
        """Calculate subagent session duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def message_count(self) -> int:
        """Count of messages in subagent session."""
        return len(self.messages)

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens used in subagent."""
        total = 0
        for msg in self.messages:
            if msg.message and msg.message.usage:
                total += msg.message.usage.total_tokens
        return total


class SessionMetadata(BaseModel):
    """Metadata about a Claude Code session."""

    session_id: str
    project_path: str
    git_branch: str | None = None
    version: str
    created_at: datetime
    updated_at: datetime | None = None
    total_messages: int
    total_tokens: int
    user_type: str | None = None


class SessionStatistics(BaseModel):
    """Comprehensive statistics for a session."""

    message_count: int
    user_message_count: int
    assistant_message_count: int
    system_message_count: int

    # Token statistics
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    # Tool statistics
    tool_calls: list[ToolCallStatistics] = Field(default_factory=list)
    total_tool_calls: int = 0

    # Subagent statistics
    subagent_count: int = 0
    subagent_sessions: dict[str, int] = Field(
        default_factory=dict
    )  # agent_type -> count

    # Time statistics
    session_duration_seconds: float | None = None
    first_message_time: datetime | None = None
    last_message_time: datetime | None = None

    @property
    def average_tokens_per_message(self) -> float:
        """Calculate average tokens per message."""
        if self.message_count == 0:
            return 0.0
        return self.total_tokens / self.message_count

    @property
    def tool_usage_summary(self) -> dict[str, int]:
        """Get tool usage summary as dict."""
        return {tc.tool_name: tc.count for tc in self.tool_calls}


class Session(BaseModel):
    """
    Complete Claude Code session with all messages and subagents.

    This is the top-level model representing a full session file.
    """

    metadata: SessionMetadata
    messages: list[MessageRecord]
    subagent_sessions: list[SubagentSession] = Field(default_factory=list)
    statistics: SessionStatistics | None = None

    @property
    def main_messages(self) -> list[MessageRecord]:
        """Get only main session messages (excluding subagent messages)."""
        return [msg for msg in self.messages if not msg.is_subagent_message]

    @property
    def subagent_messages(self) -> list[MessageRecord]:
        """Get only subagent messages."""
        return [msg for msg in self.messages if msg.is_subagent_message]

    def get_messages_by_type(self, message_type: MessageType) -> list[MessageRecord]:
        """Get messages filtered by type."""
        return [msg for msg in self.messages if msg.type == message_type]

    def get_subagent_by_id(self, agent_id: str) -> SubagentSession | None:
        """Get subagent session by agent ID."""
        for subagent in self.subagent_sessions:
            if subagent.agent_id == agent_id:
                return subagent
        return None

    @field_validator("messages")
    @classmethod
    def validate_messages_not_empty(cls, v: list[MessageRecord]) -> list[MessageRecord]:
        """Ensure messages list is not empty."""
        if not v:
            raise ValueError("Session must have at least one message")
        return v


class SessionIndex(BaseModel):
    """
    Index of all sessions in a project directory.

    This represents the sessions-index.json file.
    """

    sessions: list[dict[str, Any]]
    project_path: str
    last_updated: datetime


class ParsedSessionData(BaseModel):
    """
    Container for all parsed session data from a directory.

    This is the output format for the CLI parser.
    """

    sessions: list[Session]
    session_index: SessionIndex | None = None
    parse_timestamp: datetime = Field(default_factory=datetime.now)
    source_path: str

    @property
    def session_count(self) -> int:
        """Get total number of sessions."""
        return len(self.sessions)

    @property
    def total_messages(self) -> int:
        """Get total message count across all sessions."""
        return sum(len(session.messages) for session in self.sessions)

    @property
    def total_tokens(self) -> int:
        """Get total token count across all sessions."""
        return sum(
            session.metadata.total_tokens
            for session in self.sessions
            if session.metadata.total_tokens
        )
