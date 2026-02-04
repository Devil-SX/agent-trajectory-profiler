"""
Unit tests for session statistics calculation.

Tests cover detailed statistics including tool call tracking, subagent analysis,
token breakdowns, and usage patterns.
"""

import json
from pathlib import Path

import pytest

from claude_vis.models import SessionStatistics, ToolCallStatistics
from claude_vis.parsers import parse_session_file
from claude_vis.parsers.session_parser import (
    calculate_session_statistics,
    extract_subagent_sessions,
    parse_jsonl_file,
)


@pytest.fixture
def temp_session_dir(tmp_path: Path) -> Path:
    """Create a temporary session directory with test files."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    return session_dir


@pytest.fixture
def sample_messages_with_tools() -> list[dict]:
    """Sample session data with tool calls for testing."""
    return [
        {
            "type": "user",
            "sessionId": "test-session-tools",
            "uuid": "msg-1",
            "timestamp": "2026-02-03T13:15:17.231Z",
            "message": {
                "role": "user",
                "content": "Read the file test.py",
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-tools",
            "uuid": "msg-2",
            "timestamp": "2026-02-03T13:15:18.231Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read that file for you."},
                    {
                        "type": "tool_use",
                        "id": "tool-read-1",
                        "name": "Read",
                        "input": {"file_path": "/test.py"},
                    },
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                },
            },
        },
        {
            "type": "user",
            "sessionId": "test-session-tools",
            "uuid": "msg-3",
            "timestamp": "2026-02-03T13:15:19.231Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-read-1",
                        "content": "print('hello')",
                        "is_error": False,
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-tools",
            "uuid": "msg-4",
            "timestamp": "2026-02-03T13:15:20.231Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me edit it."},
                    {
                        "type": "tool_use",
                        "id": "tool-edit-1",
                        "name": "Edit",
                        "input": {
                            "file_path": "/test.py",
                            "old_string": "hello",
                            "new_string": "world",
                        },
                    },
                ],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 60,
                },
            },
        },
        {
            "type": "user",
            "sessionId": "test-session-tools",
            "uuid": "msg-5",
            "timestamp": "2026-02-03T13:15:21.231Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-edit-1",
                        "content": "Error: string not found",
                        "is_error": True,
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-tools",
            "uuid": "msg-6",
            "timestamp": "2026-02-03T13:15:22.231Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me try reading again."},
                    {
                        "type": "tool_use",
                        "id": "tool-read-2",
                        "name": "Read",
                        "input": {"file_path": "/test.py"},
                    },
                ],
                "usage": {
                    "input_tokens": 80,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 25,
                },
            },
        },
        {
            "type": "user",
            "sessionId": "test-session-tools",
            "uuid": "msg-7",
            "timestamp": "2026-02-03T13:15:23.231Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-read-2",
                        "content": "print('hello')",
                        "is_error": False,
                    }
                ],
            },
        },
    ]


@pytest.fixture
def sample_messages_with_subagents() -> list[dict]:
    """Sample session data with subagent messages."""
    return [
        {
            "type": "user",
            "sessionId": "test-session-subagents",
            "uuid": "msg-1",
            "timestamp": "2026-02-03T13:15:17.231Z",
            "message": {
                "role": "user",
                "content": "Explore the codebase",
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-subagents",
            "uuid": "msg-2",
            "timestamp": "2026-02-03T13:15:18.231Z",
            "isSidechain": True,
            "agentId": "explore-agent-1",
            "parentUuid": "msg-1",
            "message": {
                "role": "assistant",
                "content": "Starting exploration...",
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 25,
                },
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-subagents",
            "uuid": "msg-3",
            "timestamp": "2026-02-03T13:15:19.231Z",
            "isSidechain": True,
            "agentId": "explore-agent-1",
            "parentUuid": "msg-1",
            "message": {
                "role": "assistant",
                "content": "Found 10 files...",
                "usage": {
                    "input_tokens": 60,
                    "output_tokens": 30,
                },
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-subagents",
            "uuid": "msg-4",
            "timestamp": "2026-02-03T13:15:20.231Z",
            "isSidechain": True,
            "agentId": "bash-agent-1",
            "parentUuid": "msg-1",
            "message": {
                "role": "assistant",
                "content": "Running bash command...",
                "usage": {
                    "input_tokens": 40,
                    "output_tokens": 20,
                },
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-subagents",
            "uuid": "msg-5",
            "timestamp": "2026-02-03T13:15:21.231Z",
            "message": {
                "role": "assistant",
                "content": "Exploration complete.",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                },
            },
        },
    ]


class TestCalculateSessionStatistics:
    """Tests for calculate_session_statistics function."""

    def test_basic_message_counts(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test basic message counting."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        assert stats.message_count == 7
        # Tool result messages have "user" type in the sample data
        # 1 initial user message + 3 tool_result user messages = 4 user messages
        assert stats.user_message_count == 4
        assert stats.assistant_message_count == 3

    def test_token_statistics(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test token counting and breakdown."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        # Total: (100+50) + (120+60) + (80+40) = 450
        assert stats.total_tokens == 450
        assert stats.total_input_tokens == 300
        assert stats.total_output_tokens == 150
        assert stats.cache_read_tokens == 50
        assert stats.cache_creation_tokens == 25

    def test_tool_call_statistics(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test tool call counting and statistics."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        assert stats.total_tool_calls == 3  # 2 Read + 1 Edit
        assert len(stats.tool_calls) == 2  # Read and Edit

        # Find Read tool stats
        read_tool = next((tc for tc in stats.tool_calls if tc.tool_name == "Read"), None)
        assert read_tool is not None
        assert read_tool.count == 2
        assert read_tool.success_count == 2
        assert read_tool.error_count == 0

        # Find Edit tool stats
        edit_tool = next((tc for tc in stats.tool_calls if tc.tool_name == "Edit"), None)
        assert edit_tool is not None
        assert edit_tool.count == 1
        assert edit_tool.success_count == 0
        assert edit_tool.error_count == 1

    def test_tool_token_breakdown(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test tool-specific token usage tracking."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        # Read tool: (100+50) + (80+40) = 270
        read_tool = next((tc for tc in stats.tool_calls if tc.tool_name == "Read"), None)
        assert read_tool is not None
        assert read_tool.total_tokens == 270

        # Edit tool: (120+60) = 180
        edit_tool = next((tc for tc in stats.tool_calls if tc.tool_name == "Edit"), None)
        assert edit_tool is not None
        assert edit_tool.total_tokens == 180

    def test_session_duration(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test session duration calculation."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        # Duration: 2026-02-03T13:15:23.231Z - 2026-02-03T13:15:17.231Z = 6 seconds
        assert stats.session_duration_seconds == 6.0
        assert stats.first_message_time is not None
        assert stats.last_message_time is not None

    def test_most_used_tools(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test most used tools property."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        most_used = stats.most_used_tools
        assert len(most_used) == 2
        # Read should be first (2 calls)
        assert most_used[0][0] == "Read"
        assert most_used[0][1] == 2
        # Edit should be second (1 call)
        assert most_used[1][0] == "Edit"
        assert most_used[1][1] == 1


class TestExtractSubagentSessions:
    """Tests for extract_subagent_sessions function."""

    def test_extract_subagent_sessions(
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict]
    ) -> None:
        """Test extracting subagent sessions from messages."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_subagents:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        subagent_sessions = extract_subagent_sessions(messages)

        assert len(subagent_sessions) == 2  # explore-agent-1 and bash-agent-1

    def test_subagent_message_grouping(
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict]
    ) -> None:
        """Test that subagent messages are grouped correctly."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_subagents:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        subagent_sessions = extract_subagent_sessions(messages)

        # Find explore-agent-1
        explore_agent = next(
            (s for s in subagent_sessions if s.agent_id == "explore-agent-1"), None
        )
        assert explore_agent is not None
        assert explore_agent.message_count == 2

        # Find bash-agent-1
        bash_agent = next(
            (s for s in subagent_sessions if s.agent_id == "bash-agent-1"), None
        )
        assert bash_agent is not None
        assert bash_agent.message_count == 1

    def test_subagent_statistics(
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict]
    ) -> None:
        """Test subagent statistics in session stats."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_subagents:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        assert stats.subagent_count == 2
        # Both should be counted as "other" type
        assert "other" in stats.subagent_sessions
        assert stats.subagent_sessions["other"] == 2


