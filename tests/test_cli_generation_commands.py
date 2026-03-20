from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import agent_vis.cli.main as cli_main
from agent_vis.db.connection import get_connection
from agent_vis.session_embeddings import EmbeddingStageResult
from agent_vis.session_summaries import SummaryStageResult


def test_sync_rejects_legacy_summary_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["sync", "--summaries"])

    assert result.exit_code != 0
    assert "No such option: --summaries" in result.output


def test_summaries_generate_uses_selected_backend_and_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "summary-generate.db"
    conn = get_connection(db_path)
    conn.close()

    captured: dict[str, object] = {}

    def _fake_load_sessions(
        repo,
        *,
        ecosystem: str | None,
        session_ids: tuple[str, ...],
        inactivity_threshold: float | None,
        model_timeout: float | None,
        codex_state_db_path: Path | None,
    ):
        del repo, inactivity_threshold, model_timeout, codex_state_db_path
        captured["ecosystem"] = ecosystem
        captured["session_ids"] = session_ids
        return {"claude_code": [object(), object()], "codex": [object()]}, []

    def _fake_build_runner(config):
        captured["backend"] = config.backend
        captured["model"] = config.model
        return object()

    class _FakeSummaryCoordinator:
        def __init__(self, repo, runner, config) -> None:
            del repo
            captured["runner"] = runner
            captured["config_model_id"] = config.model_id
            self.calls: list[tuple[int, str]] = []

        def generate_for_sessions(self, sessions, *, ecosystem: str) -> SummaryStageResult:
            self.calls.append((len(sessions), ecosystem))
            captured.setdefault("calls", []).append((len(sessions), ecosystem))
            return SummaryStageResult(generated=len(sessions), skipped=0, failed=0)

    monkeypatch.setattr(cli_main, "_load_sessions_for_summary_generation", _fake_load_sessions)
    monkeypatch.setattr("agent_vis.session_summaries.build_summary_runner", _fake_build_runner)
    monkeypatch.setattr(
        "agent_vis.session_summaries.SessionSummaryCoordinator",
        _FakeSummaryCoordinator,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "summaries",
            "generate",
            "--db-path",
            str(db_path),
            "--backend",
            "claude",
            "-m",
            "sonnet",
            "--session-id",
            "sess-a",
        ],
    )

    assert result.exit_code == 0
    assert captured["backend"] == "claude"
    assert captured["model"] == "sonnet"
    assert captured["session_ids"] == ("sess-a",)
    assert captured["config_model_id"] == "claude:sonnet"
    assert captured["calls"] == [(2, "claude_code"), (1, "codex")]
    assert "Summary generation complete: 3 generated, 0 skipped, 0 failed" in result.output


def test_embeddings_generate_forwards_model_and_session_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "embedding-generate.db"
    conn = get_connection(db_path)
    conn.close()

    captured: dict[str, object] = {}

    class _FakeEmbeddingCoordinator:
        def __init__(self, repo, client, config) -> None:
            del repo, client
            captured["model"] = config.model
            captured["workers"] = config.max_workers
            captured["timeout"] = config.timeout_seconds
            captured["retries"] = config.max_retries

        def generate_for_completed_summaries(self, *, session_ids=None) -> EmbeddingStageResult:
            captured["session_ids"] = session_ids
            return EmbeddingStageResult(generated=2, skipped=1, failed=0)

    monkeypatch.setattr(
        "agent_vis.session_embeddings.SessionEmbeddingCoordinator",
        _FakeEmbeddingCoordinator,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "embeddings",
            "generate",
            "--db-path",
            str(db_path),
            "-m",
            "openai/text-embedding-3-small",
            "--session-id",
            "sess-a",
            "--session-id",
            "sess-b",
            "--workers",
            "5",
            "--timeout",
            "12",
            "--max-retries",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["workers"] == 5
    assert captured["timeout"] == 12.0
    assert captured["retries"] == 4
    assert captured["session_ids"] == ["sess-a", "sess-b"]
    assert "Embedding generation complete: 2 generated, 1 skipped, 0 failed" in result.output


def test_materialize_status_prints_chain_json(monkeypatch) -> None:
    payload = {
        "chain": [
            {"stage": "session", "depends_on": []},
            {"stage": "summary", "depends_on": ["session"]},
            {"stage": "section_summary", "depends_on": ["session"]},
            {"stage": "embedding", "depends_on": ["summary"]},
        ],
        "stages": {
            "session": {"sync_ready": True, "up_to_date": False},
            "summary": {"sync_ready": True, "up_to_date": True},
            "section_summary": {"sync_ready": True, "up_to_date": False},
            "embedding": {"sync_ready": True, "up_to_date": False},
        },
    }
    monkeypatch.setattr(cli_main, "_collect_materialization_status", lambda **_: payload)

    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["materialize", "status"])

    assert result.exit_code == 0
    assert '"stage": "summary"' in result.output
    assert '"up_to_date": false' in result.output.lower()


