"""
Unit tests for Pydantic models in claude_vis.models.

Tests cover model validation, type checking, and business logic.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from claude_vis.models import (
    ClaudeMessage,
    MessageRecord,
    MessageRole,
    MessageSource,
    MessageType,
    ParsedSessionData,
    Session,
    SessionMetadata,
    SessionStatistics,
    SubagentSession,
    SubagentType,
    TextContent,
    ThinkingContent,
    TodoItem,
    TokenUsage,
    ToolCallStatistics,
)


class TestTokenUsage:
    """Tests for TokenUsage model."""

    def test_valid_token_usage(self) -> None:
        """Test creating valid token usage."""
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=20,
            cache_read_input_tokens=30,
        )
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150

    def test_token_usage_defaults(self) -> None:
        """Test token usage with default values."""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_total_tokens_property(self) -> None:
        """Test total_tokens calculated property."""
        usage = TokenUsage(input_tokens=75, output_tokens=25)
        assert usage.total_tokens == 100


class TestClaudeMessage:
    """Tests for ClaudeMessage model."""

    def test_valid_user_message(self) -> None:
        """Test creating valid user message."""
        msg = ClaudeMessage(role=MessageRole.USER, content="Hello Claude")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello Claude"

    def test_valid_assistant_message_with_usage(self) -> None:
        """Test assistant message with token usage."""
        msg = ClaudeMessage(
            role=MessageRole.ASSISTANT,
            content="Hello!",
            model="claude-opus-4-5-20251101",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )
        assert msg.role == MessageRole.ASSISTANT
        assert msg.usage is not None
        assert msg.usage.total_tokens == 15

    def test_message_with_list_content(self) -> None:
        """Test message with list content."""
        content = [{"type": "text", "text": "Hello"}]
        msg = ClaudeMessage(role=MessageRole.ASSISTANT, content=content)
        assert isinstance(msg.content, list)
        assert len(msg.content) == 1


class TestMessageRecord:
    """Tests for MessageRecord model."""

    def test_valid_message_record(self) -> None:
        """Test creating valid message record."""
        record = MessageRecord(
            sessionId="test-session-123",
            uuid="msg-uuid-456",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
            userType="external",
            cwd="/home/user/project",
        )
        assert record.sessionId == "test-session-123"
        assert record.uuid == "msg-uuid-456"
        assert record.type == MessageType.USER

    def test_timestamp_validation(self) -> None:
        """Test timestamp validation."""
        with pytest.raises(ValidationError) as exc_info:
            MessageRecord(
                sessionId="test",
                uuid="test",
                timestamp="invalid-timestamp",
                type=MessageType.USER,
            )
        assert "Invalid timestamp format" in str(exc_info.value)

    def test_parsed_timestamp_property(self) -> None:
        """Test parsed_timestamp property."""
        record = MessageRecord(
            sessionId="test",
            uuid="test",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        dt = record.parsed_timestamp
        assert isinstance(dt, datetime)
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 3

    def test_is_user_message_property(self) -> None:
        """Test is_user_message property."""
        record = MessageRecord(
            sessionId="test",
            uuid="test",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        assert record.is_user_message is True
        assert record.is_assistant_message is False

    def test_is_assistant_message_property(self) -> None:
        """Test is_assistant_message property."""
        record = MessageRecord(
            sessionId="test",
            uuid="test",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.ASSISTANT,
        )
        assert record.is_assistant_message is True
        assert record.is_user_message is False

    def test_is_subagent_message_property(self) -> None:
        """Test is_subagent_message property."""
        record = MessageRecord(
            sessionId="test",
            uuid="test",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
            isSidechain=True,
            agentId="aprompt_suggestion-abc123",
        )
        assert record.is_subagent_message is True
        assert record.source == MessageSource.SUBAGENT

    def test_main_message_source(self) -> None:
        """Test main message source detection."""
        record = MessageRecord(
            sessionId="test",
            uuid="test",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
            isSidechain=False,
        )
        assert record.is_subagent_message is False
        assert record.source == MessageSource.MAIN


class TestSubagentSession:
    """Tests for SubagentSession model."""

    def test_valid_subagent_session(self) -> None:
        """Test creating valid subagent session."""
        msg = MessageRecord(
            sessionId="test",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        session = SubagentSession(
            agent_id="explore-agent-123",
            agent_type=SubagentType.EXPLORE,
            messages=[msg],
            start_time=datetime.now(timezone.utc),
            parent_message_uuid="parent-uuid",
        )
        assert session.agent_id == "explore-agent-123"
        assert session.agent_type == SubagentType.EXPLORE
        assert session.message_count == 1

    def test_subagent_duration_calculation(self) -> None:
        """Test duration calculation for subagent."""
        start = datetime(2026, 2, 3, 13, 15, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 3, 13, 16, 30, tzinfo=timezone.utc)
        session = SubagentSession(
            agent_id="test",
            agent_type=SubagentType.BASH,
            messages=[],
            start_time=start,
            end_time=end,
            parent_message_uuid="parent",
        )
        assert session.duration_seconds == 90.0

    def test_subagent_no_end_time(self) -> None:
        """Test subagent without end time."""
        session = SubagentSession(
            agent_id="test",
            agent_type=SubagentType.PLAN,
            messages=[],
            start_time=datetime.now(timezone.utc),
            parent_message_uuid="parent",
        )
        assert session.duration_seconds is None

    def test_subagent_total_tokens(self) -> None:
        """Test total token calculation for subagent."""
        msg1 = MessageRecord(
            sessionId="test",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.ASSISTANT,
            message=ClaudeMessage(
                role=MessageRole.ASSISTANT,
                content="Response",
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            ),
        )
        msg2 = MessageRecord(
            sessionId="test",
            uuid="msg2",
            timestamp="2026-02-03T13:15:18.231Z",
            type=MessageType.ASSISTANT,
            message=ClaudeMessage(
                role=MessageRole.ASSISTANT,
                content="Another response",
                usage=TokenUsage(input_tokens=20, output_tokens=10),
            ),
        )
        session = SubagentSession(
            agent_id="test",
            agent_type=SubagentType.GENERAL_PURPOSE,
            messages=[msg1, msg2],
            start_time=datetime.now(timezone.utc),
            parent_message_uuid="parent",
        )
        assert session.total_tokens == 45


class TestSessionMetadata:
    """Tests for SessionMetadata model."""

    def test_valid_metadata(self) -> None:
        """Test creating valid session metadata."""
        now = datetime.now(timezone.utc)
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            git_branch="main",
            version="2.1.29",
            created_at=now,
            total_messages=100,
            total_tokens=5000,
        )
        assert metadata.session_id == "session-123"
        assert metadata.total_messages == 100
        assert metadata.total_tokens == 5000


class TestSessionStatistics:
    """Tests for SessionStatistics model."""

    def test_valid_statistics(self) -> None:
        """Test creating valid session statistics."""
        stats = SessionStatistics(
            message_count=150,
            user_message_count=75,
            assistant_message_count=70,
            system_message_count=5,
            total_tokens=10000,
            total_input_tokens=6000,
            total_output_tokens=4000,
        )
        assert stats.message_count == 150
        assert stats.total_tokens == 10000

    def test_average_tokens_per_message(self) -> None:
        """Test average tokens calculation."""
        stats = SessionStatistics(
            message_count=10,
            user_message_count=5,
            assistant_message_count=5,
            system_message_count=0,
            total_tokens=1000,
            total_input_tokens=600,
            total_output_tokens=400,
        )
        assert stats.average_tokens_per_message == 100.0

    def test_average_tokens_zero_messages(self) -> None:
        """Test average tokens with zero messages."""
        stats = SessionStatistics(
            message_count=0,
            user_message_count=0,
            assistant_message_count=0,
            system_message_count=0,
            total_tokens=0,
            total_input_tokens=0,
            total_output_tokens=0,
        )
        assert stats.average_tokens_per_message == 0.0

    def test_tool_usage_summary(self) -> None:
        """Test tool usage summary property."""
        tool_calls = [
            ToolCallStatistics(tool_name="Read", count=10, total_tokens=500),
            ToolCallStatistics(tool_name="Write", count=5, total_tokens=300),
            ToolCallStatistics(tool_name="Bash", count=3, total_tokens=200),
        ]
        stats = SessionStatistics(
            message_count=50,
            user_message_count=25,
            assistant_message_count=25,
            system_message_count=0,
            total_tokens=5000,
            total_input_tokens=3000,
            total_output_tokens=2000,
            tool_calls=tool_calls,
            total_tool_calls=18,
        )
        summary = stats.tool_usage_summary
        assert summary["Read"] == 10
        assert summary["Write"] == 5
        assert summary["Bash"] == 3


class TestSession:
    """Tests for Session model."""

    def test_valid_session(self) -> None:
        """Test creating valid session."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=2,
            total_tokens=100,
        )
        msg1 = MessageRecord(
            sessionId="session-123",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        msg2 = MessageRecord(
            sessionId="session-123",
            uuid="msg2",
            timestamp="2026-02-03T13:15:18.231Z",
            type=MessageType.ASSISTANT,
        )
        session = Session(metadata=metadata, messages=[msg1, msg2])
        assert session.metadata.session_id == "session-123"
        assert len(session.messages) == 2

    def test_session_empty_messages_validation(self) -> None:
        """Test that session must have at least one message."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=0,
            total_tokens=0,
        )
        with pytest.raises(ValidationError) as exc_info:
            Session(metadata=metadata, messages=[])
        assert "Session must have at least one message" in str(exc_info.value)

    def test_main_messages_filter(self) -> None:
        """Test filtering main messages."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=3,
            total_tokens=100,
        )
        msg1 = MessageRecord(
            sessionId="session-123",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
            isSidechain=False,
        )
        msg2 = MessageRecord(
            sessionId="session-123",
            uuid="msg2",
            timestamp="2026-02-03T13:15:18.231Z",
            type=MessageType.ASSISTANT,
            isSidechain=True,
        )
        msg3 = MessageRecord(
            sessionId="session-123",
            uuid="msg3",
            timestamp="2026-02-03T13:15:19.231Z",
            type=MessageType.USER,
            isSidechain=False,
        )
        session = Session(metadata=metadata, messages=[msg1, msg2, msg3])
        main = session.main_messages
        assert len(main) == 2
        assert all(not msg.is_subagent_message for msg in main)

    def test_subagent_messages_filter(self) -> None:
        """Test filtering subagent messages."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=3,
            total_tokens=100,
        )
        msg1 = MessageRecord(
            sessionId="session-123",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
            isSidechain=False,
        )
        msg2 = MessageRecord(
            sessionId="session-123",
            uuid="msg2",
            timestamp="2026-02-03T13:15:18.231Z",
            type=MessageType.ASSISTANT,
            isSidechain=True,
        )
        msg3 = MessageRecord(
            sessionId="session-123",
            uuid="msg3",
            timestamp="2026-02-03T13:15:19.231Z",
            type=MessageType.USER,
            isSidechain=False,
        )
        session = Session(metadata=metadata, messages=[msg1, msg2, msg3])
        subagent = session.subagent_messages
        assert len(subagent) == 1
        assert all(msg.is_subagent_message for msg in subagent)

    def test_get_messages_by_type(self) -> None:
        """Test filtering messages by type."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=3,
            total_tokens=100,
        )
        msg1 = MessageRecord(
            sessionId="session-123",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        msg2 = MessageRecord(
            sessionId="session-123",
            uuid="msg2",
            timestamp="2026-02-03T13:15:18.231Z",
            type=MessageType.ASSISTANT,
        )
        msg3 = MessageRecord(
            sessionId="session-123",
            uuid="msg3",
            timestamp="2026-02-03T13:15:19.231Z",
            type=MessageType.USER,
        )
        session = Session(metadata=metadata, messages=[msg1, msg2, msg3])
        user_msgs = session.get_messages_by_type(MessageType.USER)
        assert len(user_msgs) == 2
        assert all(msg.type == MessageType.USER for msg in user_msgs)

    def test_get_subagent_by_id(self) -> None:
        """Test retrieving subagent by ID."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=1,
            total_tokens=100,
        )
        msg = MessageRecord(
            sessionId="session-123",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        subagent = SubagentSession(
            agent_id="explore-123",
            agent_type=SubagentType.EXPLORE,
            messages=[msg],
            start_time=datetime.now(timezone.utc),
            parent_message_uuid="parent",
        )
        session = Session(
            metadata=metadata, messages=[msg], subagent_sessions=[subagent]
        )
        found = session.get_subagent_by_id("explore-123")
        assert found is not None
        assert found.agent_id == "explore-123"

        not_found = session.get_subagent_by_id("nonexistent")
        assert not_found is None


class TestParsedSessionData:
    """Tests for ParsedSessionData model."""

    def test_valid_parsed_data(self) -> None:
        """Test creating valid parsed session data."""
        metadata = SessionMetadata(
            session_id="session-123",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=1,
            total_tokens=100,
        )
        msg = MessageRecord(
            sessionId="session-123",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        session = Session(metadata=metadata, messages=[msg])
        parsed = ParsedSessionData(
            sessions=[session], source_path="/home/user/.claude/projects"
        )
        assert parsed.session_count == 1
        assert parsed.total_messages == 1

    def test_parsed_data_properties(self) -> None:
        """Test parsed data calculated properties."""
        metadata1 = SessionMetadata(
            session_id="session-1",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=10,
            total_tokens=500,
        )
        metadata2 = SessionMetadata(
            session_id="session-2",
            project_path="/home/user/project",
            version="2.1.29",
            created_at=datetime.now(timezone.utc),
            total_messages=20,
            total_tokens=1000,
        )
        msg1 = MessageRecord(
            sessionId="session-1",
            uuid="msg1",
            timestamp="2026-02-03T13:15:17.231Z",
            type=MessageType.USER,
        )
        msg2 = MessageRecord(
            sessionId="session-2",
            uuid="msg2",
            timestamp="2026-02-03T13:15:18.231Z",
            type=MessageType.USER,
        )
        session1 = Session(metadata=metadata1, messages=[msg1])
        session2 = Session(metadata=metadata2, messages=[msg2])
        parsed = ParsedSessionData(
            sessions=[session1, session2], source_path="/test"
        )
        assert parsed.session_count == 2
        assert parsed.total_messages == 2
        assert parsed.total_tokens == 1500


class TestContentBlocks:
    """Tests for content block models."""

    def test_text_content(self) -> None:
        """Test TextContent model."""
        content = TextContent(text="Hello world")
        assert content.type == "text"
        assert content.text == "Hello world"

    def test_thinking_content(self) -> None:
        """Test ThinkingContent model."""
        content = ThinkingContent(thinking="Internal reasoning", signature="sig123")
        assert content.type == "thinking"
        assert content.thinking == "Internal reasoning"
        assert content.signature == "sig123"


class TestTodoItem:
    """Tests for TodoItem model."""

    def test_valid_todo_item(self) -> None:
        """Test creating valid todo item."""
        todo = TodoItem(
            content="Complete the feature",
            status="in_progress",
            activeForm="Completing the feature",
        )
        assert todo.content == "Complete the feature"
        assert todo.status == "in_progress"
        assert todo.activeForm == "Completing the feature"
