"""Codex rollout trajectory parser."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

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
from agent_vis.parsers.decoders import get_json_line_decoder
from agent_vis.parsers.normalization import (
    NormalizedMessageIR,
    NormalizedRecordIR,
    build_usage_ir,
    coerce_timestamp,
    extract_lineage_ids,
    extract_non_empty_str,
    normalize_message_content,
    normalize_tool_result_content,
    parse_json_if_possible,
    safe_json_dumps,
)

_UUID_TAIL_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
_EXIT_CODE_RE = re.compile(r"Process exited with code\s+(-?\d+)")
_STATUS_FIELD_RE = re.compile(r"\b(?:status|state|outcome)\s*[:=]\s*([a-zA-Z0-9_\- ]+)")
_TEXTUAL_ERROR_SIGNATURE_RE = re.compile(
    r"\b("
    r"traceback|exception|error|fatal|command failed|failed to|failure|"
    r"non[- ]zero exit|permission denied|not found|timed out|timeout|"
    r"unauthorized|forbidden|connection refused"
    r")\b",
    re.IGNORECASE,
)
_TEXTUAL_SUCCESS_HINT_RE = re.compile(
    r"\b(" r"no errors?|without errors?|0 errors?|success|succeeded|completed successfully" r")\b",
    re.IGNORECASE,
)
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
_MAX_TOOL_RESULT_TEXT_CHARS = 12_000
_MAX_TOOL_RESULT_JSON_BYTES = 24_000
_MAX_TOOL_RESULT_ITEMS = 200
_TOOL_RESULT_PREVIEW_CHARS = 1_000
_STATUS_SUPPORTED = "supported"
_STATUS_STORED_NOT_USED_YET = "stored_not_used_yet"
_STATUS_IGNORED_EXPECTED = "ignored_expected"
_ERROR_STATUS_VALUES = {
    "error",
    "errored",
    "failed",
    "failure",
    "timeout",
    "timed_out",
    "cancelled",
    "canceled",
    "aborted",
    "denied",
}
_SUCCESS_STATUS_VALUES = {
    "ok",
    "done",
    "success",
    "succeeded",
    "completed",
    "complete",
    "finished",
}
_NON_TERMINAL_STATUS_VALUES = {
    "queued",
    "pending",
    "running",
    "in_progress",
    "started",
    "searching",
}
_STRUCTURED_EXIT_CODE_KEYS = ("exit_code", "exitCode", "return_code", "returnCode")
_STRUCTURED_STATUS_CODE_KEYS = ("status_code", "statusCode", "http_status", "httpStatus")
_STRUCTURED_STATUS_KEYS = ("status", "state", "outcome", "result_status")
_STRUCTURED_BOOL_ERROR_KEYS = ("is_error", "error", "failed")
_STRUCTURED_BOOL_SUCCESS_KEYS = ("ok", "success")
_STRUCTURED_TEXT_ERROR_KEYS = (
    "error",
    "error_message",
    "message",
    "stderr",
    "exception",
    "traceback",
    "detail",
    "failure_reason",
)
_WEB_SEARCH_CALL_ID_KEYS = ("call_id", "id", "tool_call_id", "request_id")
_WEB_SEARCH_STATUS_KEYS = ("status", "state", "outcome", "result_status")
_WEB_SEARCH_TOOL_NAME = "web_search_call"

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
        "status": _STATUS_SUPPORTED,
        "behavior": "maps status-aware web_search tool_result block for analytics annotations",
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


def _resolve_codex_lineage(file_path: Path, session_id: str) -> tuple[str, str | None, str | None]:
    """Resolve logical lineage for one Codex rollout file.

    Returns (logical_session_id, parent_session_id, root_session_id).
    """
    parent_session_id: str | None = None
    root_session_id: str | None = None

    decoder = get_json_line_decoder()
    open_mode = "rb" if decoder.read_mode == "binary" else "r"
    open_kwargs: dict[str, Any] = {} if open_mode == "rb" else {"encoding": "utf-8"}

    try:
        with open(file_path, open_mode, **open_kwargs) as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = decoder.decode(stripped)
                except ValueError:
                    continue
                if raw.get("type") != "session_meta":
                    continue
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    continue

                parent_candidate, root_candidate = extract_lineage_ids(
                    payload,
                    parent_keys=_PARENT_ID_KEYS,
                    root_keys=_ROOT_ID_KEYS,
                )
                parent_session_id = parent_session_id or parent_candidate
                root_session_id = root_session_id or root_candidate
                if parent_session_id and root_session_id:
                    break
    except OSError:
        # Fall back to physical-only view if lineage cannot be inspected.
        pass

    logical_session_id = root_session_id or parent_session_id or session_id
    return logical_session_id, parent_session_id, root_session_id


def _safe_timestamp(raw_timestamp: Any, line_number: int) -> str:
    return coerce_timestamp(raw_timestamp, line_number)


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
    return normalize_message_content(content, text_only=True)


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


def _normalize_tool_output_content(raw_output: Any) -> str | list[dict[str, Any]]:
    return normalize_tool_result_content(raw_output)


def _normalize_status_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized.replace("-", "_").replace(" ", "_")


def _status_indicates_error(status: Any) -> bool | None:
    normalized = _normalize_status_token(status)
    if normalized is None:
        return None
    if normalized in _ERROR_STATUS_VALUES:
        return True
    if normalized in _SUCCESS_STATUS_VALUES or normalized in _NON_TERMINAL_STATUS_VALUES:
        return False
    if any(token in normalized for token in ("fail", "error", "timeout", "cancel", "deny")):
        return True
    return None


def _is_non_terminal_status(status: Any) -> bool:
    normalized = _normalize_status_token(status)
    return normalized in _NON_TERMINAL_STATUS_VALUES if normalized else False


def _detect_error_from_text_output(text: str) -> bool | None:
    stripped = text.strip()
    if not stripped:
        return None

    exit_match = _EXIT_CODE_RE.search(stripped)
    if exit_match is not None:
        return int(exit_match.group(1)) != 0

    status_match = _STATUS_FIELD_RE.search(stripped)
    if status_match is not None:
        status_detected = _status_indicates_error(status_match.group(1))
        if status_detected is not None:
            return status_detected

    has_error_signature = _TEXTUAL_ERROR_SIGNATURE_RE.search(stripped) is not None
    has_success_hint = _TEXTUAL_SUCCESS_HINT_RE.search(stripped) is not None
    if has_error_signature and not has_success_hint:
        return True
    if has_success_hint and not has_error_signature:
        return False
    return None


def _detect_error_from_structured_output(raw_output: Any) -> bool | None:
    if isinstance(raw_output, dict):
        saw_explicit_success = False

        for key in _STRUCTURED_EXIT_CODE_KEYS:
            exit_code = raw_output.get(key)
            if isinstance(exit_code, int):
                return exit_code != 0

        for key in _STRUCTURED_STATUS_CODE_KEYS:
            status_code = raw_output.get(key)
            if isinstance(status_code, int):
                return status_code >= 400
            if isinstance(status_code, str) and status_code.strip().isdigit():
                return int(status_code.strip()) >= 400

        for key in _STRUCTURED_BOOL_ERROR_KEYS:
            value = raw_output.get(key)
            if isinstance(value, bool):
                if value:
                    return True
                saw_explicit_success = True
            elif key == "error" and isinstance(value, str) and value.strip():
                detected = _detect_error_from_text_output(value)
                if detected is not None:
                    return detected
                return True

        for key in _STRUCTURED_BOOL_SUCCESS_KEYS:
            value = raw_output.get(key)
            if isinstance(value, bool):
                return not value

        for key in _STRUCTURED_STATUS_KEYS:
            status_detected = _status_indicates_error(raw_output.get(key))
            if status_detected is not None:
                return status_detected

        for key in _STRUCTURED_TEXT_ERROR_KEYS:
            value = raw_output.get(key)
            if isinstance(value, str):
                detected = _detect_error_from_text_output(value)
                if detected is not None:
                    return detected
                if key in {"error", "exception", "traceback", "failure_reason"} and value.strip():
                    return True
            elif isinstance(value, (dict, list)):
                detected = _detect_error_from_structured_output(value)
                if detected is not None:
                    return detected
                if key in {"error", "exception", "traceback"} and value:
                    return True

        for value in raw_output.values():
            detected = _detect_error_from_structured_output(value)
            if detected is True:
                return True
            if detected is False:
                saw_explicit_success = True

        if saw_explicit_success:
            return False
        return None

    if isinstance(raw_output, list):
        saw_explicit_success = False
        for item in raw_output:
            detected = _detect_error_from_structured_output(item)
            if detected is True:
                return True
            if detected is False:
                saw_explicit_success = True
        if saw_explicit_success:
            return False
        return None

    if isinstance(raw_output, str):
        return _detect_error_from_text_output(raw_output)

    return None


def _parse_json_if_possible(raw_output: Any) -> Any | None:
    return parse_json_if_possible(raw_output)


def _resolve_response_item_call_id(payload_dict: dict[str, Any], session_id: str, line: int) -> str:
    call_id = extract_non_empty_str(payload_dict, ("call_id", "id", "tool_call_id"))
    if call_id:
        return call_id
    return f"{session_id}-result-{line}"


def _resolve_web_search_call_id(payload_dict: dict[str, Any], session_id: str, line: int) -> str:
    call_id = extract_non_empty_str(payload_dict, _WEB_SEARCH_CALL_ID_KEYS)
    if call_id:
        return call_id
    return f"{session_id}-web-search-{line}"


def _build_web_search_output_payload(payload_dict: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "web_search_call"}
    for key in ("query", "status", "state", "outcome", "result_status", "message", "summary"):
        value = payload_dict.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()

    error_value = payload_dict.get("error")
    if isinstance(error_value, (str, dict, list)) and error_value:
        payload["error"] = error_value

    results = payload_dict.get("results")
    if isinstance(results, list):
        payload["result_count"] = len(results)

    return payload


def _detect_web_search_error(payload_dict: dict[str, Any]) -> bool | None:
    status = extract_non_empty_str(payload_dict, _WEB_SEARCH_STATUS_KEYS)
    if status is not None and _is_non_terminal_status(status):
        return None

    detected = _detect_error_from_structured_output(payload_dict)
    if detected is not None:
        return detected

    status_detected = _status_indicates_error(status)
    if status_detected is not None:
        return status_detected

    return False


def _extract_session_id_from_file(file_path: Path) -> str | None:
    decoder = get_json_line_decoder()
    open_mode = "rb" if decoder.read_mode == "binary" else "r"
    open_kwargs: dict[str, Any] = {} if open_mode == "rb" else {"encoding": "utf-8"}

    try:
        with open(file_path, open_mode, **open_kwargs) as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw = decoder.decode(stripped)
                except ValueError:
                    continue
                if raw.get("type") != "session_meta":
                    continue
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    continue
                session_id = payload.get("id")
                if isinstance(session_id, str) and session_id.strip():
                    return session_id.strip()
    except OSError:
        return None
    return None


def _build_message_record(
    *,
    session_id: str,
    uuid: str,
    timestamp: str,
    role: Literal["user", "assistant", "system"],
    content: str | list[dict[str, Any]],
    cwd: str | None = None,
    version: str | None = None,
    usage: dict[str, Any] | None = None,
    git_branch: str | None = None,
    user_type: str | None = None,
) -> MessageRecord:
    normalized_usage = build_usage_ir(usage)
    normalized_record = NormalizedRecordIR.model_construct(
        session_id=session_id,
        uuid=uuid,
        timestamp=timestamp,
        record_type="user" if role == "user" else "assistant",
        cwd=cwd,
        version=version,
        git_branch=git_branch,
        user_type=user_type,
        is_sidechain=False,
        message=NormalizedMessageIR.model_construct(
            role=role,
            content=content,
            usage=normalized_usage,
        ),
    )
    return normalized_record.to_message_record()


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
            if role_str in {"user", "assistant", "system"}:
                if role_str == "user":
                    normalized_role: Literal["user", "assistant", "system"] = "user"
                elif role_str == "system":
                    normalized_role = "system"
                else:
                    normalized_role = "assistant"
                user_type = None
            else:
                normalized_role = "assistant"
                user_type = f"source_role:{role_str}"
            content = _extract_text_blocks(payload_dict.get("content"))
            return _build_message_record(
                session_id=session_id,
                uuid=f"{session_id}-msg-{event.line_number}",
                timestamp=timestamp,
                role=normalized_role,
                content=content,
                user_type=user_type,
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
                parsed = _parse_json_if_possible(input_data)
                if parsed is None:
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
            call_id = _resolve_response_item_call_id(payload_dict, session_id, event.line_number)
            raw_output = payload_dict.get("output")
            parsed_output = _parse_json_if_possible(raw_output)

            detection_source: Any = parsed_output if parsed_output is not None else raw_output
            rendered_output: Any = raw_output
            if item_type == "custom_tool_call_output" and isinstance(parsed_output, dict):
                inner_output = parsed_output.get("output")
                if inner_output is not None:
                    rendered_output = inner_output
                else:
                    rendered_output = parsed_output
            elif parsed_output is not None:
                rendered_output = parsed_output

            detected = _detect_error_from_structured_output(detection_source)
            if detected is None and isinstance(raw_output, str):
                detected = _detect_error_from_text_output(raw_output)
            is_error = bool(detected) if detected is not None else False

            detection_text = (
                rendered_output
                if isinstance(rendered_output, str)
                else safe_json_dumps(rendered_output)
            )
            output_content = _normalize_tool_output_content(rendered_output)
            if output_content == "" and detection_text:
                output_content = detection_text

            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": output_content,
                "is_error": is_error,
            }
            if isinstance(payload_dict.get("name"), str) and payload_dict["name"].strip():
                block["tool_name"] = payload_dict["name"].strip()

            return _build_message_record(
                session_id=session_id,
                uuid=f"{call_id}-result",
                timestamp=timestamp,
                role="user",
                content=[block],
            )

        if item_type == "web_search_call":
            call_id = _resolve_web_search_call_id(payload_dict, session_id, event.line_number)
            is_error = _detect_web_search_error(payload_dict)
            output_payload = _build_web_search_output_payload(payload_dict)
            output_content = _normalize_tool_output_content(output_payload)
            return _build_message_record(
                session_id=session_id,
                uuid=f"{call_id}-web-search",
                timestamp=timestamp,
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "tool_name": _WEB_SEARCH_TOOL_NAME,
                        "content": output_content,
                        "is_error": is_error,
                    }
                ],
            )

        if item_type == "reasoning":
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
    file_session_id = _extract_session_id_from_file(file_path)
    if file_session_id:
        return file_session_id
    if messages:
        for message in messages:
            if message.sessionId.strip():
                return message.sessionId
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
