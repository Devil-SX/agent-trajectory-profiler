"""Local privacy-preserving Codex session regression smoke test.

This test intentionally targets a real local session file that is ignored by git.
It is safe to commit because the test data itself is never tracked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_vis.parsers.codex import (
    parse_codex_jsonl_file_with_diagnostics,
    parse_codex_session_file,
)

PRIVATE_CASE_ENV = "AGENT_VIS_PRIVATE_CODEX_CASE"
DEFAULT_PRIVATE_CASE = Path(__file__).parent / "fixtures" / "codex_real_long_session.private.jsonl"
MIN_PRIVATE_CASE_LINES = 10_000


def _resolve_private_case() -> Path:
    override = os.getenv(PRIVATE_CASE_ENV)
    if override:
        return Path(override).expanduser()
    return DEFAULT_PRIVATE_CASE


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def test_parse_private_real_codex_session_smoke() -> None:
    case_path = _resolve_private_case()
    if not case_path.exists():
        pytest.skip(
            f"Private fixture missing. Set {PRIVATE_CASE_ENV} or create {DEFAULT_PRIVATE_CASE}."
        )

    line_count = _count_lines(case_path)
    assert line_count >= MIN_PRIVATE_CASE_LINES

    session = parse_codex_session_file(case_path)
    messages, diagnostics = parse_codex_jsonl_file_with_diagnostics(case_path)

    assert session.metadata.session_id
    assert session.metadata.project_path is not None
    assert "agent_trajectory_profiler" in session.metadata.project_path
    assert len(messages) >= 50
    assert diagnostics["raw_event_count"] >= len(messages)
    assert diagnostics["raw_event_count"] >= MIN_PRIVATE_CASE_LINES
    assert session.statistics.message_count == len(messages)
