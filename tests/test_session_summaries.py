from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.db.sync import SyncEngine
from agent_vis.models import Session
from agent_vis.parsers.claude_code import ClaudeCodeParser
from agent_vis.prompts.session_summary import (
    SESSION_SUMMARY_PROMPT_VERSION,
    build_session_summary_prompt,
)
from agent_vis.session_summaries import (
    CodexSessionSummaryRunner,
    SessionSummaryCoordinator,
    SessionSummaryGenerationError,
    SessionSynopsis,
    SummaryGeneration,
    SummaryGenerationConfig,
    build_session_synopsis,
    compute_synopsis_hash,
    normalize_summary_text,
)


@pytest.fixture
def summary_db(tmp_path: Path):
    conn = get_connection(tmp_path / "summary.db")
    yield conn
    conn.close()


@pytest.fixture
def summary_repo(summary_db) -> SessionRepository:
    return SessionRepository(summary_db)


@pytest.fixture
def parser() -> ClaudeCodeParser:
    return ClaudeCodeParser()


@pytest.fixture
def summary_session_dir(tmp_path: Path) -> Path:
    root = tmp_path / "sessions"
    root.mkdir()

    def _write_session(path: Path, session_id: str, user_text: str, assistant_text: str) -> None:
        rows = [
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": f"{session_id}-u1",
                "timestamp": "2026-03-01T10:00:00.000Z",
                "cwd": "/tmp/project",
                "version": "1.0.0",
                "message": {"role": "user", "content": user_text},
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": f"{session_id}-a1",
                "timestamp": "2026-03-01T10:00:05.000Z",
                "cwd": "/tmp/project",
                "version": "1.0.0",
                "message": {
                    "role": "assistant",
                    "content": assistant_text,
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                },
            },
        ]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    _write_session(
        root / "sess-a.jsonl",
        "sess-a",
        "Investigate failing CI job and collect the likely root cause.",
        "Found a flaky path assertion in the smoke suite and suggested tightening the selector.",
    )
    _write_session(
        root / "sess-b.jsonl",
        "sess-b",
        "Profile sync performance and identify the slowest parser stage.",
        "Measured parser hotspots and narrowed the main cost to JSON parsing on large files.",
    )
    return root


def _persist_session(repo: SessionRepository, session: Session, file_path: Path) -> None:
    file_id = repo.upsert_tracked_file(
        str(file_path.resolve()),
        file_path.stat().st_size,
        file_path.stat().st_mtime,
        ecosystem="claude_code",
        parse_status="parsed",
    )
    stats = session.statistics
    automation_ratio = None
    if stats and stats.time_breakdown and stats.time_breakdown.user_interaction_count > 0:
        automation_ratio = round(
            stats.total_tool_calls / stats.time_breakdown.user_interaction_count, 2
        )
    repo.upsert_session(
        session_id=session.metadata.session_id,
        file_id=file_id,
        ecosystem="claude_code",
        physical_session_id=session.metadata.physical_session_id,
        logical_session_id=session.metadata.logical_session_id,
        parent_session_id=session.metadata.parent_session_id,
        root_session_id=session.metadata.root_session_id,
        project_path=session.metadata.project_path,
        git_branch=session.metadata.git_branch,
        created_at=session.metadata.created_at.isoformat() if session.metadata.created_at else None,
        updated_at=session.metadata.updated_at.isoformat() if session.metadata.updated_at else None,
        total_messages=session.metadata.total_messages,
        total_tokens=session.metadata.total_tokens,
        duration_seconds=stats.session_duration_seconds if stats else None,
        total_tool_calls=stats.total_tool_calls if stats else 0,
        bottleneck=None,
        automation_ratio=automation_ratio,
        version=session.metadata.version,
    )
    if stats is not None:
        repo.upsert_statistics(session.metadata.session_id, stats)


def test_build_session_synopsis_extracts_provider_agnostic_fields(
    parser: ClaudeCodeParser,
    summary_session_dir: Path,
) -> None:
    session = parser.parse_session(summary_session_dir / "sess-a.jsonl")

    synopsis = build_session_synopsis(session, ecosystem="claude_code")

    assert synopsis.session_id == "sess-a"
    assert synopsis.ecosystem == "claude_code"
    assert synopsis.total_messages == 2
    assert synopsis.total_tokens == 30
    assert "Investigate failing CI job" in (synopsis.user_goal or "")
    assert "flaky path assertion" in (synopsis.final_outcome or "")


