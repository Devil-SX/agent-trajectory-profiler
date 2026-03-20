from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.models import Session
from agent_vis.parsers.claude_code import ClaudeCodeParser
from agent_vis.session_sections import (
    SectionSummaryGeneration,
    SectionSummaryPayload,
    SessionSectionSummaryCoordinator,
    derive_session_sections,
)
from agent_vis.session_summaries import SummaryGenerationConfig


@pytest.fixture
def parser() -> ClaudeCodeParser:
    return ClaudeCodeParser()


@pytest.fixture
def section_session_dir(tmp_path: Path) -> Path:
    root = tmp_path / "sections"
    root.mkdir()
    rows = [
        {
            "type": "user",
            "sessionId": "sess-sections",
            "uuid": "u1",
            "timestamp": "2026-03-01T10:00:00.000Z",
            "cwd": "/tmp/project",
            "version": "1.0.0",
            "message": {"role": "user", "content": "Investigate the flaky test failure."},
        },
        {
            "type": "assistant",
            "sessionId": "sess-sections",
            "uuid": "a1",
            "timestamp": "2026-03-01T10:00:05.000Z",
            "cwd": "/tmp/project",
            "version": "1.0.0",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll inspect the failing suite and diff."},
                    {
                        "type": "tool_use",
                        "id": "read-1",
                        "name": "Read",
                        "input": {"path": "tests"},
                    },
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10},
            },
        },
        {
            "type": "user",
            "sessionId": "sess-sections",
            "uuid": "u2",
            "timestamp": "2026-03-01T10:01:00.000Z",
            "cwd": "/tmp/project",
            "version": "1.0.0",
            "message": {"role": "user", "content": "Summarize the root cause and next fix."},
        },
        {
            "type": "assistant",
            "sessionId": "sess-sections",
            "uuid": "a2",
            "timestamp": "2026-03-01T10:01:08.000Z",
            "cwd": "/tmp/project",
            "version": "1.0.0",
            "message": {
                "role": "assistant",
                "content": "The selector is too broad. Narrow it and add a regression test.",
                "usage": {"input_tokens": 25, "output_tokens": 12},
            },
        },
    ]
    (root / "sess-sections.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
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
        automation_ratio=None,
        version=session.metadata.version,
    )
    if stats is not None:
        repo.upsert_statistics(session.metadata.session_id, stats)


def test_derive_session_sections_splits_on_user_boundaries(
    parser: ClaudeCodeParser,
    section_session_dir: Path,
) -> None:
    session = parser.parse_session(section_session_dir / "sess-sections.jsonl")

    sections = derive_session_sections(session, ecosystem="claude_code")

    assert [section.section_index for section in sections] == [1, 2]
    assert sections[0].user_message_count == 1
    assert sections[0].assistant_message_count == 1
    assert sections[0].tool_call_count == 1
    assert sections[1].total_tokens > 0
    assert "Investigate the flaky test failure" in sections[0].title


def test_section_summary_coordinator_persists_structured_rows(
    parser: ClaudeCodeParser,
    section_session_dir: Path,
    tmp_path: Path,
) -> None:
    conn = get_connection(tmp_path / "sections.db")
    repo = SessionRepository(conn)
    session = parser.parse_session(section_session_dir / "sess-sections.jsonl")
    _persist_session(repo, session, section_session_dir / "sess-sections.jsonl")

    class _FakeRunner:
        def generate(self, synopsis, *, config):
            payload = SectionSummaryPayload(
                title=f"Section {synopsis.section_index}",
                summary=f"Summary for {synopsis.section_id}",
                goal="Investigate the issue",
                actions=["Read failing files"],
                outcome="Root cause identified",
                tool_patterns=["Read"],
                risk_or_blocker=None,
                keywords=["flaky", "selector"],
            )
            return SectionSummaryGeneration(
                section_id=synopsis.section_id,
                session_id=synopsis.session_id,
                section_hash="hash-" + synopsis.section_id,
                prompt_version="session-section-summary-v1",
                model_id=config.model_id,
                status="completed",
                summary_text=payload.summary,
                summary_json=payload.model_dump_json(),
                summary_chars=len(payload.summary),
                generated_at="2026-03-18T00:00:00Z",
                error_message=None,
            )

    coordinator = SessionSectionSummaryCoordinator(
        repo,
        _FakeRunner(),
        SummaryGenerationConfig(enabled=True, model="gpt-5.4"),
    )

    result = coordinator.generate_for_sessions([session], ecosystem="claude_code")

    assert result.sections == 2
    assert result.generated == 2
    assert repo.count_session_sections() == 2
    assert repo.count_session_section_summaries(generation_status="completed") == 2
    persisted = repo.get_session_section_summary("sess-sections:section:1")
    assert persisted is not None
    assert persisted["model_id"] == "codex:gpt-5.4"
    conn.close()
