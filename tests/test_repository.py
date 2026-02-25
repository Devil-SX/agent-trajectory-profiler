"""
Tests for SessionRepository CRUD operations.
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from claude_vis.db.connection import get_connection
from claude_vis.db.repository import SessionRepository
from claude_vis.models import SessionStatistics, ToolCallStatistics


@pytest.fixture
def db_conn(tmp_path):
    """Create an in-memory-like temp DB."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def repo(db_conn):
    return SessionRepository(db_conn)


class TestTrackedFiles:
    def test_upsert_and_get(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file(
            "/tmp/session.jsonl", 1024, 1700000000.0, "claude_code", "parsed"
        )
        assert file_id > 0

        row = repo.get_tracked_file("/tmp/session.jsonl")
        assert row is not None
        assert row["file_size"] == 1024
        assert row["file_mtime"] == 1700000000.0
        assert row["parse_status"] == "parsed"

    def test_upsert_updates_existing(self, repo: SessionRepository) -> None:
        repo.upsert_tracked_file("/tmp/session.jsonl", 1024, 1700000000.0)
        repo.upsert_tracked_file("/tmp/session.jsonl", 2048, 1700000001.0, parse_status="parsed")

        row = repo.get_tracked_file("/tmp/session.jsonl")
        assert row is not None
        assert row["file_size"] == 2048
        assert row["file_mtime"] == 1700000001.0
        assert row["parse_status"] == "parsed"

    def test_get_nonexistent(self, repo: SessionRepository) -> None:
        assert repo.get_tracked_file("/nonexistent") is None

    def test_mark_file_status(self, repo: SessionRepository) -> None:
        repo.upsert_tracked_file("/tmp/s.jsonl", 100, 1.0)
        repo.mark_file_status("/tmp/s.jsonl", "error")
        row = repo.get_tracked_file("/tmp/s.jsonl")
        assert row["parse_status"] == "error"


class TestSessions:
    def test_upsert_and_get_session(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/s.jsonl", 100, 1.0, parse_status="parsed")
        repo.upsert_session(
            session_id="sess-1",
            file_id=file_id,
            ecosystem="claude_code",
            project_path="/home/user/project",
            git_branch="main",
            created_at="2026-02-03T13:15:17.231Z",
            updated_at="2026-02-03T13:25:17.231Z",
            total_messages=42,
            total_tokens=10000,
            duration_seconds=600.0,
            total_tool_calls=15,
            bottleneck="Model",
            automation_ratio=7.5,
        )

        row = repo.get_session("sess-1")
        assert row is not None
        assert row["session_id"] == "sess-1"
        assert row["total_messages"] == 42
        assert row["bottleneck"] == "Model"
        assert row["automation_ratio"] == 7.5

    def test_list_sessions_sorted(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/s.jsonl", 100, 1.0, parse_status="parsed")
        for i in range(5):
            repo.upsert_session(
                session_id=f"sess-{i}",
                file_id=file_id,
                ecosystem="claude_code",
                project_path="/proj",
                git_branch=None,
                created_at=f"2026-02-0{i + 1}T00:00:00Z",
                updated_at=None,
                total_messages=i * 10,
                total_tokens=i * 1000,
                duration_seconds=float(i * 100),
                total_tool_calls=i,
                bottleneck=None,
                automation_ratio=None,
            )

        rows = repo.list_sessions(sort_by="created_at", sort_order="DESC", limit=3)
        assert len(rows) == 3
        assert rows[0]["session_id"] == "sess-4"
        assert rows[2]["session_id"] == "sess-2"

    def test_count_sessions(self, repo: SessionRepository) -> None:
        assert repo.count_sessions() == 0
        file_id = repo.upsert_tracked_file("/tmp/s.jsonl", 100, 1.0)
        repo.upsert_session(
            "s1", file_id, "claude_code", "/p", None,
            None, None, 1, 1, None, 0, None, None,
        )
        assert repo.count_sessions() == 1

    def test_delete_session(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/s.jsonl", 100, 1.0)
        repo.upsert_session(
            "s1", file_id, "claude_code", "/p", None,
            None, None, 1, 1, None, 0, None, None,
        )
        stats = SessionStatistics(
            message_count=1, user_message_count=0, assistant_message_count=1,
            system_message_count=0, total_tokens=100,
            total_input_tokens=60, total_output_tokens=40,
        )
        repo.upsert_statistics("s1", stats)
        assert repo.count_sessions() == 1
        assert repo.get_statistics("s1") is not None

        repo.delete_session("s1")
        assert repo.count_sessions() == 0
        assert repo.get_statistics("s1") is None


class TestSessionStatistics:
    def test_upsert_and_get_statistics(self, repo: SessionRepository) -> None:
        stats = SessionStatistics(
            message_count=100,
            user_message_count=50,
            assistant_message_count=48,
            system_message_count=2,
            total_tokens=50000,
            total_input_tokens=30000,
            total_output_tokens=20000,
            cache_read_tokens=5000,
            cache_creation_tokens=1000,
            tool_calls=[
                ToolCallStatistics(
                    tool_name="Read", count=20, total_tokens=10000,
                    success_count=18, error_count=2,
                ),
            ],
            total_tool_calls=20,
        )
        repo.upsert_statistics("sess-stats-1", stats)

        loaded = repo.get_statistics("sess-stats-1")
        assert loaded is not None
        assert loaded.message_count == 100
        assert loaded.total_tokens == 50000
        assert len(loaded.tool_calls) == 1
        assert loaded.tool_calls[0].tool_name == "Read"
        assert loaded.tool_calls[0].count == 20

    def test_get_nonexistent_statistics(self, repo: SessionRepository) -> None:
        assert repo.get_statistics("nonexistent") is None

    def test_statistics_round_trip(self, repo: SessionRepository) -> None:
        """Test that statistics survive JSON serialization round-trip."""
        stats = SessionStatistics(
            message_count=5,
            user_message_count=2,
            assistant_message_count=3,
            system_message_count=0,
            total_tokens=500,
            total_input_tokens=300,
            total_output_tokens=200,
            session_duration_seconds=60.0,
        )
        repo.upsert_statistics("rt-test", stats)
        loaded = repo.get_statistics("rt-test")
        assert loaded is not None
        assert loaded.session_duration_seconds == 60.0
        assert loaded.average_tokens_per_message == 100.0


class TestGetFilePath:
    def test_get_file_path_for_session(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/my_session.jsonl", 100, 1.0, parse_status="parsed")
        repo.upsert_session(
            "s1", file_id, "claude_code", "/p", None,
            None, None, 1, 1, None, 0, None, None,
        )
        path = repo.get_file_path_for_session("s1")
        assert path is not None
        assert str(path) == "/tmp/my_session.jsonl"

    def test_get_file_path_nonexistent(self, repo: SessionRepository) -> None:
        assert repo.get_file_path_for_session("nope") is None
