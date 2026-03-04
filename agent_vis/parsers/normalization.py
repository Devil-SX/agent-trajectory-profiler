"""Shared parser normalization helpers and typed intermediate models."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel

from agent_vis.models import MessageRecord

_MAX_TOOL_RESULT_TEXT_CHARS = 12_000
_MAX_TOOL_RESULT_JSON_BYTES = 24_000
_MAX_TOOL_RESULT_ITEMS = 200
_TOOL_RESULT_PREVIEW_CHARS = 1_000


def coerce_timestamp(raw_timestamp: Any, line_number: int) -> str:
    """Normalize raw timestamps and provide deterministic fallback for missing values."""
    if isinstance(raw_timestamp, str) and raw_timestamp:
        return raw_timestamp
    return f"1970-01-01T00:00:{line_number % 60:02d}Z"


def extract_non_empty_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _extract_nested_dict(payload: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, dict):
        return current
    return None


def _lineage_payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _append_if_dict(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        marker = id(candidate)
        if marker in seen:
            return
        seen.add(marker)
        candidates.append(candidate)

    _append_if_dict(payload)
    _append_if_dict(payload.get("lineage"))

    for path in (
        ("source",),
        ("source", "lineage"),
        ("source", "thread_spawn"),
        ("source", "subagent"),
        ("source", "subagent", "thread_spawn"),
    ):
        _append_if_dict(_extract_nested_dict(payload, path))

    return candidates


def extract_lineage_ids(
    payload: dict[str, Any],
    *,
    parent_keys: tuple[str, ...],
    root_keys: tuple[str, ...],
) -> tuple[str | None, str | None]:
    """Extract parent/root lineage IDs from known nested source payload paths."""
    parent_session_id: str | None = None
    root_session_id: str | None = None

    for candidate in _lineage_payload_candidates(payload):
        parent_session_id = parent_session_id or extract_non_empty_str(candidate, parent_keys)
        root_session_id = root_session_id or extract_non_empty_str(candidate, root_keys)
        if parent_session_id and root_session_id:
            break

    return parent_session_id, root_session_id


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _hash_reference(value: Any) -> str:
    digest = sha256(safe_json_dumps(value).encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _normalize_tool_output_blocks(raw_output: Any) -> list[dict[str, Any]]:
    if isinstance(raw_output, dict):
        return [raw_output]
    if isinstance(raw_output, list):
        blocks: list[dict[str, Any]] = []
        for item in raw_output:
            if isinstance(item, dict):
                blocks.append(item)
            else:
                blocks.append({"type": "value", "value": item})
        return blocks
    return [{"type": "value", "value": raw_output}]


def normalize_tool_result_content(raw_output: Any) -> str | list[dict[str, Any]]:
    """Normalize tool output content with bounded payload protection."""
    if isinstance(raw_output, str):
        if len(raw_output) <= _MAX_TOOL_RESULT_TEXT_CHARS:
            return raw_output
        raw_ref = _hash_reference(raw_output)
        preview = raw_output[:_MAX_TOOL_RESULT_TEXT_CHARS]
        return [
            {"type": "text", "text": preview},
            {
                "type": "truncation_meta",
                "raw_ref": raw_ref,
                "original_chars": len(raw_output),
                "truncated": True,
            },
        ]

    blocks = _normalize_tool_output_blocks(raw_output)
    serialized = safe_json_dumps(blocks)
    if (
        len(serialized.encode("utf-8")) <= _MAX_TOOL_RESULT_JSON_BYTES
        and len(blocks) <= _MAX_TOOL_RESULT_ITEMS
    ):
        return blocks

    raw_ref = _hash_reference(raw_output)
    return [
        {
            "type": "structured_summary",
            "raw_ref": raw_ref,
            "original_bytes": len(serialized.encode("utf-8")),
            "item_count": len(blocks),
            "truncated": True,
            "preview": serialized[:_TOOL_RESULT_PREVIEW_CHARS],
        }
    ]


def normalize_message_content(
    content: Any,
    *,
    text_only: bool,
) -> str | list[dict[str, Any]]:
    """Normalize message content for parser adapters.

    `text_only=True` extracts plain text fallback used by Codex response-item messages.
    `text_only=False` preserves structured blocks and normalizes `tool_result.content`.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    if text_only:
        text_blocks: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                text_blocks.append({"type": "text", "text": text})
        if not text_blocks:
            return ""
        if len(text_blocks) == 1:
            first_text = text_blocks[0].get("text")
            return first_text if isinstance(first_text, str) else ""
        return text_blocks

    normalized: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        normalized_block = dict(block)
        block_type = normalized_block.get("type")
        if block_type == "tool_result":
            normalized_block["content"] = normalize_tool_result_content(
                normalized_block.get("content")
            )
        elif not isinstance(block_type, str) and isinstance(normalized_block.get("text"), str):
            normalized_block = {"type": "text", "text": normalized_block["text"]}
        normalized.append(normalized_block)

    if not normalized:
        return ""
    return normalized