def test_materialize_sync_summary_dispatches_to_summary_stage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run_summary_stage(**kwargs):
        captured.update(kwargs)
        return {"generated": 4, "skipped": 1, "failed": 0}, ["missing-source.jsonl: not found"]

    monkeypatch.setattr(cli_main, "_run_summary_stage", _fake_run_summary_stage)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "materialize",
            "sync",
            "--stage",
            "summary",
            "--ecosystem",
            "codex",
            "--backend",
            "claude",
            "-m",
            "sonnet",
            "--workers",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert captured["ecosystem"] == "codex"
    assert captured["backend"] == "claude"
    assert captured["model"] == "sonnet"
    assert captured["workers"] == 3
    assert "Summary generation complete: 4 generated, 1 skipped, 0 failed" in result.output
    assert "Source parse errors: 1" in result.output


def test_materialize_sync_embedding_dispatches_to_embedding_stage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run_embedding_stage(**kwargs):
        captured.update(kwargs)
        return EmbeddingStageResult(generated=5, skipped=2, failed=1)

    monkeypatch.setattr(cli_main, "_run_embedding_stage", _fake_run_embedding_stage)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "materialize",
            "sync",
            "--stage",
            "embedding",
            "-m",
            "openai/text-embedding-3-small",
            "--session-id",
            "sess-a",
        ],
    )

    assert result.exit_code == 0
    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["session_ids"] == ("sess-a",)
    assert "Embedding generation complete: 5 generated, 2 skipped, 1 failed" in result.output


def test_materialize_sync_section_summary_dispatches_to_section_summary_stage(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_section_summary_stage(**kwargs):
        captured.update(kwargs)
        return (
            {"generated": 3, "skipped": 1, "failed": 0, "sections": 8},
            ["broken-session.jsonl: parse error"],
        )

    monkeypatch.setattr(
        cli_main,
        "_run_section_summary_stage",
        _fake_run_section_summary_stage,
    )

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "materialize",
            "sync",
            "--stage",
            "section-summary",
            "--ecosystem",
            "claude_code",
            "--backend",
            "codex",
            "-m",
            "gpt-5.4",
            "--session-id",
            "sess-a",
            "--workers",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert captured["ecosystem"] == "claude_code"
    assert captured["backend"] == "codex"
    assert captured["model"] == "gpt-5.4"
    assert captured["session_ids"] == ("sess-a",)
    assert captured["workers"] == 2
    assert (
        "Section summary generation complete: 3 generated, 1 skipped, 0 failed across 8 sections"
        in result.output
    )
    assert "Source parse errors: 1" in result.output


def test_analyze_uses_claude_without_session_persistence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}", encoding="utf-8")
    output_path = tmp_path / "report.md"

    monkeypatch.setattr(
        cli_main,
        "parse_session_file",
        lambda _path: SimpleNamespace(
            metadata=SimpleNamespace(session_id="sess-analyze"),
            statistics=object(),
        ),
    )
    monkeypatch.setattr(cli_main, "_format_session_stats", lambda *_args: "stats")
    monkeypatch.setattr(
        "agent_vis.prompts.analyze.build_analyze_prompt",
        lambda **_: ("prompt", "system"),
    )
    monkeypatch.setattr("agent_vis.cli.main.shutil.which", lambda _name: "/usr/bin/claude")

    captured: dict[str, object] = {}

    def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = list(args[0])
        captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(args[0], 0, stdout="# report\n", stderr="")

    monkeypatch.setattr("agent_vis.cli.main.subprocess.run", _fake_run)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "analyze",
            "--file",
            str(session_file),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert output_path.read_text(encoding="utf-8") == "# report"
    assert captured["timeout"] == 600
    assert "--dangerously-skip-permissions" in captured["command"]
    assert "--no-session-persistence" in captured["command"]