def test_session_summary_prompt_and_normalization_enforce_budget() -> None:
    synopsis = SessionSynopsis(
        session_id="sess-a",
        ecosystem="claude_code",
        project_path="/tmp/project",
        total_messages=2,
        total_tokens=30,
        total_tool_calls=0,
    )
    prompt = build_session_summary_prompt(synopsis.to_prompt_context(), max_chars=120)
    normalized = normalize_summary_text("word " * 200, max_chars=120)

    assert str(120) in prompt
    assert "plain text only" in prompt.lower()
    assert len(normalized) <= 123


def test_codex_runner_builds_expected_command_and_truncates_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = CodexSessionSummaryRunner(repo_root=tmp_path)
    config = SummaryGenerationConfig(enabled=True, model="gpt-5-codex", max_chars=80)
    synopsis = SessionSynopsis(
        session_id="sess-a",
        ecosystem="claude_code",
        project_path="/tmp/project",
        total_messages=2,
        total_tokens=30,
        total_tool_calls=0,
    )

    monkeypatch.setattr("agent_vis.session_summaries.shutil.which", lambda _: "/usr/bin/codex")

    seen_commands: list[list[str]] = []

    def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(args[0])
        seen_commands.append(command)
        output_index = command.index("--output-last-message") + 1
        output_path = Path(command[output_index])
        output_path.write_text("dense summary " * 20, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_vis.session_summaries.subprocess.run", _fake_run)

    generation = runner.generate(synopsis, config=config)

    assert seen_commands
    assert seen_commands[0][0:3] == ["codex", "exec", "--model"]
    assert "--ephemeral" in seen_commands[0]
    assert "--dangerously-bypass-approvals-and-sandbox" in seen_commands[0]
    assert generation.status == "completed"
    assert generation.summary_text is not None
    assert len(generation.summary_text) <= 83


def test_codex_runner_raises_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CodexSessionSummaryRunner()
    synopsis = SessionSynopsis(
        session_id="sess-a",
        ecosystem="claude_code",
        project_path="/tmp/project",
        total_messages=2,
        total_tokens=30,
        total_tool_calls=0,
    )
    config = SummaryGenerationConfig(enabled=True)
    monkeypatch.setattr("agent_vis.session_summaries.shutil.which", lambda _: None)

    with pytest.raises(SessionSummaryGenerationError, match="codex CLI not found"):
        runner.generate(synopsis, config=config)


def test_summary_coordinator_runs_in_parallel_and_persists_results(
    summary_repo: SessionRepository,
    parser: ClaudeCodeParser,
    summary_session_dir: Path,
) -> None:
    sessions: list[Session] = []
    for file_path in sorted(summary_session_dir.glob("*.jsonl")):
        session = parser.parse_session(file_path)
        _persist_session(summary_repo, session, file_path)
        sessions.append(session)

    class _SlowRunner:
        def __init__(self) -> None:
            self.current = 0
            self.max_seen = 0
            self.lock = threading.Lock()

        def generate(
            self, synopsis: SessionSynopsis, *, config: SummaryGenerationConfig
        ) -> SummaryGeneration:
            del config
            with self.lock:
                self.current += 1
                self.max_seen = max(self.max_seen, self.current)
            try:
                time.sleep(0.05)
                text = f"summary for {synopsis.session_id}"
                return SummaryGeneration(
                    session_id=synopsis.session_id,
                    synopsis_hash=compute_synopsis_hash(synopsis),
                    prompt_version=SESSION_SUMMARY_PROMPT_VERSION,
                    model_id="default",
                    status="completed",
                    summary_text=text,
                    summary_chars=len(text),
                    generated_at="2026-03-01T00:00:00+00:00",
                )
            finally:
                with self.lock:
                    self.current -= 1

    runner = _SlowRunner()
    coordinator = SessionSummaryCoordinator(
        summary_repo,
        runner,
        SummaryGenerationConfig(enabled=True, max_workers=2),
    )

    result = coordinator.generate_for_sessions(sessions, ecosystem="claude_code")

    assert result.generated == 2
    assert result.skipped == 0
    assert result.failed == 0
    assert runner.max_seen >= 2
    assert summary_repo.get_session_summary("sess-a")["generation_status"] == "completed"
    assert summary_repo.get_session_summary("sess-b")["summary_text"] == "summary for sess-b"


def test_summary_coordinator_skips_unchanged_synopsis(
    summary_repo: SessionRepository,
    parser: ClaudeCodeParser,
    summary_session_dir: Path,
) -> None:
    file_path = summary_session_dir / "sess-a.jsonl"
    session = parser.parse_session(file_path)
    _persist_session(summary_repo, session, file_path)
    synopsis = build_session_synopsis(session, ecosystem="claude_code")
    summary_repo.upsert_session_summary(
        session_id=session.metadata.session_id,
        synopsis_hash=compute_synopsis_hash(synopsis),
        prompt_version=SESSION_SUMMARY_PROMPT_VERSION,
        model_id="default",
        generation_status="completed",
        summary_text="cached summary",
        summary_chars=len("cached summary"),
        generated_at="2026-03-01T00:00:00+00:00",
        error_message=None,
    )

    class _FailIfCalledRunner:
        def generate(
            self, synopsis: SessionSynopsis, *, config: SummaryGenerationConfig
        ) -> SummaryGeneration:
            del synopsis, config
            raise AssertionError("runner should not be called for unchanged synopsis")

    coordinator = SessionSummaryCoordinator(
        summary_repo,
        _FailIfCalledRunner(),
        SummaryGenerationConfig(enabled=True),
    )

    result = coordinator.generate_for_sessions([session], ecosystem="claude_code")

    assert result.generated == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert summary_repo.get_session_summary("sess-a")["summary_text"] == "cached summary"


def test_sync_engine_summary_stage_success_skip_and_failure(
    tmp_path: Path,
    parser: ClaudeCodeParser,
    summary_session_dir: Path,
) -> None:
    conn = get_connection(tmp_path / "sync-summary.db")
    repo = SessionRepository(conn)

    class _SelectiveRunner:
        def __init__(self) -> None:
            self.fail = False

        def generate(
            self, synopsis: SessionSynopsis, *, config: SummaryGenerationConfig
        ) -> SummaryGeneration:
            del config
            if self.fail and synopsis.session_id == "sess-b":
                raise SessionSummaryGenerationError("forced summary failure")
            text = f"summary for {synopsis.session_id}"
            return SummaryGeneration(
                session_id=synopsis.session_id,
                synopsis_hash=compute_synopsis_hash(synopsis),
                prompt_version=SESSION_SUMMARY_PROMPT_VERSION,
                model_id="default",
                status="completed",
                summary_text=text,
                summary_chars=len(text),
                generated_at="2026-03-01T00:00:00+00:00",
            )

    runner = _SelectiveRunner()
    coordinator = SessionSummaryCoordinator(
        repo,
        runner,
        SummaryGenerationConfig(enabled=True, max_workers=2),
    )
    engine = SyncEngine(repo, parser, summary_coordinator=coordinator)

    first = engine.sync(summary_session_dir)
    second = engine.sync(summary_session_dir, force=True)
    runner.fail = True
    target_file = summary_session_dir / "sess-b.jsonl"
    rows = target_file.read_text(encoding="utf-8").splitlines()
    assistant_row = json.loads(rows[-1])
    assistant_row["message"][
        "content"
    ] = "Measured parser hotspots again and hit a forced summary failure path."
    rows[-1] = json.dumps(assistant_row)
    target_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    third = engine.sync(summary_session_dir)

    assert first.parsed == 2
    assert first.summaries_generated == 2
    assert second.summaries_skipped == 2
    assert third.parsed == 1
    assert third.summaries_failed == 1
    assert repo.get_session_summary("sess-b")["generation_status"] == "failed"
    assert repo.get_session("sess-b") is not None
    conn.close()
