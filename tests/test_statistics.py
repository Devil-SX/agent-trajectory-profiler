"""
Unit tests for session statistics calculation.

Tests cover detailed statistics including tool call tracking, subagent analysis,
token breakdowns, and usage patterns.
"""

import json
from pathlib import Path

import pytest

from agent_vis.models import SessionStatistics, ToolCallStatistics
from agent_vis.parsers import parse_session_file
from agent_vis.parsers.claude_code import parse_jsonl_file_with_compact_events
from agent_vis.parsers.error_taxonomy import (
    ERROR_TAXONOMY_VERSION,
    UNCATEGORIZED_ERROR,
)
from agent_vis.parsers.session_parser import (
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
def sample_messages_with_tools() -> list[dict[str, object]]:
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
def sample_messages_with_subagents() -> list[dict[str, object]]:
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
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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

    def test_user_yield_ratios(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
    ) -> None:
        """Token/character yield ratios should be computed with available denominators."""
        file_path = temp_session_dir / "test-yield.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        assert stats.user_yield_ratio_tokens == pytest.approx(2.0, abs=1e-6)
        assert stats.user_yield_ratio_chars is not None
        assert stats.user_yield_ratio_chars > 0
        assert stats.leverage_ratio_tokens == pytest.approx(stats.user_yield_ratio_tokens, abs=1e-6)
        assert stats.leverage_ratio_chars == pytest.approx(stats.user_yield_ratio_chars, abs=1e-6)

    def test_user_yield_ratios_low_leverage(self, temp_session_dir: Path) -> None:
        """Low-output sessions should surface leverage ratios below 1.0."""
        file_path = temp_session_dir / "test-yield-low.jsonl"
        messages = [
            {
                "type": "user",
                "sessionId": "yield-low",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T10:00:00.000Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "A" * 100}],
                },
            },
            {
                "type": "assistant",
                "sessionId": "yield-low",
                "uuid": "msg-2",
                "timestamp": "2026-02-03T10:00:10.000Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {"input_tokens": 200, "output_tokens": 20},
                },
            },
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for data in messages:
                f.write(json.dumps(data) + "\n")

        parsed = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(parsed)

        assert stats.user_yield_ratio_tokens is not None
        assert stats.user_yield_ratio_tokens < 1.0
        assert stats.leverage_ratio_tokens is not None
        assert stats.leverage_ratio_tokens < 1.0

    def test_tool_error_records_are_categorized(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
    ) -> None:
        """Failed tool results should produce detailed taxonomy records."""
        file_path = temp_session_dir / "test.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        assert stats.error_taxonomy_version == ERROR_TAXONOMY_VERSION
        assert len(stats.tool_error_records) == 1
        first_error = stats.tool_error_records[0]
        assert first_error.tool_name == "Edit"
        assert first_error.tool_call_id == "tool-edit-1"
        assert first_error.category == "file_not_found"
        assert first_error.matched_rule == "file_not_found"
        assert first_error.summary is not None
        assert first_error.detail_snippet is not None
        assert "string not found" in first_error.detail
        assert stats.tool_error_category_counts == {"file_not_found": 1}

    def test_tool_error_records_fallback_to_uncategorized(self, temp_session_dir: Path) -> None:
        """Unknown error text should map to uncategorized bucket."""
        file_path = temp_session_dir / "unknown-error.jsonl"
        unknown_error_messages = [
            {
                "type": "assistant",
                "sessionId": "session-unknown-error",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T13:15:17.231Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-custom-1",
                            "name": "CustomTool",
                            "input": {"query": "data"},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "sessionId": "session-unknown-error",
                "uuid": "msg-2",
                "timestamp": "2026-02-03T13:15:18.231Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-custom-1",
                            "content": "mysterious widget meltdown in subsystem omega",
                            "is_error": True,
                        }
                    ],
                },
            },
        ]

        with open(file_path, "w", encoding="utf-8") as f:
            for data in unknown_error_messages:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)

        assert len(stats.tool_error_records) == 1
        assert stats.tool_error_records[0].category == UNCATEGORIZED_ERROR
        assert stats.tool_error_records[0].matched_rule is None
        assert stats.tool_error_category_counts == {UNCATEGORIZED_ERROR: 1}

    def test_tool_result_without_tool_use_still_records_error_metadata(
        self, temp_session_dir: Path
    ) -> None:
        """Result-only tool records should still feed error timeline annotations."""
        file_path = temp_session_dir / "result-only-error.jsonl"
        messages = [
            {
                "type": "user",
                "sessionId": "session-result-only",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T13:15:17.231Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "web-search-1",
                            "tool_name": "web_search_call",
                            "content": "web_search failed: timeout",
                            "is_error": True,
                        }
                    ],
                },
            }
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for data in messages:
                f.write(json.dumps(data) + "\n")

        parsed = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(parsed)

        assert stats.total_tool_calls == 1
        assert len(stats.tool_calls) == 1
        assert stats.tool_calls[0].tool_name == "web_search_call"
        assert stats.tool_calls[0].error_count == 1
        assert len(stats.tool_error_records) == 1
        assert stats.tool_error_records[0].tool_call_id == "web-search-1"

    def test_user_yield_ratio_zero_denominator(self, temp_session_dir: Path) -> None:
        """Yield ratios should be None when denominator inputs are absent."""
        file_path = temp_session_dir / "yield-zero.jsonl"
        messages = [
            {
                "type": "assistant",
                "sessionId": "yield-zero",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T13:15:17.231Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "output only"}],
                    "usage": {"input_tokens": 0, "output_tokens": 20},
                },
            }
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for data in messages:
                f.write(json.dumps(data) + "\n")

        parsed = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(parsed)
        assert stats.user_yield_ratio_tokens is None
        assert stats.user_yield_ratio_chars is None
        assert stats.leverage_ratio_tokens is None
        assert stats.leverage_ratio_chars is None

    def test_model_throughput_rates(self, temp_session_dir: Path) -> None:
        """Model throughput rates should use model active seconds as denominator."""
        file_path = temp_session_dir / "throughput.jsonl"
        messages = [
            {
                "type": "user",
                "sessionId": "throughput-session",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T10:00:00.000Z",
                "message": {"role": "user", "content": "start"},
            },
            {
                "type": "assistant",
                "sessionId": "throughput-session",
                "uuid": "msg-2",
                "timestamp": "2026-02-03T10:00:10.000Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 20,
                        "cache_creation_input_tokens": 10,
                    },
                },
            },
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for data in messages:
                f.write(json.dumps(data) + "\n")

        parsed = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(parsed)
        assert stats.avg_tokens_per_second == pytest.approx(15.0, abs=1e-6)
        assert stats.read_tokens_per_second == pytest.approx(10.0, abs=1e-6)
        assert stats.output_tokens_per_second == pytest.approx(5.0, abs=1e-6)
        assert stats.cache_read_tokens_per_second == pytest.approx(2.0, abs=1e-6)
        assert stats.cache_creation_tokens_per_second == pytest.approx(1.0, abs=1e-6)
        assert stats.cache_tokens_per_second == pytest.approx(3.0, abs=1e-6)

    def test_model_throughput_zero_model_time(self, temp_session_dir: Path) -> None:
        """Throughput rates should be None when model active time is zero."""
        file_path = temp_session_dir / "throughput-zero.jsonl"
        messages = [
            {
                "type": "assistant",
                "sessionId": "throughput-zero-session",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T10:00:00.000Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "standalone output"}],
                    "usage": {"input_tokens": 80, "output_tokens": 30},
                },
            }
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for data in messages:
                f.write(json.dumps(data) + "\n")

        parsed = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(parsed)
        assert stats.avg_tokens_per_second is None
        assert stats.read_tokens_per_second is None
        assert stats.output_tokens_per_second is None
        assert stats.cache_tokens_per_second is None

    def test_session_duration(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict[str, object]]
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
        bash_agent = next((s for s in subagent_sessions if s.agent_id == "bash-agent-1"), None)
        assert bash_agent is not None
        assert bash_agent.message_count == 1

    def test_subagent_statistics(
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
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
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict[str, object]]
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

    def test_calculate_statistics_reuses_precomputed_subagents(
        self, temp_session_dir: Path, sample_messages_with_subagents: list[dict[str, object]]
    ) -> None:
        """Test precomputed subagent sessions produce the same statistics."""
        file_path = temp_session_dir / "precomputed-subagents.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_subagents:
                f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        precomputed = extract_subagent_sessions(messages)

        baseline = calculate_session_statistics(messages)
        optimized = calculate_session_statistics(
            messages,
            precomputed_subagent_sessions=precomputed,
        )

        assert optimized.subagent_count == baseline.subagent_count
        assert optimized.subagent_sessions == baseline.subagent_sessions
        assert optimized.total_tool_calls == baseline.total_tool_calls
        assert optimized.character_breakdown == baseline.character_breakdown

    def test_parse_session_file_collects_compact_events_in_single_scan(
        self, temp_session_dir: Path, sample_messages_with_tools: list[dict[str, object]]
    ) -> None:
        """Test compact events are retained without a second parser pass."""
        file_path = temp_session_dir / "compact-session.jsonl"
        compact_event = {
            "type": "system",
            "subtype": "compact_boundary",
            "sessionId": "test-session-tools",
            "uuid": "compact-1",
            "timestamp": "2026-02-03T13:15:20.900Z",
            "compactMetadata": {
                "trigger": "token_limit",
                "preTokens": 4096,
            },
        }
        with open(file_path, "w", encoding="utf-8") as f:
            for data in sample_messages_with_tools[:4]:
                f.write(json.dumps(data) + "\n")
            f.write(json.dumps(compact_event) + "\n")
            for data in sample_messages_with_tools[4:]:
                f.write(json.dumps(data) + "\n")

        messages, compact_events = parse_jsonl_file_with_compact_events(file_path)
        session = parse_session_file(file_path)

        assert len(messages) == len(sample_messages_with_tools) + 1
        assert len(compact_events) == 1
        assert compact_events[0].trigger == "token_limit"
        assert session.statistics is not None
        assert session.statistics.compact_count == 1
        assert len(session.statistics.compact_events) == 1
        assert session.statistics.compact_events[0].pre_tokens == 4096


