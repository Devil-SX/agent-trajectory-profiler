"""
Integration tests for statistics calculation validation.

Tests cover comprehensive validation of statistics calculations,
accuracy checks, and edge cases for various session types.
"""

from pathlib import Path

import pytest

from claude_vis.parsers import parse_session_file


class TestStatisticsCalculationAccuracy:
    """Tests for accuracy of statistics calculations."""

    def test_message_count_accuracy(self, sample_session_file: Path) -> None:
        """Test that message counts are accurate."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        # Total messages should equal actual message count
        assert stats.message_count == len(session.messages)

        # Message type counts should add up
        user_count = sum(1 for m in session.messages if m.is_user_message)
        assistant_count = sum(1 for m in session.messages if m.is_assistant_message)

        assert stats.user_message_count == user_count
        assert stats.assistant_message_count == assistant_count

    def test_token_calculation_accuracy(self, sample_session_file: Path) -> None:
        """Test that token calculations are accurate."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        # Manually calculate expected tokens
        total_input = 0
        total_output = 0
        cache_read = 0
        cache_creation = 0

        for message in session.messages:
            if message.message and message.message.usage:
                usage = message.message.usage
                total_input += usage.input_tokens
                total_output += usage.output_tokens
                cache_read += usage.cache_read_input_tokens or 0
                cache_creation += usage.cache_creation_input_tokens or 0

        assert stats.total_input_tokens == total_input
        assert stats.total_output_tokens == total_output
        assert stats.total_tokens == total_input + total_output
        assert stats.cache_read_tokens == cache_read
        assert stats.cache_creation_tokens == cache_creation

    def test_tool_call_count_accuracy(self, sample_session_file: Path) -> None:
        """Test that tool call counts are accurate."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        # Count tool calls manually
        tool_call_count = 0
        for message in session.messages:
            if message.message and isinstance(message.message.content, list):
                for content_block in message.message.content:
                    if isinstance(content_block, dict) and content_block.get("type") == "tool_use":
                        tool_call_count += 1

        assert stats.total_tool_calls == tool_call_count

    def test_tool_success_failure_tracking(self, sample_session_file: Path) -> None:
        """Test that tool success/failure tracking is accurate."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        # For each tool in statistics, verify success/error counts
        for tool_stat in stats.tool_calls:
            assert tool_stat.count == tool_stat.success_count + tool_stat.error_count

    def test_session_duration_calculation(self, sample_session_file: Path) -> None:
        """Test that session duration is calculated correctly."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        if len(session.messages) > 1:
            first_time = session.messages[0].parsed_timestamp
            last_time = session.messages[-1].parsed_timestamp

            expected_duration = (last_time - first_time).total_seconds()
            assert stats.session_duration_seconds == expected_duration


class TestStatisticsWithSubagents:
    """Tests for statistics calculation with subagent sessions."""

    def test_subagent_count_accuracy(self, sample_session_file_with_subagents: Path) -> None:
        """Test that subagent counts are accurate."""
        session = parse_session_file(sample_session_file_with_subagents)
        stats = session.statistics

        assert stats is not None

        # Verify subagent count matches actual subagent sessions
        assert stats.subagent_count == len(session.subagent_sessions)

    def test_subagent_type_grouping(self, sample_session_file_with_subagents: Path) -> None:
        """Test that subagent sessions are grouped by type."""
        session = parse_session_file(sample_session_file_with_subagents)
        stats = session.statistics

        assert stats is not None

        # Count subagents by type from actual sessions
        type_counts: dict[str, int] = {}
        for subagent in session.subagent_sessions:
            agent_type = subagent.agent_type.value if subagent.agent_type else "other"
            type_counts[agent_type] = type_counts.get(agent_type, 0) + 1

        # Verify statistics match
        for agent_type, count in type_counts.items():
            assert stats.subagent_sessions.get(agent_type, 0) == count

    def test_subagent_token_calculation(self, sample_session_file_with_subagents: Path) -> None:
        """Test that subagent tokens are included in totals."""
        session = parse_session_file(sample_session_file_with_subagents)
        stats = session.statistics

        assert stats is not None

        # Calculate expected tokens including subagent messages
        total_tokens = 0
        for message in session.messages:
            if message.message and message.message.usage:
                total_tokens += message.message.usage.total_tokens

        assert stats.total_tokens == total_tokens


class TestStatisticsComputedProperties:
    """Tests for computed properties in statistics."""

    def test_average_tokens_per_message(self, sample_session_file: Path) -> None:
        """Test average tokens per message calculation."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        if stats.message_count > 0:
            expected_avg = stats.total_tokens / stats.message_count
            assert stats.average_tokens_per_message == expected_avg
        else:
            assert stats.average_tokens_per_message == 0.0

    def test_tool_usage_summary(self, sample_session_file: Path) -> None:
        """Test tool usage summary property."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        summary = stats.tool_usage_summary
        assert isinstance(summary, dict)

        # Verify summary matches tool_calls list
        for tool_stat in stats.tool_calls:
            assert summary[tool_stat.tool_name] == tool_stat.count

    def test_most_used_tools(self, sample_session_file: Path) -> None:
        """Test most used tools property."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        most_used = stats.most_used_tools
        assert isinstance(most_used, list)

        # Verify tools are sorted by count
        for i in range(len(most_used) - 1):
            assert most_used[i][1] >= most_used[i + 1][1]

    def test_tool_success_rate(self, sample_session_file: Path) -> None:
        """Test tool success rate calculation."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        success_rates = stats.tool_success_rate
        assert isinstance(success_rates, dict)

        # Verify success rates are between 0 and 1
        for tool_name, rate in success_rates.items():
            assert 0.0 <= rate <= 1.0

            # Find corresponding tool stat
            tool_stat = next((t for t in stats.tool_calls if t.tool_name == tool_name), None)
            if tool_stat and tool_stat.count > 0:
                expected_rate = tool_stat.success_count / tool_stat.count
                assert abs(rate - expected_rate) < 0.001

    def test_most_error_prone_tools(self, sample_session_file: Path) -> None:
        """Test most error prone tools identification."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        error_prone = stats.most_error_prone_tools
        assert isinstance(error_prone, list)

        # Verify sorted by error count descending
        for i in range(len(error_prone) - 1):
            assert error_prone[i][1] >= error_prone[i + 1][1]

        # Verify all have at least one error
        for _tool_name, error_count in error_prone:
            assert error_count > 0

    def test_get_top_tools(self, sample_session_file: Path) -> None:
        """Test get_top_tools method."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        if len(stats.tool_calls) > 0:
            # Get top 3 tools
            top_3 = stats.get_top_tools(3)
            assert len(top_3) <= 3
            assert len(top_3) <= len(stats.tool_calls)

            # Verify sorted by count
            for i in range(len(top_3) - 1):
                assert top_3[i].count >= top_3[i + 1].count


class TestStatisticsEdgeCases:
    """Tests for statistics calculation edge cases."""

    def test_empty_session_statistics(self, temp_session_dir: Path) -> None:
        """Test statistics for empty sessions."""
        # Note: We can't actually create a valid empty session
        # since parse_session_file requires at least one message
        # This test verifies the error handling
        from claude_vis.parsers import SessionParseError

        empty_file = temp_session_dir / "empty.jsonl"
        empty_file.touch()

        with pytest.raises(SessionParseError):
            parse_session_file(empty_file)

    def test_session_with_zero_tokens(
        self, temp_session_dir: Path, sample_user_message: dict[str, object]
    ) -> None:
        """Test statistics for session with messages but no token usage."""
        import json

        # Create session with messages that have no usage data
        messages = [sample_user_message.copy() for _ in range(3)]
        for i, msg in enumerate(messages):
            msg["uuid"] = f"msg-{i}"
            msg["sessionId"] = "zero-token-session"

        session_file = temp_session_dir / "zero-tokens.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        # Parse should still work
        session = parse_session_file(session_file)
        stats = session.statistics

        assert stats is not None
        assert stats.message_count == len(messages)

    def test_session_with_no_tool_calls(
        self, temp_session_dir: Path, sample_user_message: dict[str, object]
    ) -> None:
        """Test statistics for session without any tool calls."""
        import json

        messages = [
            {
                "type": "user",
                "sessionId": "no-tools",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T13:15:17.231Z",
                "message": {"role": "user", "content": "Hello"},
            },
            {
                "type": "assistant",
                "sessionId": "no-tools",
                "uuid": "msg-2",
                "timestamp": "2026-02-03T13:15:18.231Z",
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
        ]

        session_file = temp_session_dir / "no-tools.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        session = parse_session_file(session_file)
        stats = session.statistics

        assert stats is not None
        assert stats.total_tool_calls == 0
        assert len(stats.tool_calls) == 0

    def test_session_with_all_failed_tools(self, temp_session_dir: Path) -> None:
        """Test statistics when all tool calls fail."""
        import json

        messages = [
            {
                "type": "assistant",
                "sessionId": "all-failed",
                "uuid": "msg-1",
                "timestamp": "2026-02-03T13:15:17.231Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Read",
                            "input": {"file_path": "/nonexistent.txt"},
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
            {
                "type": "user",
                "sessionId": "all-failed",
                "uuid": "msg-2",
                "timestamp": "2026-02-03T13:15:18.231Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": "File not found",
                            "is_error": True,
                        }
                    ],
                },
            },
        ]

        session_file = temp_session_dir / "all-failed.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        session = parse_session_file(session_file)
        stats = session.statistics

        assert stats is not None
        assert stats.total_tool_calls == 1

        # Find the Read tool
        read_tool = next((t for t in stats.tool_calls if t.tool_name == "Read"), None)
        assert read_tool is not None
        assert read_tool.error_count == 1
        assert read_tool.success_count == 0

        # Success rate should be 0
        success_rates = stats.tool_success_rate
        assert success_rates["Read"] == 0.0


class TestStatisticsDataIntegrity:
    """Tests for data integrity in statistics."""

    def test_statistics_immutability(self, sample_session_file: Path) -> None:
        """Test that statistics don't change on repeated access."""
        session = parse_session_file(sample_session_file)
        stats1 = session.statistics
        stats2 = session.statistics

        assert stats1 is not None
        assert stats2 is not None

        # Should be the same object
        assert stats1 is stats2

        # Values should be identical
        assert stats1.message_count == stats2.message_count
        assert stats1.total_tokens == stats2.total_tokens

    def test_tool_statistics_consistency(self, sample_session_file: Path) -> None:
        """Test that tool statistics are internally consistent."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        for tool_stat in stats.tool_calls:
            # Count should equal success + error
            assert tool_stat.count == tool_stat.success_count + tool_stat.error_count

            # Counts should be non-negative
            assert tool_stat.count >= 0
            assert tool_stat.success_count >= 0
            assert tool_stat.error_count >= 0
            assert tool_stat.total_tokens >= 0

    def test_message_type_distribution(self, sample_session_file: Path) -> None:
        """Test that message type distribution is correct."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        # Sum of message types should equal total
        total_by_type = (
            stats.user_message_count + stats.assistant_message_count + stats.system_message_count
        )

        assert total_by_type == stats.message_count
