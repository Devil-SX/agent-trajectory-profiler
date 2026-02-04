"""
Unit tests for session parser functions.

Tests cover JSONL parsing, session directory parsing, and error handling.
"""

import json
from pathlib import Path

import pytest

from claude_vis.parsers import (
    SessionParseError,
    parse_session_directory,
    parse_session_file,
)
from claude_vis.parsers.session_parser import (
    calculate_session_statistics,
    extract_session_metadata,
    find_session_files,
    parse_jsonl_file,
)


@pytest.fixture
def temp_session_dir(tmp_path: Path) -> Path:
    """Create a temporary session directory with test files."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    return session_dir


@pytest.fixture
def sample_session_data() -> list[dict[str, object]]:
    """Sample session data for testing."""
    return [
        {
            "type": "user",
            "sessionId": "test-session-123",
            "uuid": "msg-1",
            "timestamp": "2026-02-03T13:15:17.231Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "main",
            "isSidechain": False,
            "message": {
                "role": "user",
                "content": "Hello Claude",
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-123",
            "uuid": "msg-2",
            "timestamp": "2026-02-03T13:15:20.531Z",
            "userType": "external",
            "cwd": "/home/user/project",
            "version": "2.1.29",
            "gitBranch": "main",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help you?",
                "model": "claude-opus-4-5-20251101",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                },
            },
        },
    ]


@pytest.fixture
def sample_session_file(temp_session_dir: Path, sample_session_data: list[dict[str, object]]) -> Path:
    """Create a sample JSONL session file."""
    session_file = temp_session_dir / "test-session-123.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for data in sample_session_data:
            f.write(json.dumps(data) + "\n")
    return session_file


class TestParseJsonlFile:
    """Tests for parse_jsonl_file function."""

    def test_parse_valid_jsonl(self, sample_session_file: Path) -> None:
        """Test parsing a valid JSONL file."""
        messages = parse_jsonl_file(sample_session_file)
        assert len(messages) == 2
        assert messages[0].uuid == "msg-1"
        assert messages[1].uuid == "msg-2"

    def test_parse_empty_file(self, temp_session_dir: Path) -> None:
        """Test parsing an empty JSONL file."""
        empty_file = temp_session_dir / "empty.jsonl"
        empty_file.touch()
        messages = parse_jsonl_file(empty_file)
        assert len(messages) == 0

    def test_parse_file_with_blank_lines(
        self, temp_session_dir: Path, sample_session_data: list[dict[str, object]]
    ) -> None:
        """Test parsing JSONL with blank lines."""
        file_path = temp_session_dir / "with-blanks.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(sample_session_data[0]) + "\n")
            f.write("\n")  # Blank line
            f.write(json.dumps(sample_session_data[1]) + "\n")
        messages = parse_jsonl_file(file_path)
        assert len(messages) == 2

    def test_parse_invalid_json(self, temp_session_dir: Path) -> None:
        """Test parsing file with invalid JSON."""
        invalid_file = temp_session_dir / "invalid.jsonl"
        with open(invalid_file, "w", encoding="utf-8") as f:
            f.write("not valid json\n")
        with pytest.raises(SessionParseError) as exc_info:
            parse_jsonl_file(invalid_file)
        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_nonexistent_file(self, temp_session_dir: Path) -> None:
        """Test parsing nonexistent file."""
        nonexistent = temp_session_dir / "nonexistent.jsonl"
        with pytest.raises(SessionParseError) as exc_info:
            parse_jsonl_file(nonexistent)
        assert "not found" in str(exc_info.value)

    def test_parse_with_validation_errors(self, temp_session_dir: Path) -> None:
        """Test parsing with validation errors (should skip invalid records)."""
        file_path = temp_session_dir / "partial-valid.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            # Valid record
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "test",
                        "uuid": "msg-1",
                        "timestamp": "2026-02-03T13:15:17.231Z",
                    }
                )
                + "\n"
            )
            # Invalid record (missing required fields)
            f.write(json.dumps({"invalid": "data"}) + "\n")
        messages = parse_jsonl_file(file_path)
        # Should have parsed the valid message and skipped the invalid one
        assert len(messages) == 1


class TestExtractSessionMetadata:
    """Tests for extract_session_metadata function."""

    def test_extract_metadata(self, sample_session_file: Path) -> None:
        """Test extracting metadata from messages."""
        messages = parse_jsonl_file(sample_session_file)
        metadata = extract_session_metadata(messages, "test-session-123", sample_session_file)
        assert metadata.session_id == "test-session-123"
        assert metadata.project_path == "/home/user/project"
        assert metadata.git_branch == "main"
        assert metadata.version == "2.1.29"
        assert metadata.total_messages == 2
        assert metadata.total_tokens == 150  # 100 + 50

    def test_extract_metadata_empty_messages(self, temp_session_dir: Path) -> None:
        """Test extracting metadata from empty message list."""
        with pytest.raises(SessionParseError) as exc_info:
            extract_session_metadata([], "test", temp_session_dir / "test.jsonl")
        assert "empty message list" in str(exc_info.value)


class TestCalculateSessionStatistics:
    """Tests for calculate_session_statistics function."""

    def test_calculate_basic_statistics(self, sample_session_file: Path) -> None:
        """Test calculating basic statistics."""
        messages = parse_jsonl_file(sample_session_file)
        stats = calculate_session_statistics(messages)
        assert stats.message_count == 2
        assert stats.user_message_count == 1
        assert stats.assistant_message_count == 1
        assert stats.total_tokens == 150
        assert stats.total_input_tokens == 100
        assert stats.total_output_tokens == 50

    def test_calculate_with_tool_calls(self, temp_session_dir: Path) -> None:
        """Test statistics calculation with tool calls."""
        data = {
            "type": "assistant",
            "sessionId": "test",
            "uuid": "msg-1",
            "timestamp": "2026-02-03T13:15:17.231Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read the file."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"file_path": "/test.py"},
                    },
                ],
                "usage": {"input_tokens": 50, "output_tokens": 25},
            },
        }
        file_path = temp_session_dir / "with-tools.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

        messages = parse_jsonl_file(file_path)
        stats = calculate_session_statistics(messages)
        assert stats.total_tool_calls == 1

    def test_calculate_empty_messages(self) -> None:
        """Test calculating statistics for empty message list."""
        stats = calculate_session_statistics([])
        assert stats.message_count == 0
        assert stats.total_tokens == 0
        assert stats.average_tokens_per_message == 0.0


class TestFindSessionFiles:
    """Tests for find_session_files function."""

    def test_find_session_files(self, sample_session_file: Path, temp_session_dir: Path) -> None:
        """Test finding session files in directory."""
        # Create another session file
        another_file = temp_session_dir / "another-session.jsonl"
        another_file.touch()

        files = find_session_files(temp_session_dir)
        assert len(files) == 2
        assert all(f.suffix == ".jsonl" for f in files)

    def test_find_no_session_files(self, temp_session_dir: Path) -> None:
        """Test finding files in empty directory."""
        files = find_session_files(temp_session_dir)
        assert len(files) == 0

    def test_find_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test finding files in nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(SessionParseError) as exc_info:
            find_session_files(nonexistent)
        assert "does not exist" in str(exc_info.value)

    def test_find_not_directory(self, tmp_path: Path) -> None:
        """Test finding files when path is not a directory."""
        file_path = tmp_path / "notadir.txt"
        file_path.touch()
        with pytest.raises(SessionParseError) as exc_info:
            find_session_files(file_path)
        assert "not a directory" in str(exc_info.value)


class TestParseSessionFile:
    """Tests for parse_session_file function."""

    def test_parse_session_file(self, sample_session_file: Path) -> None:
        """Test parsing a complete session file."""
        session = parse_session_file(sample_session_file)
        assert session.metadata.session_id == "test-session-123"
        assert len(session.messages) == 2
        assert session.statistics is not None
        assert session.statistics.message_count == 2

    def test_parse_empty_session_file(self, temp_session_dir: Path) -> None:
        """Test parsing empty session file."""
        empty_file = temp_session_dir / "empty.jsonl"
        empty_file.touch()
        with pytest.raises(SessionParseError) as exc_info:
            parse_session_file(empty_file)
        assert "No valid messages" in str(exc_info.value)


class TestParseSessionDirectory:
    """Tests for parse_session_directory function."""

    def test_parse_directory(self, sample_session_file: Path, temp_session_dir: Path) -> None:
        """Test parsing a directory with session files."""
        parsed_data = parse_session_directory(temp_session_dir)
        assert parsed_data.session_count == 1
        assert parsed_data.total_messages == 2
        assert parsed_data.total_tokens == 150
        assert parsed_data.source_path == str(temp_session_dir)

    def test_parse_directory_multiple_sessions(
        self, temp_session_dir: Path, sample_session_data: list[dict[str, object]]
    ) -> None:
        """Test parsing directory with multiple sessions."""
        # Create multiple session files
        for i in range(3):
            file_path = temp_session_dir / f"session-{i}.jsonl"
            with open(file_path, "w", encoding="utf-8") as f:
                for data in sample_session_data:
                    # Modify session ID for each file
                    modified_data = data.copy()
                    modified_data["sessionId"] = f"session-{i}"
                    f.write(json.dumps(modified_data) + "\n")

        parsed_data = parse_session_directory(temp_session_dir)
        assert parsed_data.session_count == 3
        assert parsed_data.total_messages == 6  # 2 messages * 3 sessions

    def test_parse_empty_directory(self, temp_session_dir: Path) -> None:
        """Test parsing empty directory."""
        with pytest.raises(SessionParseError) as exc_info:
            parse_session_directory(temp_session_dir)
        assert "No session files found" in str(exc_info.value)

    def test_parse_directory_with_some_corrupt_files(
        self, temp_session_dir: Path, sample_session_data: list[dict[str, object]]
    ) -> None:
        """Test parsing directory with some corrupt files."""
        # Create valid file
        valid_file = temp_session_dir / "valid.jsonl"
        with open(valid_file, "w", encoding="utf-8") as f:
            for data in sample_session_data:
                f.write(json.dumps(data) + "\n")

        # Create corrupt file
        corrupt_file = temp_session_dir / "corrupt.jsonl"
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("invalid json\n")

        # Should parse valid file and skip corrupt one
        parsed_data = parse_session_directory(temp_session_dir)
        assert parsed_data.session_count == 1

    def test_parse_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test parsing nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(SessionParseError) as exc_info:
            parse_session_directory(nonexistent)
        assert "does not exist" in str(exc_info.value)
