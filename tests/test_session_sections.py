from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_vis.db.connection import get_connection
from agent_vis.db.repository import SessionRepository
from agent_vis.models import Session
from agent_vis.parsers.claude_code import ClaudeCodeParser
from agent_vis.prompts.session_sectioning import build_session_sectioning_prompt
from agent_vis.session_sections import (
    SectionMaterializationConfig,
    SectionMaterializationGeneration,
    SectionSummaryGeneration,
    SectionSummaryPayload,
    SessionSection,
    SessionSectionMaterializationCoordinator,
    SessionSectionSummaryCoordinator,
    build_session_sectioning_synopsis,
    compute_sectioning_hash,
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


def test_sectioning_prompt_requires_exact_first_and_last_ordinals() -> None:
    prompt = build_session_sectioning_prompt(
        "\n".join(
            [
                "session_id: sess-sections",
                "first_user_ordinal: 1",
                "last_coverable_ordinal: 4",
                "messages:",
                "1. role=user uuid=u1 timestamp=t1 tools=(none) text=setup command",
                "2. role=assistant uuid=a1 timestamp=t2 tools=(none) text=ack",
            ]
        )
    )

    assert "The first section must start exactly at `first_user_ordinal`." in prompt
    assert "The last section must end exactly at `last_coverable_ordinal`." in prompt
    assert "Do not skip command-style, metadata-like, interrupted, or setup user" in prompt


def test_section_summary_coordinator_persists_structured_rows(
    parser: ClaudeCodeParser,
    section_session_dir: Path,
    tmp_path: Path,
) -> None:
    conn = get_connection(tmp_path / "sections.db")
    repo = SessionRepository(conn)
    session = parser.parse_session(section_session_dir / "sess-sections.jsonl")
    _persist_session(repo, session, section_session_dir / "sess-sections.jsonl")
    sections = derive_session_sections(session, ecosystem="claude_code")
    repo.replace_session_sections(
        session.metadata.session_id,
        [section.to_row() for section in sections],
    )
    repo.upsert_session_section_materialization(
        session_id=session.metadata.session_id,
        session_hash=compute_sectioning_hash(
            build_session_sectioning_synopsis(session, ecosystem="claude_code")
        ),
        prompt_version="session-sectioning-v1",
        model_id="codex:gpt-5.4",
        generation_status="completed",
        section_count=len(sections),
        generated_at="2026-03-18T00:00:00Z",
        error_message=None,
    )

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


def test_section_materialization_coordinator_persists_ai_sections(
    parser: ClaudeCodeParser,
    section_session_dir: Path,
    tmp_path: Path,
) -> None:
    conn = get_connection(tmp_path / "sections.db")
    repo = SessionRepository(conn)
    session = parser.parse_session(section_session_dir / "sess-sections.jsonl")
    _persist_session(repo, session, section_session_dir / "sess-sections.jsonl")

    heuristic_sections = derive_session_sections(session, ecosystem="claude_code")

    class _FakeBoundaryRunner:
        def generate(self, synopsis, *, session, ecosystem, config):
            assert synopsis.session_id == "sess-sections"
            return SectionMaterializationGeneration(
                session_id=session.metadata.session_id,
                session_hash=compute_sectioning_hash(synopsis),
                prompt_version="session-sectioning-v1",
                model_id=config.model_id,
                status="completed",
                sections=[
                    SessionSection(
                        **{
                            **heuristic_sections[0].__dict__,
                        }
                    ),
                    SessionSection(
                        **{
                            **heuristic_sections[1].__dict__,
                        }
                    ),
                ],
                generated_at="2026-03-18T00:00:00Z",
                error_message=None,
            )

    coordinator = SessionSectionMaterializationCoordinator(
        repo,
        _FakeBoundaryRunner(),
        SectionMaterializationConfig(enabled=True, model="gpt-5.4"),
    )

    result = coordinator.generate_for_sessions([session], ecosystem="claude_code")

    assert result.generated == 1
    assert result.sections == 2
    assert repo.count_session_sections() == 2
    persisted = repo.get_session_section_materialization("sess-sections")
    assert persisted is not None
    assert persisted["model_id"] == "codex:gpt-5.4"
    assert persisted["prompt_version"] == "session-sectioning-v1"
    conn.close()


def test_section_summary_coordinator_uses_persisted_sections_not_fallback(
    parser: ClaudeCodeParser,
    section_session_dir: Path,
    tmp_path: Path,
) -> None:
    conn = get_connection(tmp_path / "sections.db")
    repo = SessionRepository(conn)
    session = parser.parse_session(section_session_dir / "sess-sections.jsonl")
    _persist_session(repo, session, section_session_dir / "sess-sections.jsonl")

    heuristic_sections = derive_session_sections(session, ecosystem="claude_code")
    repo.replace_session_sections(
        session.metadata.session_id,
        [heuristic_sections[0].to_row()],
    )
    repo.upsert_session_section_materialization(
        session_id=session.metadata.session_id,
        session_hash=compute_sectioning_hash(
            build_session_sectioning_synopsis(session, ecosystem="claude_code")
        ),
        prompt_version="session-sectioning-v1",
        model_id="codex:gpt-5.4",
        generation_status="completed",
        section_count=1,
        generated_at="2026-03-18T00:00:00Z",
        error_message=None,
    )

    class _FakeRunner:
        def generate(self, synopsis, *, config):
            return SectionSummaryGeneration(
                section_id=synopsis.section_id,
                session_id=synopsis.session_id,
                section_hash="hash-" + synopsis.section_id,
                prompt_version="session-section-summary-v1",
                model_id=config.model_id,
                status="completed",
                summary_text=f"Summary for {synopsis.section_id}",
                summary_json=SectionSummaryPayload(
                    title=synopsis.title,
                    summary=f"Summary for {synopsis.section_id}",
                ).model_dump_json(),
                summary_chars=12,
                generated_at="2026-03-18T00:00:00Z",
                error_message=None,
            )

    coordinator = SessionSectionSummaryCoordinator(
        repo,
        _FakeRunner(),
        SummaryGenerationConfig(enabled=True, model="gpt-5.4"),
    )

    result = coordinator.generate_for_sessions([session], ecosystem="claude_code")

    assert result.sections == 1
    assert result.generated == 1
    assert repo.count_session_section_summaries(generation_status="completed") == 1
    conn.close()
