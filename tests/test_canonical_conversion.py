"""Tests for canonical trajectory conversion layer and adapter contract."""

import json
from pathlib import Path

from agent_vis.models import MessageRecord
from agent_vis.parsers.canonical import (
    CanonicalEvent,
    TrajectoryEventAdapter,
    canonical_to_messages,
    get_adapter,
    list_adapters,
    parse_jsonl_to_canonical,
    register_adapter,
)
from agent_vis.parsers.claude_code import parse_jsonl_file


class TestCanonicalAdapterRegistry:
    """Tests for canonical adapter registration and lookup."""

    def test_builtin_claude_adapter_is_registered(self) -> None:
        assert "claude_code" in list_adapters()
        adapter = get_adapter("claude_code")
        assert adapter.ecosystem_name == "claude_code"

    def test_registry_supports_extension_without_core_changes(self) -> None:
        class DummyAdapter(TrajectoryEventAdapter):
            ecosystem_name = "dummy_ecosystem"

            def to_canonical_event(
                self, raw_event: dict[str, object], *, source_path: Path, line_number: int
            ) -> None:
                return None

            def canonical_to_message(self, event: CanonicalEvent) -> MessageRecord | None:
                return None

        register_adapter(DummyAdapter)
        adapter = get_adapter("dummy_ecosystem")
        assert isinstance(adapter, DummyAdapter)


class TestCanonicalConversionContract:
    """Tests for source JSONL -> canonical event -> MessageRecord contract."""

    def test_parse_jsonl_to_canonical_preserves_source_metadata(
        self, sample_session_file: Path
    ) -> None:
        adapter = get_adapter("claude_code")
        canonical_session = parse_jsonl_to_canonical(sample_session_file, adapter)

        assert canonical_session.ecosystem == "claude_code"
        assert canonical_session.source_path == str(sample_session_file)
        assert len(canonical_session.events) == 4
        assert canonical_session.events[0].line_number == 1
        assert canonical_session.events[0].actor == "user"

    def test_canonical_conversion_matches_current_claude_parser_output(
        self, sample_session_file: Path
    ) -> None:
        adapter = get_adapter("claude_code")
        canonical_session = parse_jsonl_to_canonical(sample_session_file, adapter)
        converted_messages = canonical_to_messages(canonical_session, adapter)
        parser_messages = parse_jsonl_file(sample_session_file)

        assert [m.uuid for m in converted_messages] == [m.uuid for m in parser_messages]
        assert [m.type for m in converted_messages] == [m.type for m in parser_messages]

    def test_invalid_message_records_are_skipped_after_canonical_conversion(
        self, temp_session_dir: Path
    ) -> None:
        file_path = temp_session_dir / "partial-valid.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "test",
                        "uuid": "msg-1",
                        "timestamp": "2026-02-03T13:15:17.231Z",
                    }
                )
                + "\n"
            )
            f.write(json.dumps({"invalid": "data"}) + "\n")

        adapter = get_adapter("claude_code")
        canonical_session = parse_jsonl_to_canonical(file_path, adapter)
        messages = canonical_to_messages(canonical_session, adapter)

        assert len(canonical_session.events) == 2
        assert len(messages) == 1
        assert messages[0].uuid == "msg-1"
