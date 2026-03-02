"""
Tests for SyncEngine incremental parsing.
"""

import json
from pathlib import Path

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.db.sync import SyncEngine
from agent_vis.parsers.claude_code import ClaudeCodeParser


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test_sync.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def repo(db_conn):
    return SessionRepository(db_conn)


@pytest.fixture
def parser():
    return ClaudeCodeParser()


@pytest.fixture
def engine(repo, parser):
    return SyncEngine(repo, parser)


@pytest.fixture
def session_dir(tmp_path) -> Path:
    """Create a directory with two session JSONL files."""
    d = tmp_path / "sessions"
    d.mkdir()

    data_a = [
        {
            "type": "user",
            "sessionId": "sess-a",
            "uuid": "m1",
            "timestamp": "2026-02-03T13:15:17.231Z",
            "message": {"role": "user", "content": "Hello"},
        },
        {
            "type": "assistant",
            "sessionId": "sess-a",
            "uuid": "m2",
            "timestamp": "2026-02-03T13:15:18.231Z",
            "message": {
                "role": "assistant",
                "content": "Hi!",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        },
    ]
    with open(d / "sess-a.jsonl", "w") as f:
        for row in data_a:
            f.write(json.dumps(row) + "\n")

    data_b = [
        {
            "type": "user",
            "sessionId": "sess-b",
            "uuid": "m1",
            "timestamp": "2026-02-03T14:00:00.000Z",
            "message": {"role": "user", "content": "Test"},
        },
        {
            "type": "assistant",
            "sessionId": "sess-b",
            "uuid": "m2",
            "timestamp": "2026-02-03T14:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": "OK",
                "usage": {"input_tokens": 20, "output_tokens": 10},
            },
        },
    ]
    with open(d / "sess-b.jsonl", "w") as f:
        for row in data_b:
            f.write(json.dumps(row) + "\n")

    return d


class TestSyncEngineBasic:
    def test_initial_sync(
        self, engine: SyncEngine, session_dir: Path, repo: SessionRepository
    ) -> None:
        result = engine.sync(session_dir)
        assert result.parsed == 2
        assert result.skipped == 0
        assert len(result.errors) == 0
        assert result.total == 2
        assert repo.count_sessions() == 2

    def test_second_sync_skips(self, engine: SyncEngine, session_dir: Path) -> None:
        r1 = engine.sync(session_dir)
        assert r1.parsed == 2

        r2 = engine.sync(session_dir)
        assert r2.parsed == 0
        assert r2.skipped == 2

    def test_force_re_parses_all(self, engine: SyncEngine, session_dir: Path) -> None:
        engine.sync(session_dir)
        result = engine.sync(session_dir, force=True)
        assert result.parsed == 2
        assert result.skipped == 0

    def test_modified_file_detected(self, engine: SyncEngine, session_dir: Path) -> None:
        engine.sync(session_dir)

        # Modify one file
        file_a = session_dir / "sess-a.jsonl"
        with open(file_a, "a") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "sess-a",
                        "uuid": "m3",
                        "timestamp": "2026-02-03T13:16:00.000Z",
                        "message": {"role": "user", "content": "More"},
                    }
                )
                + "\n"
            )

        result = engine.sync(session_dir)
        assert result.parsed == 1  # Only sess-a re-parsed
        assert result.skipped == 1  # sess-b unchanged

    def test_corrupt_file_counted_as_error(self, engine: SyncEngine, session_dir: Path) -> None:
        corrupt = session_dir / "corrupt.jsonl"
        corrupt.write_text("not valid json\n")

        result = engine.sync(session_dir)
        # 2 good + 1 error
        assert result.parsed == 2
        assert len(result.errors) == 1

    def test_empty_directory(self, engine: SyncEngine, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = engine.sync(empty)
        assert result.parsed == 0
        assert result.skipped == 0

    def test_nonexistent_directory(self, engine: SyncEngine, tmp_path: Path) -> None:
        result = engine.sync(tmp_path / "nonexistent")
        assert result.parsed == 0
        assert len(result.errors) == 1


class TestSyncEngineDataIntegrity:
    def test_statistics_stored(
        self, engine: SyncEngine, session_dir: Path, repo: SessionRepository
    ) -> None:
        engine.sync(session_dir)

        stats = repo.get_statistics("sess-a")
        assert stats is not None
        assert stats.message_count == 2
        assert stats.total_tokens == 15

    def test_session_summary_fields(
        self, engine: SyncEngine, session_dir: Path, repo: SessionRepository
    ) -> None:
        engine.sync(session_dir)

        row = repo.get_session("sess-a")
        assert row is not None
        assert row["ecosystem"] == "claude_code"
        assert row["total_messages"] == 2
        assert row["total_tokens"] == 15
        assert row["parsed_at"] is not None

    def test_capability_warning_is_logged(
        self,
        engine: SyncEngine,
        session_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            "agent_vis.db.sync.get_capability_warnings",
            lambda *args, **kwargs: ["manifest drift warning"],
        )
        caplog.set_level("WARNING")

        engine.sync(session_dir)
        assert "Capability warning" in caplog.text
