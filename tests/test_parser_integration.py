"""
Integration tests for session parser with sample files.

Tests cover end-to-end parsing workflows, including directory parsing,
session file handling, and integration with the statistics calculator.
"""

import json
from pathlib import Path

from claude_vis.parsers import (
    SessionParseError,
    parse_session_directory,
    parse_session_file,
)


class TestParserIntegrationWithSingleSession:
    """Integration tests for parsing single session files."""

    def test_parse_complete_session_file(self, sample_session_file: Path) -> None:
        """Test parsing a complete session file end-to-end."""
        session = parse_session_file(sample_session_file)

        # Verify session metadata
        assert session.metadata.session_id == "test-session-001"
        assert session.metadata.project_path == "/home/user/project"
        assert session.metadata.git_branch == "main"
        assert session.metadata.version == "2.1.29"
        assert session.metadata.total_messages > 0

        # Verify messages are parsed
        assert len(session.messages) > 0

        # Verify statistics are calculated
        assert session.statistics is not None
        assert session.statistics.message_count == len(session.messages)
        assert session.statistics.total_tokens > 0

    def test_parse_session_with_tool_calls(self, sample_session_file: Path) -> None:
        """Test that tool calls are properly extracted during parsing."""
        session = parse_session_file(sample_session_file)

        # Should have tool call statistics
        assert session.statistics is not None
        assert session.statistics.total_tool_calls > 0
        assert len(session.statistics.tool_calls) > 0

        # Verify tool call details
        tool_names = [tc.tool_name for tc in session.statistics.tool_calls]
        assert "Read" in tool_names

    def test_parse_session_with_subagents(self, sample_session_file_with_subagents: Path) -> None:
        """Test parsing session with subagent messages."""
        session = parse_session_file(sample_session_file_with_subagents)

        # Verify subagent sessions are extracted
        assert len(session.subagent_sessions) > 0

        # Verify subagent statistics
        assert session.statistics is not None
        assert session.statistics.subagent_count > 0

        # Verify subagent details
        subagent = session.subagent_sessions[0]
        assert subagent.agent_id is not None
        assert subagent.message_count > 0

    def test_parse_session_token_calculations(self, sample_session_file: Path) -> None:
        """Test that token calculations are accurate during parsing."""
        session = parse_session_file(sample_session_file)

        assert session.statistics is not None
        stats = session.statistics

        # Verify token totals
        assert stats.total_tokens == stats.total_input_tokens + stats.total_output_tokens
        assert stats.total_input_tokens > 0
        assert stats.total_output_tokens > 0

        # Verify cache tokens are tracked
        if stats.cache_read_tokens > 0 or stats.cache_creation_tokens > 0:
            assert stats.cache_read_tokens >= 0
            assert stats.cache_creation_tokens >= 0

    def test_parse_session_message_order(self, sample_session_file: Path) -> None:
        """Test that messages are parsed in correct chronological order."""
        session = parse_session_file(sample_session_file)

        # Verify messages are in order
        for i in range(len(session.messages) - 1):
            curr_time = session.messages[i].parsed_timestamp
            next_time = session.messages[i + 1].parsed_timestamp
            assert curr_time <= next_time


class TestParserIntegrationWithDirectory:
    """Integration tests for parsing session directories."""

    def test_parse_directory_with_multiple_sessions(self, multi_session_directory: Path) -> None:
        """Test parsing a directory containing multiple sessions."""
        parsed_data = parse_session_directory(multi_session_directory)

        # Should have multiple sessions
        assert parsed_data.session_count > 1
        assert len(parsed_data.sessions) > 1

        # Verify aggregate statistics
        assert parsed_data.total_messages > 0
        assert parsed_data.total_tokens > 0

        # Verify each session is complete
        for session in parsed_data.sessions:
            assert session.metadata.session_id is not None
            assert len(session.messages) > 0
            assert session.statistics is not None

    def test_parse_directory_session_isolation(self, multi_session_directory: Path) -> None:
        """Test that sessions are properly isolated during directory parsing."""
        parsed_data = parse_session_directory(multi_session_directory)

        # Get all session IDs
        session_ids = [s.metadata.session_id for s in parsed_data.sessions]

        # Verify all session IDs are unique
        assert len(session_ids) == len(set(session_ids))

        # Verify each session only contains its own messages
        for session in parsed_data.sessions:
            for message in session.messages:
                assert message.sessionId == session.metadata.session_id

    def test_parse_directory_aggregate_statistics(self, multi_session_directory: Path) -> None:
        """Test that directory-level statistics are accurate."""
        parsed_data = parse_session_directory(multi_session_directory)

        # Calculate expected totals
        expected_messages = sum(len(s.messages) for s in parsed_data.sessions)
        expected_tokens = sum(s.metadata.total_tokens for s in parsed_data.sessions)

        assert parsed_data.total_messages == expected_messages
        assert parsed_data.total_tokens == expected_tokens

    def test_parse_directory_with_corrupt_files(
        self, temp_session_dir: Path, sample_complete_session: list[dict[str, object]]
    ) -> None:
        """Test that directory parsing handles corrupt files gracefully."""
        # Create valid session file
        valid_file = temp_session_dir / "valid.jsonl"
        with open(valid_file, "w", encoding="utf-8") as f:
            for msg in sample_complete_session:
                f.write(json.dumps(msg) + "\n")

        # Create corrupt session file
        corrupt_file = temp_session_dir / "corrupt.jsonl"
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("this is not valid json\n")

        # Parse directory - should succeed with valid file only
        parsed_data = parse_session_directory(temp_session_dir)

        # Should have parsed the valid file
        assert parsed_data.session_count >= 1

    def test_parse_directory_empty_files(
        self, temp_session_dir: Path, sample_complete_session: list[dict[str, object]]
    ) -> None:
        """Test that directory parsing skips empty files."""
        # Create valid session file
        valid_file = temp_session_dir / "valid.jsonl"
        with open(valid_file, "w", encoding="utf-8") as f:
            for msg in sample_complete_session:
                f.write(json.dumps(msg) + "\n")

        # Create empty file
        empty_file = temp_session_dir / "empty.jsonl"
        empty_file.touch()

        # Parse directory
        parsed_data = parse_session_directory(temp_session_dir)

        # Should only have the valid session
        assert parsed_data.session_count == 1


