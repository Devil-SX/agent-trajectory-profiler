"""Codex raw->parser->API parity regression tests."""

from __future__ import annotations

import json
import shutil
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_vis.api.app import app
from agent_vis.api.config import Settings, get_settings
from agent_vis.parsers.canonical import canonical_to_messages, get_adapter, parse_jsonl_to_canonical
from agent_vis.parsers.codex import parse_codex_jsonl_file

PARITY_FIXTURE_FILE = (
    Path(__file__).parent
    / "fixtures"
    / "codex_parity"
    / "rollout-2026-03-01T09-00-00-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
)
PARITY_SESSION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _count_adjacent_duplicate_user_messages(messages: list) -> int:
    duplicates = 0
    previous: str | None = None
    for msg in messages:
        if not msg.is_user_message or msg.message is None:
            continue
        if not isinstance(msg.message.content, str):
            continue
        text = msg.message.content.strip()
        if not text:
            continue
        if previous == text:
            duplicates += 1
        previous = text
    return duplicates


def test_codex_gold_fixture_parser_parity_contract() -> None:
    """Parser stage parity: raw rollout fixture -> canonical events -> message records."""
    assert (
        PARITY_FIXTURE_FILE.exists()
    ), "parser-stage parity setup failed: Codex golden fixture is missing"

    with PARITY_FIXTURE_FILE.open(encoding="utf-8") as handle:
        raw_events = [json.loads(line) for line in handle if line.strip()]
    assert len(raw_events) == 10, "parser-stage parity failed: unexpected raw event count"

    adapter = get_adapter("codex")
    canonical_session = parse_jsonl_to_canonical(PARITY_FIXTURE_FILE, adapter)
    canonical_messages = canonical_to_messages(canonical_session, adapter)
    direct_messages = parse_codex_jsonl_file(PARITY_FIXTURE_FILE)
    assert (
        len(canonical_session.events) == 10
    ), "parser-stage parity failed: canonical conversion unexpectedly dropped raw events"
    assert (
        len(canonical_messages) == 8
    ), "parser-stage parity failed: canonical message materialization count mismatch"
    assert (
        len(direct_messages) == 7
    ), "parser-stage parity failed: final parser message count mismatch after dedupe"
    assert (
        len(canonical_messages) - len(direct_messages) == 1
    ), "parser-stage parity failed: user-prompt dedupe delta changed unexpectedly"
    assert (
        len(canonical_session.events) - len(direct_messages) == 3
    ), "parser-stage parity failed: dropped-event count changed unexpectedly"

    user_count = sum(1 for msg in direct_messages if msg.is_user_message)
    assistant_count = sum(1 for msg in direct_messages if msg.is_assistant_message)
    assert user_count == 3, "parser-stage parity failed: user-message count drift"
    assert assistant_count == 4, "parser-stage parity failed: assistant-message count drift"

    tool_use_ids: list[str] = []
    tool_result_ids: list[str] = []
    token_count_messages = 0
    for msg in direct_messages:
        if msg.message is None:
            continue
        content = msg.message.content
        if isinstance(content, str) and content == "token_count":
            token_count_messages += 1
            usage = msg.message.usage
            assert usage is not None, "parser-stage parity failed: token_count usage missing"
            assert (
                usage.input_tokens == 42
            ), "parser-stage parity failed: token_count input_tokens changed"
            assert (
                usage.output_tokens == 17
            ), "parser-stage parity failed: token_count output_tokens changed"
            assert (
                usage.cache_read_input_tokens == 5
            ), "parser-stage parity failed: token_count cache_read_input_tokens changed"
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                tool_use_ids.append(str(block.get("id")))
            if block_type == "tool_result":
                tool_result_ids.append(str(block.get("tool_use_id")))

    assert (
        token_count_messages == 1
    ), "parser-stage parity failed: token_count message should appear exactly once"
    assert tool_use_ids == [
        "call-parity-read-1"
    ], "parser-stage parity failed: tool_use linkage key drift"
    assert tool_result_ids == [
        "call-parity-read-1"
    ], "parser-stage parity failed: tool_result linkage key drift"
    assert (
        _count_adjacent_duplicate_user_messages(direct_messages) == 0
    ), "parser-stage parity failed: overlapping user prompt was not deduplicated"


def test_codex_gold_fixture_api_detail_matches_parser_output(tmp_path: Path) -> None:
    """API stage parity: parser output stored in DB is returned unchanged by session detail API."""
    codex_root = tmp_path / "codex_sessions"
    codex_target_dir = codex_root / "2026" / "03" / "01"
    codex_target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PARITY_FIXTURE_FILE, codex_target_dir / PARITY_FIXTURE_FILE.name)

    claude_root = tmp_path / "claude_sessions"
    claude_root.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        session_path=claude_root,
        codex_session_path=codex_root,
        db_path=tmp_path / "codex_parity.db",
        api_host="127.0.0.1",
        api_port=8000,
        api_reload=False,
        log_level="INFO",
        cors_origins=["http://localhost:5173"],
    )

    api_app_module = import_module("agent_vis.api.app")
    get_settings.cache_clear()
    try:
        with patch.object(api_app_module, "get_settings", return_value=settings):
            with TestClient(app) as client:
                list_response = client.get("/api/sessions?ecosystem=codex&view=physical")
                assert (
                    list_response.status_code == 200
                ), "api-stage parity failed: unable to list codex sessions"
                sessions = list_response.json()["sessions"]
                assert len(sessions) == 1, (
                    "api-stage parity failed: codex parity fixture "
                    "should produce one physical session"
                )
                assert (
                    sessions[0]["session_id"] == PARITY_SESSION_ID
                ), "api-stage parity failed: unexpected session id"

                detail_response = client.get(f"/api/sessions/{PARITY_SESSION_ID}")
                assert (
                    detail_response.status_code == 200
                ), "api-stage parity failed: session detail endpoint did not return parity fixture"
                detail_payload = detail_response.json()
                messages = detail_payload["session"]["messages"]
                assert len(messages) == 7, (
                    "api-stage parity failed: session detail message count "
                    "drifted from parser baseline"
                )

                tool_use_ids = []
                tool_result_ids = []
                for item in messages:
                    content = item.get("message", {}).get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            tool_use_ids.append(block.get("id"))
                        if block.get("type") == "tool_result":
                            tool_result_ids.append(block.get("tool_use_id"))

                assert tool_use_ids == [
                    "call-parity-read-1"
                ], "api-stage parity failed: tool_use chain changed before frontend consumption"
                assert tool_result_ids == [
                    "call-parity-read-1"
                ], "api-stage parity failed: tool_result chain changed before frontend consumption"
    finally:
        get_settings.cache_clear()
