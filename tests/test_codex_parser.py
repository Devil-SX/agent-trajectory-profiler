"""Tests for Codex rollout parser and parser-registry integration."""

from pathlib import Path

from agent_vis.parsers import get_parser
from agent_vis.parsers.codex import (
    CodexParser,
    find_codex_session_files,
    parse_codex_jsonl_file,
    parse_codex_session_file,
)


class TestCodexParser:
    """Validate Codex local rollout ingestion behavior."""

    def test_parse_codex_jsonl_file(self, sample_codex_rollout_file: Path) -> None:
        messages = parse_codex_jsonl_file(sample_codex_rollout_file)

        assert len(messages) >= 5
        assert messages[0].sessionId == "123e4567-e89b-12d3-a456-426614174000"
        assert any(msg.is_user_message for msg in messages)
        assert any(msg.is_assistant_message for msg in messages)

    def test_parse_codex_session_file_statistics(self, sample_codex_rollout_file: Path) -> None:
        session = parse_codex_session_file(sample_codex_rollout_file)

        assert session.metadata.session_id == "123e4567-e89b-12d3-a456-426614174000"
        assert session.metadata.project_path == "/tmp/codex-project"
        assert session.statistics.total_tool_calls >= 1

    def test_find_codex_session_files(
        self, codex_session_root: Path, sample_codex_rollout_file: Path
    ) -> None:
        _ = sample_codex_rollout_file
        found = find_codex_session_files(codex_session_root)
        assert len(found) == 1
        assert found[0].name.startswith("rollout-")

    def test_parser_registry_includes_codex(self) -> None:
        parser = get_parser("codex")
        assert isinstance(parser, CodexParser)

    def test_parse_codex_session_file_extracts_logical_lineage(
        self, codex_logical_hierarchy_root: Path
    ) -> None:
        root_id = "11111111-1111-1111-1111-111111111111"
        child_id = "22222222-2222-2222-2222-222222222222"
        child_file = (
            codex_logical_hierarchy_root
            / "2026"
            / "02"
            / "27"
            / f"rollout-2026-02-27T10-10-00-{child_id}.jsonl"
        )

        session = parse_codex_session_file(child_file)
        assert session.metadata.session_id == child_id
        assert session.metadata.physical_session_id == child_id
        assert session.metadata.parent_session_id == root_id
        assert session.metadata.root_session_id == root_id
        assert session.metadata.logical_session_id == root_id