def parse_json_if_possible(raw_output: Any) -> Any | None:
    if not isinstance(raw_output, str):
        return None
    stripped = raw_output.strip()
    if not stripped or stripped[0] not in {"{", "["}:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


class NormalizedTokenUsageIR(BaseModel):
    """Typed normalized token-usage model for intermediate conversion."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    service_tier: str | None = None


class NormalizedMessageIR(BaseModel):
    """Typed normalized message model used before MessageRecord materialization."""

    role: Literal["user", "assistant", "system"]
    content: str | list[dict[str, Any]]
    model: str | None = None
    id: str | None = None
    type: str | None = None
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: NormalizedTokenUsageIR | None = None


class NormalizedRecordIR(BaseModel):
    """Typed normalized record model used by parser adapters."""

    session_id: str
    uuid: str
    timestamp: str
    record_type: Literal["user", "assistant", "file-history-snapshot", "summary"]
    parent_uuid: str | None = None
    user_type: str | None = None
    cwd: str | None = None
    version: str | None = None
    git_branch: str | None = None
    is_sidechain: bool | None = None
    agent_id: str | None = None
    message: NormalizedMessageIR | None = None
    is_meta: bool | None = None
    is_snapshot_update: bool | None = None
    thinking_metadata: dict[str, Any] | None = None
    todos: list[dict[str, Any]] | None = None
    permission_mode: str | None = None
    snapshot: dict[str, Any] | None = None
    message_id: str | None = None
    summary: str | None = None
    leaf_uuid: str | None = None

    def to_message_record(self) -> MessageRecord:
        payload: dict[str, Any] = {
            "sessionId": self.session_id,
            "uuid": self.uuid,
            "timestamp": self.timestamp,
            "type": self.record_type,
            "parentUuid": self.parent_uuid,
            "userType": self.user_type,
            "cwd": self.cwd,
            "version": self.version,
            "gitBranch": self.git_branch,
            "isSidechain": self.is_sidechain,
            "agentId": self.agent_id,
            "isMeta": self.is_meta,
            "isSnapshotUpdate": self.is_snapshot_update,
            "thinkingMetadata": self.thinking_metadata,
            "todos": self.todos,
            "permissionMode": self.permission_mode,
            "snapshot": self.snapshot,
            "messageId": self.message_id,
            "summary": self.summary,
            "leafUuid": self.leaf_uuid,
        }

        if self.message is not None:
            message_payload: dict[str, Any] = {
                "role": self.message.role,
                "content": self.message.content,
                "model": self.message.model,
                "id": self.message.id,
                "type": self.message.type,
                "stop_reason": self.message.stop_reason,
                "stop_sequence": self.message.stop_sequence,
            }
            if self.message.usage is not None:
                message_payload["usage"] = self.message.usage.model_dump(exclude_none=True)
            payload["message"] = message_payload

        return MessageRecord(**{k: v for k, v in payload.items() if v is not None})


def build_usage_ir(raw_usage: Any) -> NormalizedTokenUsageIR | None:
    if not isinstance(raw_usage, dict):
        return None

    def _as_int(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return 0

    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return None

    service_tier = raw_usage.get("service_tier")
    return NormalizedTokenUsageIR(
        input_tokens=_as_int(raw_usage.get("input_tokens")),
        output_tokens=_as_int(raw_usage.get("output_tokens")),
        cache_creation_input_tokens=_optional_int(raw_usage.get("cache_creation_input_tokens")),
        cache_read_input_tokens=_optional_int(raw_usage.get("cache_read_input_tokens")),
        service_tier=service_tier if isinstance(service_tier, str) else None,
    )