class TestConfigurableThresholds:
    """Tests for configurable inactivity threshold and model timeout detection."""

    @pytest.fixture
    def messages_with_large_gaps(self, temp_session_dir: Path) -> Path:
        """Create a session file with large time gaps to test thresholds."""
        messages = [
            {
                "type": "user",
                "sessionId": "test-thresholds",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T10:00:00.000Z",
                "message": {"role": "user", "content": "Start task"},
            },
            {
                "type": "assistant",
                "sessionId": "test-thresholds",
                "uuid": "msg-2",
                "timestamp": "2026-02-03T10:08:00.000Z",  # 8 min gap (model time)
                "message": {
                    "role": "assistant",
                    "content": "Working on it...",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            },
            {
                "type": "user",
                "sessionId": "test-thresholds",
                "uuid": "msg-3",
                "timestamp": "2026-02-03T10:20:00.000Z",  # 12 min gap (user time)
                "message": {"role": "user", "content": "Continue please"},
            },
            {
                "type": "assistant",
                "sessionId": "test-thresholds",
                "uuid": "msg-4",
                "timestamp": "2026-02-03T10:35:00.000Z",  # 15 min gap (model time)
                "message": {
                    "role": "assistant",
                    "content": "Done!",
                    "usage": {"input_tokens": 80, "output_tokens": 40},
                },
            },
            {
                "type": "user",
                "sessionId": "test-thresholds",
                "uuid": "msg-5",
                "timestamp": "2026-02-03T11:30:00.000Z",  # 55 min gap (inactive w/ default)
                "message": {"role": "user", "content": "Back now"},
            },
            {
                "type": "assistant",
                "sessionId": "test-thresholds",
                "uuid": "msg-6",
                "timestamp": "2026-02-03T11:32:00.000Z",  # 2 min gap (model time)
                "message": {
                    "role": "assistant",
                    "content": "Welcome back!",
                    "usage": {"input_tokens": 60, "output_tokens": 30},
                },
            },
        ]
        file_path = temp_session_dir / "test-thresholds.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")
        return file_path

    def test_default_inactivity_threshold(self, messages_with_large_gaps: Path) -> None:
        """Test that 55-min gap is classified as inactive with default 1800s threshold."""
        from agent_vis.parsers.session_parser import parse_jsonl_file

        messages = parse_jsonl_file(messages_with_large_gaps)
        stats = calculate_session_statistics(messages)

        assert stats.time_breakdown is not None
        tbd = stats.time_breakdown
        # 55 min gap should be inactive (> 30 min default)
        assert tbd.total_inactive_time_seconds > 0
        assert tbd.inactivity_threshold_seconds == 1800.0
        total_span = tbd.total_active_time_seconds + tbd.total_inactive_time_seconds
        assert total_span > 0
        assert tbd.active_time_ratio == pytest.approx(
            tbd.total_active_time_seconds / total_span, abs=1e-4
        )

    def test_custom_inactivity_threshold_lower(self, messages_with_large_gaps: Path) -> None:
        """Test with a 600s (10 min) threshold: 12-min and 15-min gaps become inactive too."""
        from agent_vis.parsers.session_parser import parse_jsonl_file

        messages = parse_jsonl_file(messages_with_large_gaps)
        stats_default = calculate_session_statistics(messages)
        stats_custom = calculate_session_statistics(messages, inactivity_threshold=600.0)

        assert stats_custom.time_breakdown is not None
        assert stats_default.time_breakdown is not None
        # With 600s threshold, more time should be classified as inactive
        assert (
            stats_custom.time_breakdown.total_inactive_time_seconds
            > stats_default.time_breakdown.total_inactive_time_seconds
        )
        assert stats_custom.time_breakdown.inactivity_threshold_seconds == 600.0

    def test_custom_inactivity_threshold_higher(self, messages_with_large_gaps: Path) -> None:
        """Test with a 7200s (2 hour) threshold: 55-min gap is no longer inactive."""
        from agent_vis.parsers.session_parser import parse_jsonl_file

        messages = parse_jsonl_file(messages_with_large_gaps)
        stats = calculate_session_statistics(messages, inactivity_threshold=7200.0)

        assert stats.time_breakdown is not None
        # 55 min gap (3300s) should NOT be inactive with 7200s threshold
        assert stats.time_breakdown.total_inactive_time_seconds == 0.0
        assert stats.time_breakdown.inactivity_threshold_seconds == 7200.0
        assert stats.time_breakdown.active_time_ratio == 1.0

    def test_model_timeout_detection_default(self, messages_with_large_gaps: Path) -> None:
        """Test model timeout detection with default 600s threshold."""
        from agent_vis.parsers.session_parser import parse_jsonl_file

        messages = parse_jsonl_file(messages_with_large_gaps)
        stats = calculate_session_statistics(messages)

        assert stats.time_breakdown is not None
        tbd = stats.time_breakdown
        # 8 min (480s) and 15 min (900s) are model gaps; only 15 min > 600s default
        # 2 min (120s) is also model but < 600s
        assert tbd.model_timeout_count == 1
        assert tbd.model_timeout_threshold_seconds == 600.0

    def test_model_timeout_detection_custom_threshold(self, messages_with_large_gaps: Path) -> None:
        """Test model timeout detection with a custom 300s (5 min) threshold."""
        from agent_vis.parsers.session_parser import parse_jsonl_file

        messages = parse_jsonl_file(messages_with_large_gaps)
        stats = calculate_session_statistics(messages, model_timeout_threshold=300.0)

        assert stats.time_breakdown is not None
        tbd = stats.time_breakdown
        # 8 min (480s) and 15 min (900s) are model gaps; both > 300s
        # 2 min (120s) is model but < 300s
        assert tbd.model_timeout_count == 2
        assert tbd.model_timeout_threshold_seconds == 300.0

    def test_no_model_timeout_with_high_threshold(self, messages_with_large_gaps: Path) -> None:
        """Test that high threshold produces zero timeouts."""
        from agent_vis.parsers.session_parser import parse_jsonl_file

        messages = parse_jsonl_file(messages_with_large_gaps)
        stats = calculate_session_statistics(messages, model_timeout_threshold=3600.0)

        assert stats.time_breakdown is not None
        assert stats.time_breakdown.model_timeout_count == 0

    def test_parse_session_file_with_thresholds(self, messages_with_large_gaps: Path) -> None:
        """Test that parse_session_file passes thresholds correctly."""
        session = parse_session_file(
            messages_with_large_gaps,
            inactivity_threshold=600.0,
            model_timeout_threshold=300.0,
        )

        assert session.statistics is not None
        assert session.statistics.time_breakdown is not None
        assert session.statistics.time_breakdown.inactivity_threshold_seconds == 600.0
        assert session.statistics.time_breakdown.model_timeout_threshold_seconds == 300.0
