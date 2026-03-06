from __future__ import annotations

import json
from pathlib import Path

from agent_vis.parsers.claude_code import (
    iter_claude_normalized_events,
    normalize_claude_event,
    parse_jsonl_file_with_compact_events,
)
from agent_vis.parsers.decoders import (
    available_json_line_decoders,
    decode_json_value,
    get_json_line_decoder,
)


def test_decoder_registry_supports_json_and_orjson() -> None:
    assert "json" in available_json_line_decoders()
    assert "orjson" in available_json_line_decoders()
    assert get_json_line_decoder().name == "orjson"
    assert get_json_line_decoder("json").read_mode == "text"
    assert get_json_line_decoder("orjson").read_mode == "binary"


def test_decode_json_value_respects_decoder_selection(monkeypatch) -> None:
    assert decode_json_value('{"kind":"default"}') == {"kind": "default"}

    monkeypatch.setenv("AGENT_VIS_JSON_DECODER", "json")
    assert get_json_line_decoder().name == "json"
    assert decode_json_value('{"kind":"env-json"}') == {"kind": "env-json"}


def test_normalize_claude_event_materializes_record_and_compact_ir() -> None:
    message_event = normalize_claude_event(
        {
            "type": "assistant",
            "sessionId": "session-1",
            "uuid": "msg-1",
            "timestamp": "2026-03-06T10:00:00.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        },
        line_number=1,
    )
    assert message_event is not None
    assert message_event.record is not None
    assert message_event.compact_event is None
    assert message_event.record.session_id == "session-1"
    assert message_event.to_message_record() is not None

    compact_boundary = normalize_claude_event(
        {
            "type": "system",
            "subtype": "compact_boundary",
            "timestamp": "2026-03-06T10:00:02.000Z",
            "compactMetadata": {"trigger": "token_limit", "preTokens": 2048},
        },
        line_number=2,
    )
    assert compact_boundary is not None
    assert compact_boundary.record is None
    assert compact_boundary.compact_event is not None
    assert compact_boundary.compact_event.trigger == "token_limit"
    assert compact_boundary.compact_event.to_compact_event().pre_tokens == 2048


def test_parse_pipeline_supports_decoder_selection(tmp_path: Path) -> None:
    file_path = tmp_path / "session.jsonl"
    rows = [
        {
            "type": "user",
            "sessionId": "session-2",
            "uuid": "u-1",
            "timestamp": "2026-03-06T10:00:00.000Z",
            "message": {"role": "user", "content": "hi"},
        },
        {
            "type": "system",
            "subtype": "compact_boundary",
            "timestamp": "2026-03-06T10:00:01.000Z",
            "compactMetadata": {"trigger": "manual", "preTokens": 512},
        },
        {
            "type": "assistant",
            "sessionId": "session-2",
            "uuid": "a-1",
            "timestamp": "2026-03-06T10:00:02.000Z",
            "message": {"role": "assistant", "content": "hello"},
        },
    ]
    with file_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    json_messages, json_compacts = parse_jsonl_file_with_compact_events(
        file_path,
        decoder_name="json",
    )
    orjson_messages, orjson_compacts = parse_jsonl_file_with_compact_events(
        file_path,
        decoder_name="orjson",
    )
    normalized_events = iter_claude_normalized_events(file_path, decoder_name="orjson")

    assert [msg.uuid for msg in json_messages] == [msg.uuid for msg in orjson_messages]
    assert len(json_compacts) == len(orjson_compacts) == 1
    assert len(normalized_events) == 3
    assert normalized_events[1].compact_event is not None
