"""Tests for Codex rollout parser and parser-registry integration."""

import json
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

    def test_parse_codex_jsonl_file_deduplicates_cross_channel_user_prompt(self) -> None:
        parity_fixture = (
            Path(__file__).parent
            / "fixtures"
            / "codex_parity"
            / "rollout-2026-03-01T09-00-00-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
        )
        messages = parse_codex_jsonl_file(parity_fixture)

        prompt = "Run parity check on parser and timeline."
        user_texts = [
            msg.message.content
            for msg in messages
            if msg.is_user_message
            and msg.message is not None
            and isinstance(msg.message.content, str)
        ]
        assert user_texts.count(prompt) == 1

    def test_parse_codex_jsonl_file_preserves_genuine_repeated_user_inputs(
        self, tmp_path: Path
    ) -> None:
        session_id = "44444444-4444-4444-4444-444444444444"
        rollout = tmp_path / f"rollout-2026-03-01T10-00-00-{session_id}.jsonl"
        prompt = "repeat this prompt twice"
        events = [
            {
                "timestamp": "2026-03-01T10:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": "/tmp/codex-project",
                    "cli_version": "0.107.0",
                    "source": "cli",
                },
            },
            {
                "timestamp": "2026-03-01T10:00:01.000Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": prompt},
            },
            {
                "timestamp": "2026-03-01T10:00:08.000Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": prompt},
            },
        ]
        with rollout.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

        messages = parse_codex_jsonl_file(rollout)
        user_texts = [
            msg.message.content
            for msg in messages
            if msg.is_user_message
            and msg.message is not None
            and isinstance(msg.message.content, str)
        ]
        assert user_texts.count(prompt) == 2
