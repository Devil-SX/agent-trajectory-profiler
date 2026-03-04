"""Codex rollout trajectory parser."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_vis.exceptions import SessionParseError
from agent_vis.models import (
    MessageRecord,
    ParsedSessionData,
    Session,
    SessionMetadata,
    SessionStatistics,
)
from agent_vis.parsers.base import TrajectoryParser
from agent_vis.parsers.canonical import (
    CanonicalEvent,
    TrajectoryEventAdapter,
    get_adapter,
    parse_jsonl_to_canonical_with_diagnostics,
    register_adapter,
)
from agent_vis.parsers.claude_code import calculate_session_statistics, extract_session_metadata

_UUID_TAIL_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
_EXIT_CODE_RE = re.compile(r"Process exited with code\s+(-?\d+)")
_PARENT_ID_KEYS = (
    "parent_session_id",
    "parent_thread_id",
    "parent_id",
    "parentSessionId",
    "parentThreadId",
)
_ROOT_ID_KEYS = (
    "root_session_id",
    "root_thread_id",
    "root_id",
    "rootSessionId",
    "rootThreadId",
)
_MAX_DIAGNOSTIC_SAMPLES = 12
_STATUS_SUPPORTED = "supported"
_STATUS_STORED_NOT_USED_YET = "stored_not_used_yet"
_STATUS_IGNORED_EXPECTED = "ignored_expected"

logger = logging.getLogger(__name__)

CODEX_EVENT_COVERAGE_MATRIX: dict[str, dict[str, str]] = {
    "session_meta": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to synthetic metadata marker message",
    },
    "turn_context": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "compacted": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:user_message": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to user text message",
    },
    "event_msg:token_count": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to assistant token_count message with usage",
    },
    "event_msg:agent_message": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to assistant text message",
    },
    "event_msg:agent_reasoning": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:task_started": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:task_complete": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:turn_aborted": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:context_compacted": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:item_completed": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "event_msg:turn_context": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "response_item:message": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to role-preserving message",
    },
    "response_item:function_call": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to assistant tool_use block",
    },
    "response_item:custom_tool_call": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to assistant tool_use block",
    },
    "response_item:function_call_output": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to user tool_result block",
    },
    "response_item:custom_tool_call_output": {
        "status": _STATUS_SUPPORTED,
        "behavior": "maps to user tool_result block",
    },
    "response_item:web_search_call": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "response_item:reasoning": {
        "status": _STATUS_STORED_NOT_USED_YET,
        "behavior": "retained as canonical event; currently excluded from message mapping",
    },
    "<unknown_top_level>": {
        "status": _STATUS_IGNORED_EXPECTED,
        "behavior": (
            "dropped before canonical conversion; " "diagnostics capture top-level type + line"
        ),
    },
}


def _session_id_from_source_path(source_path: str) -> str:
    stem = Path(source_path).stem
    match = _UUID_TAIL_RE.search(stem)
    if match:
        return match.group(1)
    return stem


def _extract_non_empty_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
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


def _resolve_codex_lineage(file_path: Path, session_id: str) -> tuple[str, str | None, str | None]:
    """Resolve logical lineage for one Codex rollout file.

    Returns (logical_session_id, parent_session_id, root_session_id).
    """
    parent_session_id: str | None = None
    root_session_id: str | None = None

    try:
        with open(file_path, encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if raw.get("type") != "session_meta":
                    continue
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    continue

                for candidate in _lineage_payload_candidates(payload):
                    parent_session_id = parent_session_id or _extract_non_empty_str(
                        candidate,
                        _PARENT_ID_KEYS,
                    )
                    root_session_id = root_session_id or _extract_non_empty_str(
                        candidate,
                        _ROOT_ID_KEYS,
                    )
                    if parent_session_id and root_session_id:
                        break
    except OSError:
        # Fall back to physical-only view if lineage cannot be inspected.
        pass

    logical_session_id = root_session_id or parent_session_id or session_id
    return logical_session_id, parent_session_id, root_session_id


def _safe_timestamp(raw_timestamp: Any, line_number: int) -> str:
    if isinstance(raw_timestamp, str) and raw_timestamp:
        return raw_timestamp
    # Keep a deterministic ISO timestamp fallback when source data is incomplete.
    return f"1970-01-01T00:00:{line_number % 60:02d}Z"


def _normalize_user_text_for_dedupe(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _extract_user_text_message(message: MessageRecord) -> str | None:
    if not message.is_user_message or message.message is None:
        return None
    if message.message.role != "user":
        return None
    content = message.message.content
    if not isinstance(content, str):
        return None
    normalized = _normalize_user_text_for_dedupe(content)
    return normalized or None


def _parse_timestamp_or_none(raw_timestamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _infer_user_prompt_channel(message: MessageRecord) -> str:
    if "-user-" in message.uuid:
        return "event_user_message"
    if "-msg-" in message.uuid:
        return "response_item_message"
    return "other"


def _is_cross_channel_overlap(previous: MessageRecord, current: MessageRecord) -> bool:
    channels = {_infer_user_prompt_channel(previous), _infer_user_prompt_channel(current)}
    return channels == {"event_user_message", "response_item_message"}


def _dedupe_overlapping_user_prompts(
    messages: list[MessageRecord],
    *,
    max_window_seconds: float = 2.0,
) -> list[MessageRecord]:
    """Drop duplicate user prompts emitted by overlapping Codex event channels.

    Codex may emit the same user prompt via:
    - event_msg.user_message
    - response_item.message(role=user)

    We dedupe only cross-channel adjacent text duplicates within a short window
    to avoid swallowing genuine repeated user inputs.
    """
    if not messages:
        return messages

    deduped: list[MessageRecord] = []
    for message in messages:
        current_text = _extract_user_text_message(message)
        if current_text is None:
            deduped.append(message)
            continue

        current_ts = _parse_timestamp_or_none(message.timestamp)
        if current_ts is None:
            deduped.append(message)
            continue

        duplicate_index: int | None = None
        for index in range(len(deduped) - 1, -1, -1):
            previous = deduped[index]
            previous_text = _extract_user_text_message(previous)
            if previous_text is None:
                continue
            previous_ts = _parse_timestamp_or_none(previous.timestamp)
            if previous_ts is None:
                continue

            delta_seconds = abs((current_ts - previous_ts).total_seconds())
            if delta_seconds > max_window_seconds:
                continue
            if previous_text != current_text:
                continue
            if not _is_cross_channel_overlap(previous, message):
                continue

            duplicate_index = index
            break

        if duplicate_index is None:
            deduped.append(message)
            continue

        previous_channel = _infer_user_prompt_channel(deduped[duplicate_index])
        current_channel = _infer_user_prompt_channel(message)
        # Keep event_msg.user_message as canonical when both channels overlap.
        if current_channel == "event_user_message" and previous_channel == "response_item_message":
            deduped[duplicate_index] = message
        # Else keep existing canonical message and drop current duplicate.

    return deduped


def _coverage_key_from_raw_event(raw_event: dict[str, Any]) -> str:
    top_type = str(raw_event.get("type") or "<missing_top_level>")
    payload = raw_event.get("payload")
    if not isinstance(payload, dict):
        return top_type
    subtype = payload.get("type")
    if not isinstance(subtype, str) or not subtype.strip():
        return top_type
    return f"{top_type}:{subtype.strip()}"


def _coverage_status(coverage_key: str) -> str | None:
    entry = CODEX_EVENT_COVERAGE_MATRIX.get(coverage_key)
    if entry is None:
        return None
    status = entry.get("status")
    if isinstance(status, str):
        return status
    return None


def _append_drop_sample(
    samples: list[dict[str, Any]],
    *,
    line_number: int,
    event_type: str,
    reason: str,
    sample_limit: int,
) -> None:
    if len(samples) >= sample_limit:
        return
    samples.append(
        {
            "line_number": line_number,
            "event_type": event_type,
            "reason": reason,
        }
    )


def _extract_text_blocks(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

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
        return text_blocks[0]["text"]
    return text_blocks


def _summarize_text_like_payload(payload: dict[str, Any]) -> str:
    candidates = (
        payload.get("message"),
        payload.get("summary"),
        payload.get("reason"),
        payload.get("status"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, list):
            for item in candidate:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return f"{payload.get('type', 'event')}"


def _build_message_record(
    *,
    session_id: str,
    uuid: str,
    timestamp: str,
    role: str,
    content: str | list[dict[str, Any]],
    cwd: str | None = None,
    version: str | None = None,
    usage: dict[str, Any] | None = None,
    git_branch: str | None = None,
) -> MessageRecord:
    payload: dict[str, Any] = {
        "type": "assistant" if role == "assistant" else "user",
        "sessionId": session_id,
        "uuid": uuid,
        "timestamp": timestamp,
        "cwd": cwd,
        "version": version,
        "gitBranch": git_branch,
        "isSidechain": False,
        "message": {
            "role": role,
            "content": content,
        },
    }
    if usage is not None:
        payload["message"]["usage"] = usage
    return MessageRecord(**payload)


@register_adapter
class CodexEventAdapter(TrajectoryEventAdapter):
    """Canonical adapter for local Codex rollout JSONL files."""

    ecosystem_name = "codex"

    def to_canonical_event(
        self, raw_event: dict[str, Any], *, source_path: Path, line_number: int
    ) -> CanonicalEvent | None:
        top_type = raw_event.get("type")
        if top_type not in {
            "session_meta",
            "response_item",
            "event_msg",
            "turn_context",
            "compacted",
        }:
            return None

        return CanonicalEvent(
            ecosystem=self.ecosystem_name,
            source_path=str(source_path),
            line_number=line_number,
            event_kind=str(top_type),
            timestamp=_safe_timestamp(raw_event.get("timestamp"), line_number),
            actor=str(top_type),
            payload=raw_event,
        )

    def canonical_to_message(self, event: CanonicalEvent) -> MessageRecord | None:
        raw = event.payload
        top_type = raw.get("type")
        payload = raw.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        session_id = _session_id_from_source_path(event.source_path)
        timestamp = _safe_timestamp(raw.get("timestamp"), event.line_number)

        if top_type == "session_meta":
            if isinstance(payload_dict.get("id"), str):
                session_id = str(payload_dict["id"])
            content = f"session_meta source={payload_dict.get('source', 'codex')}"
            return _build_message_record(
                session_id=session_id,
                uuid=f"{session_id}-meta-{event.line_number}",
                timestamp=timestamp,
                role="user",
                content=content,
                cwd=payload_dict.get("cwd") if isinstance(payload_dict.get("cwd"), str) else None,
                version=(
                    payload_dict.get("cli_version")
                    if isinstance(payload_dict.get("cli_version"), str)
                    else None
                ),
            )

        if top_type in {"turn_context", "compacted"}:
            return None

        if top_type == "event_msg":
            event_kind = payload_dict.get("type")
            if event_kind == "user_message":
                text = (
                    payload_dict.get("message")
                    if isinstance(payload_dict.get("message"), str)
                    else ""
                )
                return _build_message_record(
                    session_id=session_id,
                    uuid=f"{session_id}-user-{event.line_number}",
                    timestamp=timestamp,
                    role="user",
                    content=text,
                )
            if event_kind == "token_count":
                info = payload_dict.get("info")
                if not isinstance(info, dict):
                    return None
                usage_src = info.get("last_token_usage") or info.get("total_token_usage")
                if not isinstance(usage_src, dict):
                    return None
                usage: dict[str, Any] = {
                    "input_tokens": int(usage_src.get("input_tokens") or 0),
                    "output_tokens": int(usage_src.get("output_tokens") or 0),
                }
                cached = usage_src.get("cached_input_tokens")
                if isinstance(cached, int):
                    usage["cache_read_input_tokens"] = cached
                return _build_message_record(
                    session_id=session_id,
                    uuid=f"{session_id}-tok-{event.line_number}",
                    timestamp=timestamp,
                    role="assistant",
                    content="token_count",
                    usage=usage,
                )
            if event_kind == "agent_message":
                return _build_message_record(
                    session_id=session_id,
                    uuid=f"{session_id}-agent-{event.line_number}",
                    timestamp=timestamp,
                    role="assistant",
                    content=_summarize_text_like_payload(payload_dict),
                )
            return None

        if top_type != "response_item":
            return None

        item_type = payload_dict.get("type")
        if item_type == "message":
            role = payload_dict.get("role")
            role_str = role if isinstance(role, str) else "assistant"
            normalized_role = "user" if role_str == "user" else "assistant"
            content = _extract_text_blocks(payload_dict.get("content"))
            return _build_message_record(
                session_id=session_id,
                uuid=f"{session_id}-msg-{event.line_number}",
                timestamp=timestamp,
                role=normalized_role,
                content=content,
            )

        if item_type in {"function_call", "custom_tool_call"}:
            tool_name = (
                payload_dict.get("name")
                if isinstance(payload_dict.get("name"), str)
                else "unknown_tool"
            )
            call_id = (
                payload_dict.get("call_id")
                if isinstance(payload_dict.get("call_id"), str)
                else f"{session_id}-call-{event.line_number}"
            )

            input_data: Any = payload_dict.get("input")
            if item_type == "function_call":
                input_data = payload_dict.get("arguments")
            if isinstance(input_data, str):
                try:
                    parsed = json.loads(input_data)
                except json.JSONDecodeError:
                    parsed = {"raw": input_data}
                input_data = parsed
            if not isinstance(input_data, dict):
                input_data = {"value": input_data}

            return _build_message_record(
                session_id=session_id,
                uuid=call_id,
                timestamp=timestamp,
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": tool_name,
                        "input": input_data,
                    }
                ],
            )

        if item_type in {"function_call_output", "custom_tool_call_output"}:
            call_id = (
                payload_dict.get("call_id")
                if isinstance(payload_dict.get("call_id"), str)
                else f"{session_id}-result-{event.line_number}"
            )
            raw_output = payload_dict.get("output")
            output_text = raw_output if isinstance(raw_output, str) else str(raw_output or "")
            is_error = False

            if item_type == "custom_tool_call_output" and isinstance(raw_output, str):
                try:
                    parsed_output = json.loads(raw_output)
                except json.JSONDecodeError:
                    parsed_output = None
                if isinstance(parsed_output, dict):
                    metadata = parsed_output.get("metadata")
                    if isinstance(metadata, dict):
                        exit_code = metadata.get("exit_code")
                        if isinstance(exit_code, int):
                            is_error = exit_code != 0
                    inner_output = parsed_output.get("output")
                    if isinstance(inner_output, str):
                        output_text = inner_output
            else:
                exit_match = _EXIT_CODE_RE.search(output_text)
                if exit_match is not None:
                    is_error = int(exit_match.group(1)) != 0

            return _build_message_record(
                session_id=session_id,
                uuid=f"{call_id}-result",
                timestamp=timestamp,
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": output_text,
                        "is_error": is_error,
                    }
                ],
            )

        if item_type in {"reasoning", "web_search_call"}:
            return None

        return None


def parse_codex_jsonl_file_with_diagnostics(
    file_path: Path,
    *,
    sample_limit: int = _MAX_DIAGNOSTIC_SAMPLES,
) -> tuple[list[MessageRecord], dict[str, Any]]:
    """Parse one Codex rollout file and expose explicit coverage/drop diagnostics."""
    adapter = get_adapter("codex")
    canonical_session, canonical_diag = parse_jsonl_to_canonical_with_diagnostics(
        file_path,
        adapter,
        sample_limit=sample_limit,
    )

    pre_dedupe_messages: list[MessageRecord] = []
    unmapped_event_counts: dict[str, int] = {}
    policy_drop_counts: dict[str, int] = {}
    dropped_samples: list[dict[str, Any]] = []

    for sample in canonical_diag.dropped_samples:
        _append_drop_sample(
            dropped_samples,
            line_number=sample.line_number,
            event_type=sample.event_kind,
            reason=sample.reason,
            sample_limit=sample_limit,
        )

    for event in canonical_session.events:
        coverage_key = _coverage_key_from_raw_event(event.payload)
        try:
            message = adapter.canonical_to_message(event)
        except ValidationError:
            unmapped_event_counts[coverage_key] = unmapped_event_counts.get(coverage_key, 0) + 1
            _append_drop_sample(
                dropped_samples,
                line_number=event.line_number,
                event_type=coverage_key,
                reason="validation_error",
                sample_limit=sample_limit,
            )
            continue

        if message is not None:
            pre_dedupe_messages.append(message)
            continue

        coverage_status = _coverage_status(coverage_key)
        if coverage_status in {_STATUS_STORED_NOT_USED_YET, _STATUS_IGNORED_EXPECTED}:
            policy_drop_counts[coverage_key] = policy_drop_counts.get(coverage_key, 0) + 1
            _append_drop_sample(
                dropped_samples,
                line_number=event.line_number,
                event_type=coverage_key,
                reason=f"policy_{coverage_status}",
                sample_limit=sample_limit,
            )
            continue

        unmapped_event_counts[coverage_key] = unmapped_event_counts.get(coverage_key, 0) + 1
        _append_drop_sample(
            dropped_samples,
            line_number=event.line_number,
            event_type=coverage_key,
            reason="canonical_to_message_returned_none",
            sample_limit=sample_limit,
        )

    messages = _dedupe_overlapping_user_prompts(pre_dedupe_messages)
    deduped_user_prompt_count = max(0, len(pre_dedupe_messages) - len(messages))
    diagnostics: dict[str, Any] = {
        "raw_event_count": canonical_diag.raw_event_count,
        "raw_event_kind_counts": dict(canonical_diag.raw_event_kind_counts),
        "dropped_top_level_counts": dict(canonical_diag.dropped_event_kind_counts),
        "unmapped_event_counts": unmapped_event_counts,
        "policy_drop_counts": policy_drop_counts,
        "mapped_message_count_before_dedupe": len(pre_dedupe_messages),
        "mapped_message_count_after_dedupe": len(messages),
        "deduped_user_prompt_count": deduped_user_prompt_count,
        "dropped_samples": dropped_samples,
        "coverage_matrix": CODEX_EVENT_COVERAGE_MATRIX,
    }
    return messages, diagnostics


def parse_codex_jsonl_file(file_path: Path) -> list[MessageRecord]:
    """Parse one Codex rollout JSONL file into internal message records."""
    messages, diagnostics = parse_codex_jsonl_file_with_diagnostics(file_path)
    if (
        diagnostics["dropped_top_level_counts"]
        or diagnostics["unmapped_event_counts"]
        or diagnostics["policy_drop_counts"]
        or diagnostics["deduped_user_prompt_count"] > 0
    ):
        logger.info(
            "Codex coverage diagnostics for %s | raw=%s | dropped_top=%s | "
            "unmapped=%s | policy_drop=%s | deduped=%s | samples=%s",
            file_path,
            diagnostics["raw_event_kind_counts"],
            diagnostics["dropped_top_level_counts"],
            diagnostics["unmapped_event_counts"],
            diagnostics["policy_drop_counts"],
            diagnostics["deduped_user_prompt_count"],
            diagnostics["dropped_samples"],
        )
    return messages


def _resolve_codex_session_id(messages: list[MessageRecord], file_path: Path) -> str:
    if messages:
        return messages[0].sessionId
    return _session_id_from_source_path(str(file_path))


def find_codex_session_files(directory: Path) -> list[Path]:
    """Discover Codex rollout files recursively."""
    if not directory.exists():
        raise SessionParseError(f"Directory does not exist: {directory}")
    if not directory.is_dir():
        raise SessionParseError(f"Path is not a directory: {directory}")
    return sorted(f for f in directory.rglob("rollout-*.jsonl") if f.is_file())


def parse_codex_session_file(
    file_path: Path,
    *,
    inactivity_threshold: float = 1800.0,
    model_timeout_threshold: float = 600.0,
) -> Session:
    """Parse a Codex rollout file into a Session object."""
    messages = parse_codex_jsonl_file(file_path)
    if not messages:
        raise SessionParseError(f"No valid messages found in {file_path}")

    session_id = _resolve_codex_session_id(messages, file_path)
    metadata = extract_session_metadata(messages, session_id, file_path)
    logical_session_id, parent_session_id, root_session_id = _resolve_codex_lineage(
        file_path, session_id
    )
    metadata.physical_session_id = session_id
    metadata.logical_session_id = logical_session_id
    metadata.parent_session_id = parent_session_id
    metadata.root_session_id = root_session_id
    statistics = calculate_session_statistics(
        messages,
        inactivity_threshold=inactivity_threshold,
        model_timeout_threshold=model_timeout_threshold,
    )
    return Session(
        metadata=metadata,
        messages=messages,
        subagent_sessions=[],
        statistics=statistics,
    )


def parse_codex_session_directory(
    directory: Path,
    *,
    inactivity_threshold: float = 1800.0,
    model_timeout_threshold: float = 600.0,
) -> ParsedSessionData:
    """Parse all Codex rollout files in a directory tree."""
    session_files = find_codex_session_files(directory)
    if not session_files:
        raise SessionParseError(f"No session files found in {directory}")

    sessions: list[Session] = []
    errors: list[str] = []
    for file_path in session_files:
        try:
            sessions.append(
                parse_codex_session_file(
                    file_path,
                    inactivity_threshold=inactivity_threshold,
                    model_timeout_threshold=model_timeout_threshold,
                )
            )
        except SessionParseError as exc:
            errors.append(f"{file_path.name}: {exc}")

    if not sessions and errors:
        raise SessionParseError("Failed to parse any codex sessions. Errors:\n" + "\n".join(errors))
    return ParsedSessionData(
        sessions=sessions,
        source_path=str(directory),
    )


class CodexParser(TrajectoryParser):
    """TrajectoryParser implementation for local Codex rollout JSONL."""

    def __init__(
        self,
        inactivity_threshold: float = 1800.0,
        model_timeout_threshold: float = 600.0,
    ) -> None:
        self.inactivity_threshold = inactivity_threshold
        self.model_timeout_threshold = model_timeout_threshold

    @property
    def ecosystem_name(self) -> str:
        return "codex"

    def parse_file(self, file_path: Path) -> list[MessageRecord]:
        return parse_codex_jsonl_file(file_path)

    def extract_metadata(
        self, messages: list[MessageRecord], session_id: str, file_path: Path
    ) -> SessionMetadata:
        return extract_session_metadata(messages, session_id, file_path)

    def calculate_statistics(self, messages: list[MessageRecord]) -> SessionStatistics:
        return calculate_session_statistics(
            messages,
            inactivity_threshold=self.inactivity_threshold,
            model_timeout_threshold=self.model_timeout_threshold,
        )

    def find_session_files(self, directory: Path) -> list[Path]:
        return find_codex_session_files(directory)

    def parse_session(self, file_path: Path) -> Session:
        return parse_codex_session_file(
            file_path,
            inactivity_threshold=self.inactivity_threshold,
            model_timeout_threshold=self.model_timeout_threshold,
        )