class TestSessionStatisticsProperties:
    """Tests for SessionStatistics computed properties."""

    def test_average_tokens_per_message(self) -> None:
        """Test average tokens per message calculation."""
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

    def test_average_tokens_empty_session(self) -> None:
        """Test average tokens for empty session."""
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

    def test_tool_success_rate(self) -> None:
        """Test tool success rate calculation."""
        stats = SessionStatistics(
            message_count=5,
            user_message_count=2,
            assistant_message_count=3,
            system_message_count=0,
            total_tokens=500,
            total_input_tokens=300,
            total_output_tokens=200,
            tool_calls=[
                ToolCallStatistics(
                    tool_name="Read", count=5, success_count=4, error_count=1, total_tokens=200
                ),
                ToolCallStatistics(
                    tool_name="Edit", count=3, success_count=1, error_count=2, total_tokens=150
                ),
                ToolCallStatistics(
                    tool_name="Write",
                    count=2,
                    success_count=2,
                    error_count=0,
                    total_tokens=100,
                ),
            ],
        )

        success_rates = stats.tool_success_rate
        assert success_rates["Read"] == 0.8  # 4/5
        assert abs(success_rates["Edit"] - 0.333333) < 0.01  # 1/3
        assert success_rates["Write"] == 1.0  # 2/2

    def test_tool_token_breakdown(self) -> None:
        """Test tool token breakdown."""
        stats = SessionStatistics(
            message_count=5,
            user_message_count=2,
            assistant_message_count=3,
            system_message_count=0,
            total_tokens=500,
            total_input_tokens=300,
            total_output_tokens=200,
            tool_calls=[
                ToolCallStatistics(
                    tool_name="Read", count=5, success_count=5, error_count=0, total_tokens=200
                ),
                ToolCallStatistics(
                    tool_name="Edit", count=3, success_count=3, error_count=0, total_tokens=150
                ),
            ],
        )

        breakdown = stats.tool_token_breakdown
        assert breakdown["Read"] == 200
        assert breakdown["Edit"] == 150

    def test_most_error_prone_tools(self) -> None:
        """Test most error prone tools identification."""
        stats = SessionStatistics(
            message_count=5,
            user_message_count=2,
            assistant_message_count=3,
            system_message_count=0,
            total_tokens=500,
            total_input_tokens=300,
            total_output_tokens=200,
            tool_calls=[
                ToolCallStatistics(
                    tool_name="Read", count=5, success_count=4, error_count=1, total_tokens=200
                ),
                ToolCallStatistics(
                    tool_name="Edit", count=3, success_count=0, error_count=3, total_tokens=150
                ),
                ToolCallStatistics(
                    tool_name="Write",
                    count=2,
                    success_count=2,
                    error_count=0,
                    total_tokens=100,
                ),
            ],
        )

        error_prone = stats.most_error_prone_tools
        assert len(error_prone) == 2
        assert error_prone[0] == ("Edit", 3)
        assert error_prone[1] == ("Read", 1)

    def test_get_top_tools(self) -> None:
        """Test getting top N tools."""
        stats = SessionStatistics(
            message_count=10,
            user_message_count=5,
            assistant_message_count=5,
            system_message_count=0,
            total_tokens=1000,
            total_input_tokens=600,
            total_output_tokens=400,
            tool_calls=[
                ToolCallStatistics(
                    tool_name="Read", count=10, success_count=10, error_count=0, total_tokens=300
                ),
                ToolCallStatistics(
                    tool_name="Edit", count=8, success_count=8, error_count=0, total_tokens=250
                ),
                ToolCallStatistics(
                    tool_name="Write",
                    count=5,
                    success_count=5,
                    error_count=0,
                    total_tokens=200,
                ),
                ToolCallStatistics(
                    tool_name="Bash", count=3, success_count=3, error_count=0, total_tokens=150
                ),
            ],
        )

        top_3 = stats.get_top_tools(3)
        assert len(top_3) == 3
        assert top_3[0].tool_name == "Read"
        assert top_3[1].tool_name == "Edit"
        assert top_3[2].tool_name == "Write"


class TestIntegrationWithParseSessionFile:
    """Integration tests with the full parse_session_file function."""

    def test_full_session_parsing_with_statistics(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict]
    ) -> None:
        """Test that parse_session_file includes complete statistics."""
        file_path = temp_session_dir / "test-session.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        session = parse_session_file(file_path)

        assert session.statistics is not None
        assert session.statistics.total_tool_calls == 3
        assert len(session.statistics.tool_calls) == 2
        assert session.statistics.total_tokens == 450

    def test_full_session_with_subagents(
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict]
    ) -> None:
        """Test that parse_session_file includes subagent sessions."""
        file_path = temp_session_dir / "test-session.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_subagents:
                f.write(json.dumps(data) + "\n")

        session = parse_session_file(file_path)

        assert len(session.subagent_sessions) == 2
        assert session.statistics is not None
        assert session.statistics.subagent_count == 2
