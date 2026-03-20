"""Tests for Codex state_5.sqlite reader."""

import sqlite3
from pathlib import Path

from agent_vis.parsers.codex_state_db import CodexStateDB


def _create_state_db(db_path: Path, threads: list[dict[str, object]] | None = None) -> None:
    """Create a minimal Codex state_5.sqlite with a threads table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""\
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT,
            created_at INTEGER,
            updated_at INTEGER,
            title TEXT,
            cwd TEXT,
            tokens_used INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT,
            source TEXT,
            model_provider TEXT,
            first_user_message TEXT,
            archived INTEGER DEFAULT 0,
            sandbox_policy TEXT,
            approval_mode TEXT
        )
    """)
    if threads:
        for t in threads:
            conn.execute(
                """\
                INSERT INTO threads (
                    id, rollout_path, created_at, updated_at, title, cwd,
                    tokens_used, git_sha, git_branch, git_origin_url,
                    cli_version, source, model_provider, first_user_message,
                    archived, sandbox_policy, approval_mode
                ) VALUES (
                    :id, :rollout_path, :created_at, :updated_at, :title, :cwd,
                    :tokens_used, :git_sha, :git_branch, :git_origin_url,
                    :cli_version, :source, :model_provider, :first_user_message,
                    :archived, :sandbox_policy, :approval_mode
                )
                """,
                t,
            )
    conn.commit()
    conn.close()


_SAMPLE_THREAD = {
    "id": "abc-123",
    "rollout_path": "/tmp/sessions/rollout-abc.jsonl",
    "created_at": 1700000000,
    "updated_at": 1700001000,
    "title": "Fix the bug",
    "cwd": "/home/user/project",
    "tokens_used": 5000,
    "git_sha": "deadbeef",
    "git_branch": "main",
    "git_origin_url": "https://github.com/user/project.git",
    "cli_version": "0.108.0",
    "source": "cli",
    "model_provider": "anthropic",
    "first_user_message": "Fix the login issue",
    "archived": 0,
    "sandbox_policy": "permissive",
    "approval_mode": "auto",
}

_ARCHIVED_THREAD = {
    **_SAMPLE_THREAD,
    "id": "xyz-789",
    "rollout_path": "/tmp/sessions/archived/rollout-xyz.jsonl",
    "archived": 1,
    "title": "Old task",
}


class TestCodexStateDB:
    """Validate CodexStateDB reader behavior."""

    def test_missing_db_returns_empty(self, tmp_path: Path) -> None:
        db = CodexStateDB(tmp_path / "nonexistent.sqlite")
        assert db.list_threads() == []
        assert db.get_thread("any-id") is None
        assert db.find_rollout_path("any-id") is None

    def test_db_without_threads_table_returns_empty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state_5.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other_table (id TEXT)")
        conn.close()

        db = CodexStateDB(db_path)
        assert db.list_threads() == []

    def test_list_threads_excludes_archived_by_default(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [_SAMPLE_THREAD, _ARCHIVED_THREAD])

        db = CodexStateDB(db_path)
        threads = db.list_threads()
        assert len(threads) == 1
        assert threads[0].id == "abc-123"

    def test_list_threads_includes_archived(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [_SAMPLE_THREAD, _ARCHIVED_THREAD])

        db = CodexStateDB(db_path)
        threads = db.list_threads(include_archived=True)
        assert len(threads) == 2
        ids = {t.id for t in threads}
        assert ids == {"abc-123", "xyz-789"}

    def test_get_thread_found(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [_SAMPLE_THREAD])

        db = CodexStateDB(db_path)
        thread = db.get_thread("abc-123")
        assert thread is not None
        assert thread.id == "abc-123"
        assert thread.git_sha == "deadbeef"
        assert thread.git_branch == "main"
        assert thread.cli_version == "0.108.0"
        assert thread.source == "cli"
        assert thread.model_provider == "anthropic"
        assert thread.title == "Fix the bug"
        assert thread.first_user_message == "Fix the login issue"
        assert thread.archived is False

    def test_get_thread_not_found(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [_SAMPLE_THREAD])

        db = CodexStateDB(db_path)
        assert db.get_thread("nonexistent") is None

    def test_find_rollout_path_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [_SAMPLE_THREAD])

        db = CodexStateDB(db_path)
        # rollout file doesn't actually exist on disk
        assert db.find_rollout_path("abc-123") is None

    def test_find_rollout_path_returns_path_when_file_exists(self, tmp_path: Path) -> None:
        rollout_file = tmp_path / "rollout-abc.jsonl"
        rollout_file.write_text("{}")

        thread_data = {**_SAMPLE_THREAD, "rollout_path": str(rollout_file)}
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [thread_data])

        db = CodexStateDB(db_path)
        result = db.find_rollout_path("abc-123")
        assert result is not None
        assert result == rollout_file

    def test_thread_row_nullable_fields(self, tmp_path: Path) -> None:
        thread_data = {
            **_SAMPLE_THREAD,
            "git_sha": None,
            "git_branch": None,
            "git_origin_url": None,
        }
        db_path = tmp_path / "state_5.sqlite"
        _create_state_db(db_path, [thread_data])

        db = CodexStateDB(db_path)
        thread = db.get_thread("abc-123")
        assert thread is not None
        assert thread.git_sha is None
        assert thread.git_branch is None
        assert thread.git_origin_url is None
