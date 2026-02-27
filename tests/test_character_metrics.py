"""Tests for trajectory file size and character metrics."""

from __future__ import annotations

import json
from pathlib import Path

from claude_vis.parsers.session_parser import (
    calculate_session_statistics,
    parse_jsonl_file,
    parse_session_file,
)


def test_character_breakdown_mixed_cjk_latin_digits(temp_session_dir: Path) -> None:
    """Character classifier should separate CJK, Latin, and digits with source attribution."""
    messages = [
        {
            "type": "user",
            "sessionId": "char-metrics-001",
            "uuid": "msg-1",
            "timestamp": "2026-02-10T10:00:00.000Z",
            "message": {"role": "user", "content": "你好abc"},
        },
        {
            "type": "assistant",
            "sessionId": "char-metrics-001",
            "uuid": "msg-2",
            "timestamp": "2026-02-10T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "测试xyz"},
                    {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "a.txt"}},
                ],
            },
        },
        {
            "type": "user",
            "sessionId": "char-metrics-001",
            "uuid": "msg-3",
            "timestamp": "2026-02-10T10:00:02.000Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "错误404",
                        "is_error": False,
                    }
                ],
            },
        },
    ]
    file_path = temp_session_dir / "char-metrics.jsonl"
    with file_path.open("w", encoding="utf-8") as handle:
        for message in messages:
            handle.write(json.dumps(message) + "\n")

    parsed_messages = parse_jsonl_file(file_path)
    stats = calculate_session_statistics(parsed_messages)

    chars = stats.character_breakdown
    assert chars.total_chars == 15
    assert chars.user_chars == 5
    assert chars.model_chars == 5
    assert chars.tool_chars == 5
    assert chars.cjk_chars == 6
    assert chars.latin_chars == 6
    assert chars.digit_chars == 3
    assert chars.whitespace_chars == 0
    assert chars.other_chars == 0


def test_parse_session_records_trajectory_file_size(temp_session_dir: Path) -> None:
    """Parsed session statistics should include trajectory file size in bytes."""
    file_path = temp_session_dir / "size-metrics.jsonl"
    payload = {
        "type": "user",
        "sessionId": "char-metrics-002",
        "uuid": "msg-1",
        "timestamp": "2026-02-10T10:10:00.000Z",
        "message": {"role": "user", "content": "hello"},
    }
    file_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    session = parse_session_file(file_path)
    assert session.statistics is not None
    assert session.statistics.trajectory_file_size_bytes == file_path.stat().st_size
