from __future__ import annotations

from pathlib import Path

from agent_vis.perf.backend_runner import run_backend_performance


def test_run_backend_performance_writes_artifacts(tmp_path: Path) -> None:
    report, payload, json_path, markdown_path = run_backend_performance(
        mode="quick",
        output_dir=tmp_path,
        budgets_path=Path("tests/perf/budgets.json"),
        session_count=4,
        turns_per_session=4,
        api_iterations=2,
        stats_iterations=3,
    )

    assert report.mode == "quick"
    assert json_path.exists()
    assert markdown_path.exists()

    assert payload["runtime"]["character_classifier"] == "rust_native"

    metrics = payload["metrics"]
    assert metrics["sync_full_parse_seconds"] > 0
    assert metrics["sync_sessions_per_second"] > 0
    assert metrics["parser_statistics_p50_ms"] > 0
    assert metrics["api_overview_p50_ms"] >= 0
    assert metrics["api_timeseries_p50_ms"] >= 0
