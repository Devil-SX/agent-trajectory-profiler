from __future__ import annotations

from pathlib import Path

import pytest

from agent_vis.perf.backend_runner import _create_dataset
from agent_vis.perf.sync_profiler import (
    PRIVATE_SYNC_ROOT_ENV,
    profile_session_file,
    profile_sync_directory,
    render_sync_profile_markdown,
    resolve_private_sync_root,
)


def test_resolve_private_sync_root_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "private-root"
    monkeypatch.setenv(PRIVATE_SYNC_ROOT_ENV, str(override))

    assert resolve_private_sync_root() == override


def test_profile_session_file_reports_expected_stages(tmp_path: Path) -> None:
    sessions_dir, _, _ = _create_dataset(tmp_path, session_count=1, turns_per_session=3)
    session_file = next(sessions_dir.glob("*.jsonl"))

    payload = profile_session_file(session_file)

    assert payload["line_count"] > 0
    assert payload["message_count"] > 0
    assert payload["total_ms"] > 0
    assert payload["stage_timings_ms"]["parse_jsonl_file_ms"] > 0
    assert payload["stage_timings_ms"]["calculate_session_statistics_ms"] > 0
    assert payload["stage_timings_ms"]["extract_compact_events_ms"] >= 0


def test_profile_sync_directory_writes_artifacts(tmp_path: Path) -> None:
    sessions_dir, _, _ = _create_dataset(tmp_path / "dataset", session_count=3, turns_per_session=4)
    output_dir = tmp_path / "out"

    payload, json_path, markdown_path = profile_sync_directory(
        sessions_dir,
        output_dir=output_dir,
        max_files=2,
        top_n=2,
    )

    assert json_path is not None and json_path.exists()
    assert markdown_path is not None and markdown_path.exists()
    assert payload["summary"]["discovered_files"] == 3
    assert payload["summary"]["selected_files"] == 2
    assert payload["summary"]["parsed_files"] == 2
    assert payload["summary"]["total_sync_ms"] > 0
    assert payload["stage_breakdown"]
    assert any(item["stage"] == "parse_jsonl_file_ms" for item in payload["stage_breakdown"])
    assert len(payload["slow_files"]) == 2

    markdown = render_sync_profile_markdown(payload, title="Test Sync Profile")
    assert "Test Sync Profile" in markdown
    assert "Stage Breakdown" in markdown
    assert "Slow Files" in markdown
