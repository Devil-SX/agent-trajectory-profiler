"""Tests for Codex rollout parser and parser-registry integration."""

import json
from pathlib import Path

from agent_vis.parsers import get_parser
from agent_vis.parsers.codex import (
    CODEX_EVENT_COVERAGE_MATRIX,
    CodexParser,
    find_codex_session_files,
    parse_codex_jsonl_file,
    parse_codex_jsonl_file_with_diagnostics,
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

    def test_parse_codex_session_file_extracts_nested_thread_spawn_lineage(
        self, codex_nested_lineage_root: Path
    ) -> None:
        root_id = "aaaaaaa1-1111-1111-1111-111111111111"
        child_id = "bbbbbbb2-2222-2222-2222-222222222222"
        child_file = (
            codex_nested_lineage_root
            / "2026"
            / "02"
            / "28"
            / f"rollout-2026-02-28T09-10-00-{child_id}.jsonl"
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

    def test_parse_codex_jsonl_file_with_diagnostics_reports_policy_drop_counts(self) -> None:
        parity_fixture = (
            Path(__file__).parent
            / "fixtures"
            / "codex_parity"
            / "rollout-2026-03-01T09-00-00-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
        )
        messages, diagnostics = parse_codex_jsonl_file_with_diagnostics(parity_fixture)

        assert len(messages) == 7
        assert diagnostics["raw_event_count"] == 10
        assert diagnostics["raw_event_kind_counts"]["session_meta"] == 1
        assert diagnostics["raw_event_kind_counts"]["event_msg"] == 3
        assert diagnostics["raw_event_kind_counts"]["response_item"] == 6
        assert diagnostics["unmapped_event_counts"] == {}
        assert diagnostics["policy_drop_counts"]["event_msg:turn_context"] == 1
        assert diagnostics["policy_drop_counts"]["response_item:reasoning"] == 1
        assert diagnostics["deduped_user_prompt_count"] == 1
        assert diagnostics["coverage_matrix"] == CODEX_EVENT_COVERAGE_MATRIX
        assert any(
            sample["event_type"] == "event_msg:turn_context"
            for sample in diagnostics["dropped_samples"]
        )

    def test_parse_codex_jsonl_file_with_diagnostics_tracks_unknown_top_level_events(
        self, tmp_path: Path
    ) -> None:
        session_id = "55555555-5555-5555-5555-555555555555"
        rollout = tmp_path / f"rollout-2026-03-01T11-00-00-{session_id}.jsonl"
        events = [
            {
                "timestamp": "2026-03-01T11:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": "/tmp/codex-project",
                    "cli_version": "0.107.0",
                    "source": "cli",
                },
            },
            {
                "timestamp": "2026-03-01T11:00:00.500Z",
                "type": "unknown_top_level_event",
                "payload": {"type": "turn_context", "turn_id": "turn-1"},
            },
            {
                "timestamp": "2026-03-01T11:00:01.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "ack"}],
                },
            },
        ]
        with rollout.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

        messages, diagnostics = parse_codex_jsonl_file_with_diagnostics(rollout)
        assert len(messages) == 2
        assert diagnostics["dropped_top_level_counts"]["unknown_top_level_event"] == 1
        assert any(
            sample["event_type"] == "unknown_top_level_event"
            for sample in diagnostics["dropped_samples"]
        )

    def test_parse_codex_jsonl_file_covers_all_observed_event_families(
        self, tmp_path: Path
    ) -> None:
        session_id = "66666666-6666-6666-6666-666666666666"
        rollout = tmp_path / f"rollout-2026-03-01T12-00-00-{session_id}.jsonl"
        events = [
            {
                "timestamp": "2026-03-01T12:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": "/tmp/codex-project",
                    "cli_version": "0.107.0",
                    "source": "cli",
                },
            },
            {
                "timestamp": "2026-03-01T12:00:00.050Z",
                "type": "turn_context",
                "payload": {"turn": 1},
            },
            {
                "timestamp": "2026-03-01T12:00:00.060Z",
                "type": "compacted",
                "payload": {"reason": "auto"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.100Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "hello"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.120Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 2, "output_tokens": 1}},
                },
            },
            {
                "timestamp": "2026-03-01T12:00:00.130Z",
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "thinking done"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.140Z",
                "type": "event_msg",
                "payload": {"type": "agent_reasoning", "message": "reasoning"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.150Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "task": "x"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.160Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "task": "x"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.170Z",
                "type": "event_msg",
                "payload": {"type": "turn_aborted", "turn_id": "1"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.180Z",
                "type": "event_msg",
                "payload": {"type": "context_compacted", "tokens": 1},
            },
            {
                "timestamp": "2026-03-01T12:00:00.190Z",
                "type": "event_msg",
                "payload": {"type": "item_completed", "item_id": "item-1"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.200Z",
                "type": "event_msg",
                "payload": {"type": "turn_context", "turn_id": "turn-1"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.210Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "ack"}],
                },
            },
            {
                "timestamp": "2026-03-01T12:00:00.220Z",
                "type": "response_item",
                "payload": {"type": "reasoning", "summary": [{"text": "plan"}]},
            },
            {
                "timestamp": "2026-03-01T12:00:00.230Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "Read",
                    "arguments": '{"path":"README.md"}',
                    "call_id": "call-1",
                },
            },
            {
                "timestamp": "2026-03-01T12:00:00.240Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-1", "output": "ok"},
            },
            {
                "timestamp": "2026-03-01T12:00:00.250Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "web",
                    "input": {"q": "x"},
                    "call_id": "c2",
                },
            },
            {
                "timestamp": "2026-03-01T12:00:00.260Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "c2",
                    "output": '{"output":"ok"}',
                },
            },
            {
                "timestamp": "2026-03-01T12:00:00.270Z",
                "type": "response_item",
                "payload": {"type": "web_search_call", "query": "codex parser"},
            },
        ]
        with rollout.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

        messages, diagnostics = parse_codex_jsonl_file_with_diagnostics(rollout)

        assert len(messages) == 9
        assert diagnostics["raw_event_count"] == len(events)
        assert diagnostics["dropped_top_level_counts"] == {}
        assert diagnostics["unmapped_event_counts"] == {}
        observed_keys = {
            "session_meta",
            "turn_context",
            "compacted",
            "event_msg:user_message",
            "event_msg:token_count",
            "event_msg:agent_message",
            "event_msg:agent_reasoning",
            "event_msg:task_started",
            "event_msg:task_complete",
            "event_msg:turn_aborted",
            "event_msg:context_compacted",
            "event_msg:item_completed",
            "event_msg:turn_context",
            "response_item:message",
            "response_item:reasoning",
            "response_item:function_call",
            "response_item:function_call_output",
            "response_item:custom_tool_call",
            "response_item:custom_tool_call_output",
            "response_item:web_search_call",
        }
        assert observed_keys.issubset(set(diagnostics["coverage_matrix"].keys()))
        assert diagnostics["policy_drop_counts"]["turn_context"] == 1
        assert diagnostics["policy_drop_counts"]["compacted"] == 1
        assert diagnostics["policy_drop_counts"]["response_item:web_search_call"] == 1
