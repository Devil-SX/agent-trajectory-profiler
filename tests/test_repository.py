"""
Tests for SessionRepository CRUD operations.
"""

import json

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.models import SessionStatistics, ToolCallStatistics


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
            "s1",
            file_id,
            "claude_code",
            "/p",
            None,
            None,
            None,
            1,
            1,
            None,
            0,
            None,
            None,
        )
        assert repo.count_sessions() == 1

    def test_delete_session(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/s.jsonl", 100, 1.0)
        repo.upsert_session(
            "s1",
            file_id,
            "claude_code",
            "/p",
            None,
            None,
            None,
            1,
            1,
            None,
            0,
            None,
            None,
        )
        stats = SessionStatistics(
            message_count=1,
            user_message_count=0,
            assistant_message_count=1,
            system_message_count=0,
            total_tokens=100,
            total_input_tokens=60,
            total_output_tokens=40,
        )
        repo.upsert_statistics("s1", stats)
        assert repo.count_sessions() == 1
        assert repo.get_statistics("s1") is not None

        repo.delete_session("s1")
        assert repo.count_sessions() == 0
        assert repo.get_statistics("s1") is None

    def test_transaction_rolls_back_on_exception(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/tx.jsonl", 200, 2.0, parse_status="parsed")

        with pytest.raises(RuntimeError, match="forced rollback"):
            with repo.transaction():
                repo.upsert_session(
                    session_id="tx-session",
                    file_id=file_id,
                    ecosystem="claude_code",
                    project_path="/tmp/project",
                    git_branch="main",
                    created_at="2026-02-01T10:00:00Z",
                    updated_at="2026-02-01T10:05:00Z",
                    total_messages=10,
                    total_tokens=100,
                    duration_seconds=60.0,
                    total_tool_calls=2,
                    bottleneck="Model",
                    automation_ratio=1.0,
                )
                raise RuntimeError("forced rollback")

        assert repo.get_session("tx-session") is None


class TestSessionMaterializationQueries:
    def _seed_sessions(self, repo: SessionRepository) -> tuple[int, int]:
        file_a = repo.upsert_tracked_file(
            "/tmp/source-a.jsonl",
            100,
            1.0,
            ecosystem="claude_code",
            parse_status="parsed",
        )
        file_b = repo.upsert_tracked_file(
            "/tmp/source-b.jsonl",
            200,
            2.0,
            ecosystem="codex",
            parse_status="parsed",
        )
        repo.upsert_session(
            "sess-a",
            file_a,
            "claude_code",
            "/proj/a",
            None,
            None,
            None,
            1,
            10,
            None,
            0,
            None,
            None,
        )
        repo.upsert_session(
            "sess-b",
            file_b,
            "codex",
            "/proj/b",
            None,
            None,
            None,
            2,
            20,
            None,
            1,
            None,
            None,
        )
        return file_a, file_b

    def test_list_session_source_files_supports_ecosystem_and_session_filters(
        self, repo: SessionRepository
    ) -> None:
        self._seed_sessions(repo)

        all_rows = repo.list_session_source_files()
        assert [(row["session_id"], row["ecosystem"]) for row in all_rows] == [
            ("sess-a", "claude_code"),
            ("sess-b", "codex"),
        ]

        filtered_rows = repo.list_session_source_files(
            ecosystem="codex",
            session_ids=["sess-b"],
        )
        assert len(filtered_rows) == 1
        assert filtered_rows[0]["session_id"] == "sess-b"
        assert filtered_rows[0]["file_path"] == "/tmp/source-b.jsonl"

    def test_list_and_count_sessions_support_project_path_filter(
        self, repo: SessionRepository
    ) -> None:
        self._seed_sessions(repo)

        rows = repo.list_sessions(
            project_path="/proj/b",
            sort_by="session_id",
            sort_order="ASC",
            view_mode="physical",
        )

        assert [row["session_id"] for row in rows] == ["sess-b"]
        assert repo.count_sessions(project_path="/proj/b", view_mode="physical") == 1
        assert repo.count_sessions(project_path="/missing", view_mode="physical") == 0

    def test_count_session_summaries_filters_by_generation_status(
        self, repo: SessionRepository
    ) -> None:
        self._seed_sessions(repo)
        repo.upsert_session_summary(
            session_id="sess-a",
            synopsis_hash="hash-a",
            prompt_version="v1",
            model_id="gpt-5.4",
            generation_status="completed",
            summary_text="summary a",
            summary_chars=9,
            generated_at="2026-03-18T00:00:00Z",
            error_message=None,
        )
        repo.upsert_session_summary(
            session_id="sess-b",
            synopsis_hash="hash-b",
            prompt_version="v1",
            model_id="gpt-5.4",
            generation_status="failed",
            summary_text=None,
            summary_chars=None,
            generated_at="2026-03-18T00:01:00Z",
            error_message="boom",
        )

        assert repo.count_session_summaries() == 2
        assert repo.count_session_summaries(generation_status="completed") == 1
        assert repo.count_session_summaries(generation_status="failed") == 1

    def test_replace_and_list_session_sections_and_summaries(self, repo: SessionRepository) -> None:
        self._seed_sessions(repo)
        repo.replace_session_sections(
            "sess-a",
            [
                {
                    "section_id": "sess-a:section:1",
                    "section_index": 1,
                    "title": "Investigate issue",
                    "start_message_uuid": "u1",
                    "end_message_uuid": "a1",
                    "start_timestamp": "2026-03-01T10:00:00Z",
                    "end_timestamp": "2026-03-01T10:00:05Z",
                    "total_messages": 2,
                    "user_message_count": 1,
                    "assistant_message_count": 1,
                    "tool_call_count": 1,
                    "input_tokens": 10,
                    "output_tokens": 12,
                    "total_tokens": 22,
                    "char_count": 120,
                    "duration_seconds": 5.0,
                }
            ],
        )
        repo.upsert_session_section_summary(
            section_id="sess-a:section:1",
            session_id="sess-a",
            section_hash="section-hash-a",
            prompt_version="session-section-summary-v1",
            model_id="codex:gpt-5.4",
            generation_status="completed",
            summary_text="Investigated the issue and narrowed it to one failing assertion.",
            summary_json=json.dumps(
                {
                    "title": "Investigate issue",
                    "summary": "Investigated the issue.",
                    "goal": "Find root cause",
                    "actions": ["Ran tests"],
                    "outcome": "Found flaky assertion",
                    "tool_patterns": ["Read"],
                    "risk_or_blocker": None,
                    "keywords": ["test"],
                }
            ),
            summary_chars=26,
            generated_at="2026-03-18T00:00:00Z",
            error_message=None,
        )

        rows = repo.list_session_sections("sess-a")
        assert len(rows) == 1
        assert rows[0]["title"] == "Investigate issue"
        assert repo.get_session_section("sess-a", 1)["section_id"] == "sess-a:section:1"
        summaries = repo.list_session_section_summaries("sess-a")
        assert len(summaries) == 1
        assert summaries[0]["model_id"] == "codex:gpt-5.4"
        assert repo.count_session_sections() == 1
        assert repo.count_session_section_summaries(generation_status="completed") == 1

    def test_count_session_summary_embeddings_filters_by_status_and_model(
        self, repo: SessionRepository
    ) -> None:
        self._seed_sessions(repo)
        repo.upsert_session_summary_embedding(
            session_id="sess-a",
            summary_hash="sum-a",
            model_id="openai/text-embedding-3-small",
            provider_name="openrouter",
            generation_status="completed",
            embedding_dimension=3,
            vector_json="[0.1, 0.2, 0.3]",
            generated_at="2026-03-18T00:00:00Z",
            error_message=None,
        )
        repo.upsert_session_summary_embedding(
            session_id="sess-b",
            summary_hash="sum-b",
            model_id="other-model",
            provider_name="openrouter",
            generation_status="failed",
            embedding_dimension=None,
            vector_json=None,
            generated_at="2026-03-18T00:01:00Z",
            error_message="timeout",
        )

        assert repo.count_session_summary_embeddings() == 2
        assert (
            repo.count_session_summary_embeddings(
                generation_status="completed",
                model_id="openai/text-embedding-3-small",
            )
            == 1
        )
        assert repo.count_session_summary_embeddings(generation_status="failed") == 1
        assert repo.count_session_summary_embeddings(model_id="missing-model") == 0


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
                    tool_name="Read",
                    count=20,
                    total_tokens=10000,
                    success_count=18,
                    error_count=2,
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

    def test_list_statistics_for_sessions(self, repo: SessionRepository) -> None:
        first = SessionStatistics(
            message_count=2,
            user_message_count=1,
            assistant_message_count=1,
            system_message_count=0,
            total_tokens=20,
            total_input_tokens=12,
            total_output_tokens=8,
        )
        second = SessionStatistics(
            message_count=3,
            user_message_count=1,
            assistant_message_count=2,
            system_message_count=0,
            total_tokens=30,
            total_input_tokens=18,
            total_output_tokens=12,
        )
        repo.upsert_statistics("stats-a", first)
        repo.upsert_statistics("stats-b", second)

        stats_map = repo.list_statistics_for_sessions(["stats-a", "stats-b", "stats-missing"])
        assert set(stats_map.keys()) == {"stats-a", "stats-b"}
        assert '"message_count":2' in stats_map["stats-a"]
        assert '"message_count":3' in stats_map["stats-b"]


class TestGetFilePath:
    def test_get_file_path_for_session(self, repo: SessionRepository) -> None:
        file_id = repo.upsert_tracked_file("/tmp/my_session.jsonl", 100, 1.0, parse_status="parsed")
        repo.upsert_session(
            "s1",
            file_id,
            "claude_code",
            "/p",
            None,
            None,
            None,
            1,
            1,
            None,
            0,
            None,
            None,
        )
        path = repo.get_file_path_for_session("s1")
        assert path is not None
        assert str(path) == "/tmp/my_session.jsonl"

    def test_get_file_path_nonexistent(self, repo: SessionRepository) -> None:
        assert repo.get_file_path_for_session("nope") is None