class TestParserIntegrationWithEdgeCases:
    """Integration tests for edge cases in parsing."""

    def test_parse_session_with_blank_lines(
        self, temp_session_dir: Path, sample_complete_session: list[dict[str, object]]
    ) -> None:
        """Test parsing session file with blank lines."""
        session_file = temp_session_dir / "with-blanks.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for i, msg in enumerate(sample_complete_session):
                f.write(json.dumps(msg) + "\n")
                # Add blank line between messages
                if i < len(sample_complete_session) - 1:
                    f.write("\n")

        session = parse_session_file(session_file)
        assert len(session.messages) == len(sample_complete_session)

    def test_parse_session_with_missing_optional_fields(self, temp_session_dir: Path) -> None:
        """Test parsing messages with missing optional fields."""
        messages = [
            {
                "type": "user",
                "sessionId": "test-minimal",
                "uuid": "msg-001",
                "timestamp": "2026-02-03T13:15:17.231Z",
                "message": {"role": "user", "content": "Hello"},
            },
            {
                "type": "assistant",
                "sessionId": "test-minimal",
                "uuid": "msg-002",
                "timestamp": "2026-02-03T13:15:18.231Z",
                "message": {
                    "role": "assistant",
                    "content": "Hi",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
        ]

        session_file = temp_session_dir / "minimal.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        session = parse_session_file(session_file)
        assert len(session.messages) == 2
        assert session.statistics is not None

    def test_parse_large_session_file(
        self, temp_session_dir: Path, sample_user_message: dict[str, object]
    ) -> None:
        """Test parsing a large session file with many messages."""
        # Create a large session with 100 messages
        session_file = temp_session_dir / "large.jsonl"
        with open(session_file, "w", encoding="utf-8") as f:
            for i in range(100):
                msg = sample_user_message.copy()
                msg["uuid"] = f"msg-{i:03d}"
                msg["timestamp"] = f"2026-02-03T13:{i // 60:02d}:{i % 60:02d}.000Z"
                f.write(json.dumps(msg) + "\n")

        session = parse_session_file(session_file)
        assert len(session.messages) == 100
        assert session.statistics is not None
        assert session.statistics.message_count == 100


class TestParserIntegrationDataConsistency:
    """Integration tests for data consistency across parsing operations."""

    def test_reparse_session_consistency(self, sample_session_file: Path) -> None:
        """Test that reparsing the same file produces consistent results."""
        session1 = parse_session_file(sample_session_file)
        session2 = parse_session_file(sample_session_file)

        # Metadata should be identical
        assert session1.metadata.session_id == session2.metadata.session_id
        assert session1.metadata.total_messages == session2.metadata.total_messages
        assert session1.metadata.total_tokens == session2.metadata.total_tokens

        # Statistics should be identical
        assert session1.statistics is not None
        assert session2.statistics is not None
        assert session1.statistics.message_count == session2.statistics.message_count
        assert session1.statistics.total_tokens == session2.statistics.total_tokens

    def test_parse_directory_vs_individual_files(self, multi_session_directory: Path) -> None:
        """Test that directory parsing matches individual file parsing."""
        # Parse entire directory
        dir_parsed = parse_session_directory(multi_session_directory)

        # Parse each file individually
        individual_sessions = []
        for file in multi_session_directory.glob("*.jsonl"):
            try:
                session = parse_session_file(file)
                individual_sessions.append(session)
            except SessionParseError:
                # Skip corrupt files
                pass

        # Number of sessions should match
        assert len(dir_parsed.sessions) == len(individual_sessions)

        # Total messages and tokens should match
        total_messages_dir = sum(len(s.messages) for s in dir_parsed.sessions)
        total_messages_ind = sum(len(s.messages) for s in individual_sessions)
        assert total_messages_dir == total_messages_ind

    def test_statistics_calculation_consistency(self, sample_session_file: Path) -> None:
        """Test that statistics are consistently calculated."""
        session = parse_session_file(sample_session_file)
        stats = session.statistics

        assert stats is not None

        # Verify message counts add up
        assert (
            stats.user_message_count + stats.assistant_message_count + stats.system_message_count
            == stats.message_count
        )

        # Verify token counts are consistent
        assert stats.total_tokens == stats.total_input_tokens + stats.total_output_tokens

        # Verify tool call counts
        total_tool_calls_from_list = sum(tc.count for tc in stats.tool_calls)
        assert total_tool_calls_from_list == stats.total_tool_calls
