"""Regression tests for shared parser normalization and typed IR conversion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_vis.models import MessageRecord
from agent_vis.parsers.claude_code import parse_jsonl_file as parse_claude_jsonl_file
from agent_vis.parsers.codex import parse_codex_jsonl_file


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _first_tool_result_content(messages: list[MessageRecord]) -> str | list[dict[str, Any]]:
    for message in messages:
        if message.message is None or not isinstance(message.message.content, list):
            continue
        for block in message.message.content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return block.get("content")
    raise AssertionError("expected at least one tool_result block")


def _render_text_content(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def test_shared_timestamp_fallback_is_consistent_across_ecosystems(tmp_path: Path) -> None:
    codex_file = tmp_path / "rollout-2026-03-04T10-00-00-123e4567-e89b-12d3-a456-426614174001.jsonl"
    claude_file = tmp_path / "claude-session.jsonl"

    _write_jsonl(
        codex_file,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "123e4567-e89b-12d3-a456-426614174001",
                    "cwd": "/tmp/project",
                    "cli_version": "0.108.0",
                    "source": "cli",
                },
            }
        ],
    )
    _write_jsonl(
        claude_file,
        [
            {
                "type": "user",
                "sessionId": "claude-session-1",
                "uuid": "claude-msg-1",
                "message": {
                    "role": "user",
                    "content": "hello",
                },
            }
        ],
    )

    codex_messages = parse_codex_jsonl_file(codex_file)
    claude_messages = parse_claude_jsonl_file(claude_file)

    assert codex_messages[0].timestamp == "1970-01-01T00:00:01Z"
    assert claude_messages[0].timestamp == "1970-01-01T00:00:01Z"


def test_shared_tool_result_normalization_across_ecosystems(tmp_path: Path) -> None:
    oversized_output = "x" * 13_050

    codex_file = tmp_path / "rollout-2026-03-04T10-10-00-123e4567-e89b-12d3-a456-426614174002.jsonl"
    claude_file = tmp_path / "claude-session-tool-result.jsonl"

    _write_jsonl(
        codex_file,
        [
            {
                "timestamp": "2026-03-04T10:10:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": "123e4567-e89b-12d3-a456-426614174002",
                    "cwd": "/tmp/project",
                    "cli_version": "0.108.0",
                    "source": "cli",
                },
            },
            {
                "timestamp": "2026-03-04T10:10:01.000Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "tool-call-1",
                    "output": oversized_output,
                },
            },
        ],
    )

    _write_jsonl(
        claude_file,
        [
            {
                "timestamp": "2026-03-04T10:10:01.000Z",
                "type": "user",
                "sessionId": "claude-session-2",
                "uuid": "claude-msg-tool-result",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-call-1",
                            "content": oversized_output,
                            "is_error": False,
                        }
                    ],
                },
            }
        ],
    )

    codex_messages = parse_codex_jsonl_file(codex_file)
    claude_messages = parse_claude_jsonl_file(claude_file)

    codex_content = _first_tool_result_content(codex_messages)
    claude_content = _first_tool_result_content(claude_messages)

    assert isinstance(codex_content, list)
    assert isinstance(claude_content, list)
    assert codex_content[1]["type"] == "truncation_meta"
    assert claude_content[1]["type"] == "truncation_meta"
    assert codex_content[1]["truncated"] is True
    assert claude_content[1]["truncated"] is True


def test_shared_text_message_semantics_for_core_message_events(tmp_path: Path) -> None:
    codex_file = tmp_path / "rollout-2026-03-04T10-20-00-123e4567-e89b-12d3-a456-426614174003.jsonl"
    claude_file = tmp_path / "claude-session-text.jsonl"

    _write_jsonl(
        codex_file,
        [
            {
                "timestamp": "2026-03-04T10:20:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": "123e4567-e89b-12d3-a456-426614174003",
                    "cwd": "/tmp/project",
                    "cli_version": "0.108.0",
                    "source": "cli",
                },
            },
            {
                "timestamp": "2026-03-04T10:20:01.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "normalized text"}],
                },
            },
        ],
    )

    _write_jsonl(
        claude_file,
        [
            {
                "timestamp": "2026-03-04T10:20:01.000Z",
                "type": "assistant",
                "sessionId": "claude-session-3",
                "uuid": "claude-msg-3",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "normalized text"}],
                },
            }
        ],
    )

    codex_messages = parse_codex_jsonl_file(codex_file)
    claude_messages = parse_claude_jsonl_file(claude_file)

    codex_text = _render_text_content(codex_messages[-1].message.content)
    claude_text = _render_text_content(claude_messages[-1].message.content)

    assert codex_messages[-1].message.role == "assistant"
    assert claude_messages[-1].message.role == "assistant"
    assert codex_text == "normalized text"
    assert claude_text == "normalized text"
