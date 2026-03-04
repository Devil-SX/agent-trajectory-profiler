"""
Type-safe Pydantic models for Claude Code session data.

This module defines comprehensive data models for parsing and validating
Claude Code session files, including support for nested subagent sessions,
tool calls, and message structures.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator


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
MessageContent = TextContent | ThinkingContent | ToolUseContent | ToolResultContent


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


class TimeBreakdown(BaseModel):
    """Breakdown of session time by category."""

    total_model_time_seconds: float = 0.0
    total_tool_time_seconds: float = 0.0
    total_user_time_seconds: float = 0.0
    total_inactive_time_seconds: float = 0.0
    total_active_time_seconds: float = 0.0
    model_time_percent: float = 0.0
    tool_time_percent: float = 0.0
    user_time_percent: float = 0.0
    inactive_time_percent: float = 0.0
    active_time_ratio: float = 0.0
    inactivity_threshold_seconds: float = 1800.0
    user_interaction_count: int = 0
    interactions_per_hour: float = 0.0
    model_timeout_count: int = 0
    model_timeout_threshold_seconds: float = 600.0


class TokenBreakdown(BaseModel):
    """Percentage breakdown of token usage by category."""

    input_percent: float = 0.0
    output_percent: float = 0.0
    cache_read_percent: float = 0.0
    cache_creation_percent: float = 0.0


class CharacterBreakdown(BaseModel):
    """Character counts by producer and script family."""

    total_chars: int = 0
    user_chars: int = 0
    model_chars: int = 0
    tool_chars: int = 0
    cjk_chars: int = 0
    latin_chars: int = 0
    digit_chars: int = 0
    whitespace_chars: int = 0
    other_chars: int = 0


class ToolCallStatistics(BaseModel):
    """Statistics about tool calls in a session."""

    tool_name: str
    count: int
    total_tokens: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency_seconds: float = 0.0
    avg_latency_seconds: float = 0.0
    tool_group: str = ""


class ToolErrorRecord(BaseModel):
    """Detailed record for one failed tool execution."""

    timestamp: str
    tool_name: str
    tool_call_id: str | None = None
    category: str
    matched_rule: str | None = None
    summary: str | None = None
    preview: str
    detail_snippet: str | None = None
    detail: str


class ToolGroupStatistics(BaseModel):
    """Aggregated statistics for a group of related tools (e.g., all MCP tools from one server)."""

    group_name: str
    count: int = 0
    total_tokens: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency_seconds: float = 0.0
    avg_latency_seconds: float = 0.0
    tool_count: int = 0
    tools: list[str] = Field(default_factory=list)


class CompactEvent(BaseModel):
    """A single auto-compact (context summarization) event."""

    timestamp: str
    trigger: str = "auto"
    pre_tokens: int = 0


class BashCommandStats(BaseModel):
    """Stats for a base command (e.g. 'grep', 'python') used within Bash calls."""

    command_name: str
    count: int = 0
    total_latency_seconds: float = 0.0
    avg_latency_seconds: float = 0.0
    total_output_chars: int = 0
    avg_output_chars: float = 0.0


class BashBreakdown(BaseModel):
    """Detailed breakdown of Bash tool usage."""

    total_calls: int = 0
    total_sub_commands: int = 0
    avg_commands_per_call: float = 0.0
    commands_per_call_distribution: dict[int, int] = Field(default_factory=dict)
    command_stats: list[BashCommandStats] = Field(default_factory=list)


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
    physical_session_id: str | None = None
    logical_session_id: str | None = None
    parent_session_id: str | None = None
    root_session_id: str | None = None
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
    trajectory_file_size_bytes: int = 0
    character_breakdown: CharacterBreakdown = Field(default_factory=CharacterBreakdown)
    user_yield_ratio_tokens: float | None = None
    user_yield_ratio_chars: float | None = None
    avg_tokens_per_second: float | None = None
    read_tokens_per_second: float | None = None
    output_tokens_per_second: float | None = None
    cache_tokens_per_second: float | None = None
    cache_read_tokens_per_second: float | None = None
    cache_creation_tokens_per_second: float | None = None

    # Tool statistics
    tool_calls: list[ToolCallStatistics] = Field(default_factory=list)
    tool_groups: list[ToolGroupStatistics] = Field(default_factory=list)
    total_tool_calls: int = 0
    tool_error_records: list[ToolErrorRecord] = Field(default_factory=list)
    tool_error_category_counts: dict[str, int] = Field(default_factory=dict)
    error_taxonomy_version: str = "0.0.0"

    # Subagent statistics
    subagent_count: int = 0
    subagent_sessions: dict[str, int] = Field(default_factory=dict)  # agent_type -> count

    # Time statistics
    session_duration_seconds: float | None = None
    first_message_time: datetime | None = None
    last_message_time: datetime | None = None

    # Time and token breakdowns
    time_breakdown: TimeBreakdown | None = None
    token_breakdown: TokenBreakdown | None = None

    # Bash breakdown
    bash_breakdown: BashBreakdown | None = None

    # Auto-compact events
    compact_count: int = 0
    compact_events: list[CompactEvent] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def average_tokens_per_message(self) -> float:
        """Calculate average tokens per message."""
        if self.message_count == 0:
            return 0.0
        return self.total_tokens / self.message_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def leverage_ratio_tokens(self) -> float | None:
        """Alias of token yield ratio for leverage-oriented API clients."""
        return self.user_yield_ratio_tokens

    @computed_field  # type: ignore[prop-decorator]
    @property
    def leverage_ratio_chars(self) -> float | None:
        """Alias of character yield ratio for leverage-oriented API clients."""
        return self.user_yield_ratio_chars

    @property
    def tool_usage_summary(self) -> dict[str, int]:
        """Get tool usage summary as dict."""
        return {tc.tool_name: tc.count for tc in self.tool_calls}

    @property
    def most_used_tools(self) -> list[tuple[str, int]]:
        """
        Get the most used tools sorted by usage count.

        Returns:
            List of tuples (tool_name, count) sorted by count descending
        """
        return [(tc.tool_name, tc.count) for tc in self.tool_calls]

    @property
    def tool_success_rate(self) -> dict[str, float]:
        """
        Calculate success rate for each tool.

        Returns:
            Dict mapping tool_name to success rate (0.0 to 1.0)
        """
        rates = {}
        for tc in self.tool_calls:
            total_results = tc.success_count + tc.error_count
            if total_results > 0:
                rates[tc.tool_name] = tc.success_count / total_results
            else:
                # No results tracked, assume 100% success
                rates[tc.tool_name] = 1.0
        return rates

    @property
    def tool_token_breakdown(self) -> dict[str, int]:
        """
        Get token usage breakdown by tool.

        Returns:
            Dict mapping tool_name to total tokens consumed
        """
        return {tc.tool_name: tc.total_tokens for tc in self.tool_calls}

    @property
    def total_tool_errors(self) -> int:
        """Calculate total number of tool errors."""
        return sum(tc.error_count for tc in self.tool_calls)

    @property
    def most_error_prone_tools(self) -> list[tuple[str, int]]:
        """
        Get tools with the most errors.

        Returns:
            List of tuples (tool_name, error_count) sorted by error count descending
        """
        tools_with_errors = [
            (tc.tool_name, tc.error_count) for tc in self.tool_calls if tc.error_count > 0
        ]
        return sorted(tools_with_errors, key=lambda x: x[1], reverse=True)

    def get_top_tools(self, n: int = 5) -> list[ToolCallStatistics]:
        """
        Get top N most frequently used tools.

        Args:
            n: Number of top tools to return

        Returns:
            List of ToolCallStatistics for the top N tools
        """
        return self.tool_calls[:n]


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
