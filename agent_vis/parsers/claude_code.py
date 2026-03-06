"""
Claude Code trajectory parser.

This module wraps the existing session parsing functions into a class-based
parser that implements the TrajectoryParser ABC, while preserving all
original logic as module-level helper functions.
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from agent_vis.exceptions import SessionParseError
from agent_vis.models import (
    BashBreakdown,
    BashCommandStats,
    CharacterBreakdown,
    CompactEvent,
    MessageRecord,
    ParsedSessionData,
    Session,
    SessionMetadata,
    SessionStatistics,
    SubagentSession,
    SubagentType,
    TimeBreakdown,
    TodoItem,
    TokenBreakdown,
    ToolCallStatistics,
    ToolErrorRecord,
    ToolGroupStatistics,
)
from agent_vis.parsers.base import TrajectoryParser
from agent_vis.parsers.canonical import (
    CanonicalEvent,
    TrajectoryEventAdapter,
    register_adapter,
)
from agent_vis.parsers.character_classifier import classify_characters
from agent_vis.parsers.decoders import get_json_line_decoder
from agent_vis.parsers.error_taxonomy import (
    ERROR_TAXONOMY_VERSION,
    classify_tool_error,
)
from agent_vis.parsers.normalization import (
    NormalizedCompactEventIR,
    NormalizedEventIR,
    NormalizedMessageIR,
    NormalizedRecordIR,
    build_usage_ir,
    coerce_timestamp,
    normalize_message_content,
)

# ---------------------------------------------------------------------------
# Module-level helper functions (private)
# ---------------------------------------------------------------------------


def _split_bash_on_operators(command_str: str) -> list[str]:
    """
    Split a shell command string on chaining operators (&&, ||, ;, |)
    while respecting single quotes, double quotes, and backtick quotes.

    Returns a list of sub-command strings.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    n = len(command_str)
    quote_char: str | None = None  # None, "'", '"', '`'

    while i < n:
        ch = command_str[i]

        # Handle escape sequences inside double quotes / unquoted
        if ch == "\\" and quote_char != "'" and i + 1 < n:
            current.append(ch)
            current.append(command_str[i + 1])
            i += 2
            continue

        # Toggle quote state
        if quote_char is None and ch in ("'", '"', "`"):
            quote_char = ch
            current.append(ch)
            i += 1
            continue
        if quote_char and ch == quote_char:
            quote_char = None
            current.append(ch)
            i += 1
            continue

        # Only split when outside quotes
        if quote_char is None:
            # Check two-char operators first: && ||
            if i + 1 < n:
                two = command_str[i : i + 2]
                if two in ("&&", "||"):
                    parts.append("".join(current))
                    current = []
                    i += 2
                    continue
            # Single-char operators: | ;
            if ch in ("|", ";"):
                parts.append("".join(current))
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    # Last segment
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    return parts


# Regex to validate that an extracted token looks like a real command name
# (starts with letter, dot, or underscore — filters out numbers, punctuation, etc.)
_CMD_NAME_RE = re.compile(r"^[a-zA-Z_.]")


def _parse_bash_sub_commands(command_str: str) -> list[str]:
    """
    Extract base command names from a Bash command string.

    Splits on shell chaining operators (&&, ||, ;, |) while respecting
    quoted strings, then extracts the first "real word" from each
    sub-command, stripping any path prefix.

    Args:
        command_str: The full shell command string.

    Returns:
        List of base command names (e.g. ['cd', 'make', 'tail']).
    """
    if not command_str or not command_str.strip():
        return []

    parts = _split_bash_on_operators(command_str)
    commands: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Tokenize on whitespace, skip env var assignments (FOO=bar)
        tokens = part.split()
        cmd_token = None
        for token in tokens:
            # Skip env var assignments like VAR=value
            if "=" in token and not token.startswith("-") and token.split("=")[0].isidentifier():
                continue
            cmd_token = token
            break

        if cmd_token:
            # Strip path prefix: /usr/bin/python -> python
            base = cmd_token.rsplit("/", 1)[-1]
            # Strip leading ./ prefix
            if base.startswith("./"):
                base = base[2:]
            # Validate it looks like a command name
            if base and _CMD_NAME_RE.match(base):
                commands.append(base)

    return commands


def _parse_tool_group(tool_name: str) -> str:
    """
    Determine the group name for a tool based on its naming convention.

    MCP tools follow the pattern ``mcp__<server_name>__<method_name>``.
    For these, the group is the server name with an " (MCP)" suffix.
    Non-MCP tools each form their own group (group name == tool name).

    Examples:
        "mcp__plugin_autochip_WaveTool__get_fst_signals" -> "WaveTool (MCP)"
        "mcp__obsidian__read_note"                       -> "obsidian (MCP)"
        "mcp__bilibili-mcp__search_video"                -> "bilibili-mcp (MCP)"
        "Bash"                                           -> "Bash"
        "Read"                                           -> "Read"
    """
    if not tool_name.startswith("mcp__"):
        return tool_name

    parts = tool_name.split("__")
    if len(parts) < 3:
        return tool_name

    server_name = parts[1]
    # Use the last segment of underscore-separated server name as display name
    # e.g. "plugin_autochip_WaveTool" -> "WaveTool"
    segments = server_name.split("_")
    display_name = segments[-1] if segments else server_name
    return f"{display_name} (MCP)"


def _has_tool_result_content(msg: MessageRecord) -> bool:
    """Check if a message contains tool_result content blocks."""
    if not msg.message or not msg.message.content:
        return False
    if isinstance(msg.message.content, list):
        for block in msg.message.content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return True
    return False


def _extract_tool_result_text(content: str | list[dict[str, Any]] | Any) -> str:
    """Normalize tool_result content into plain text for taxonomy matching."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    pieces.append(text)
                else:
                    pieces.append(json.dumps(block, ensure_ascii=False))
            else:
                pieces.append(str(block))
        return "\n".join(pieces)
    if content is None:
        return ""
    return str(content)


def _normalize_tool_result_error_flag(value: Any) -> bool | None:
    """Best-effort conversion of tool_result error flag into tri-state bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "error", "failed", "failure"}:
            return True
        if normalized in {"false", "0", "no", "ok", "success", "succeeded"}:
            return False
    return None


def _tool_error_summary(detail: str, *, max_chars: int = 160) -> str:
    """Generate a concise one-line summary for UI table display."""
    normalized = detail.strip()
    if not normalized:
        return "(empty error output)"
    return normalized.replace("\n", " ")[:max_chars]


def _tool_error_detail_snippet(detail: str, *, max_chars: int = 1200) -> str:
    """Bounded snippet for annotation payloads to avoid oversized API rows."""
    if not detail:
        return ""
    return detail[:max_chars]


def _ensure_tool_stats_bucket(
    tool_stats: dict[str, dict[str, float]], tool_name: str
) -> dict[str, float]:
    if tool_name not in tool_stats:
        tool_stats[tool_name] = {
            "count": 0,
            "tokens": 0,
            "success": 0,
            "error": 0,
            "total_latency": 0.0,
            "latency_count": 0,
        }
    return tool_stats[tool_name]


def _classify_characters(text: str) -> tuple[int, int, int, int, int]:
    """Count text characters by script family via the required native extension."""
    return classify_characters(text)


def _build_todo_items(raw_todos: Any) -> list[TodoItem] | None:
    normalized = _normalize_todos(raw_todos)
    if normalized is None:
        return None

    todos: list[TodoItem] = []
    for item in normalized:
        todos.append(
            TodoItem.model_construct(
                content=item["content"],
                status=item["status"],
                activeForm=item["activeForm"],
            )
        )
    return todos or None


def _normalize_todos(raw_todos: Any) -> list[dict[str, str]] | None:
    if not isinstance(raw_todos, list):
        return None

    todos: list[dict[str, str]] = []
    for item in raw_todos:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        status = item.get("status")
        active_form = item.get("activeForm")
        if (
            not isinstance(content, str)
            or status
            not in {
                "pending",
                "in_progress",
                "completed",
            }
            or not isinstance(active_form, str)
        ):
            continue
        todos.append(
            {
                "content": content,
                "status": status,
                "activeForm": active_form,
            }
        )
    return todos or None


def _normalize_thinking_metadata(raw_metadata: Any) -> dict[str, Any] | None:
    if not isinstance(raw_metadata, dict):
        return None
    max_thinking_tokens = raw_metadata.get("maxThinkingTokens")
    if isinstance(max_thinking_tokens, int):
        return {"maxThinkingTokens": max_thinking_tokens}
    return {}


def _normalize_claude_record(
    raw: dict[str, Any],
    *,
    line_number: int,
    timestamp: str | None = None,
) -> NormalizedRecordIR | None:
    message_payload = raw.get("message")
    raw_type = raw.get("type")
    raw_role = message_payload.get("role") if isinstance(message_payload, dict) else None
    role = _coerce_claude_role(raw_role, raw_type)
    record_type = _coerce_claude_record_type(raw_type, role)

    session_id = raw.get("sessionId")
    uuid = raw.get("uuid")
    resolved_timestamp = timestamp or coerce_timestamp(raw.get("timestamp"), line_number)
    if not isinstance(session_id, str) or not isinstance(uuid, str) or not resolved_timestamp:
        return None

    thinking_metadata = _normalize_thinking_metadata(raw.get("thinkingMetadata"))
    snapshot = raw.get("snapshot")

    return NormalizedRecordIR.model_construct(
        session_id=session_id,
        uuid=uuid,
        timestamp=resolved_timestamp,
        record_type=record_type,
        parent_uuid=raw.get("parentUuid") if isinstance(raw.get("parentUuid"), str) else None,
        user_type=raw.get("userType") if isinstance(raw.get("userType"), str) else None,
        cwd=raw.get("cwd") if isinstance(raw.get("cwd"), str) else None,
        version=raw.get("version") if isinstance(raw.get("version"), str) else None,
        git_branch=raw.get("gitBranch") if isinstance(raw.get("gitBranch"), str) else None,
        is_sidechain=(raw.get("isSidechain") if isinstance(raw.get("isSidechain"), bool) else None),
        agent_id=raw.get("agentId") if isinstance(raw.get("agentId"), str) else None,
        message=_normalize_claude_message(message_payload, role),
        is_meta=raw.get("isMeta") if isinstance(raw.get("isMeta"), bool) else None,
        is_snapshot_update=(
            raw.get("isSnapshotUpdate") if isinstance(raw.get("isSnapshotUpdate"), bool) else None
        ),
        thinking_metadata=thinking_metadata,
        todos=_normalize_todos(raw.get("todos")),
        permission_mode=(
            raw.get("permissionMode") if isinstance(raw.get("permissionMode"), str) else None
        ),
        snapshot=snapshot if isinstance(snapshot, dict) else None,
        message_id=raw.get("messageId") if isinstance(raw.get("messageId"), str) else None,
        summary=raw.get("summary") if isinstance(raw.get("summary"), str) else None,
        leaf_uuid=raw.get("leafUuid") if isinstance(raw.get("leafUuid"), str) else None,
    )


def normalize_claude_event(raw: dict[str, Any], *, line_number: int) -> NormalizedEventIR | None:
    raw_type = raw.get("type")
    event_kind = str(raw_type or "message")
    actor = raw_type if isinstance(raw_type, str) else None
    timestamp = coerce_timestamp(raw.get("timestamp"), line_number)

    compact_event = None
    if raw.get("subtype") == "compact_boundary":
        compact_metadata = raw.get("compactMetadata", {})
        compact_event = NormalizedCompactEventIR(
            timestamp=timestamp,
            trigger=(
                compact_metadata.get("trigger", "unknown")
                if isinstance(compact_metadata, dict)
                else "unknown"
            ),
            pre_tokens=(
                compact_metadata.get("preTokens", 0) if isinstance(compact_metadata, dict) else 0
            ),
        )

    record = _normalize_claude_record(raw, line_number=line_number, timestamp=timestamp)
    if record is None and compact_event is None:
        return None

    return NormalizedEventIR(
        event_kind=event_kind,
        timestamp=timestamp,
        actor=actor,
        record=record,
        compact_event=compact_event,
    )


def _claude_raw_event_to_message(
    raw: dict[str, Any],
    *,
    line_number: int,
    timestamp: str | None = None,
) -> MessageRecord | None:
    normalized = _normalize_claude_record(raw, line_number=line_number, timestamp=timestamp)
    if normalized is None:
        return None
    return normalized.to_message_record()


def iter_claude_normalized_events(
    file_path: Path,
    *,
    decoder_name: str | None = None,
) -> list[NormalizedEventIR]:
    """Read one Claude JSONL file into staged normalized events."""
    decoder = get_json_line_decoder(decoder_name)
    normalized_events: list[NormalizedEventIR] = []

    try:
        open_kwargs: dict[str, Any] = {}
        mode = "rb" if decoder.read_mode == "binary" else "r"
        if decoder.read_mode == "text":
            open_kwargs["encoding"] = "utf-8"
        with open(file_path, mode, **open_kwargs) as handle:
            for line_number, line in enumerate(handle, 1):
                if not line or line.isspace():
                    continue
                try:
                    data = decoder.decode(line)
                except ValueError as exc:
                    raise SessionParseError(
                        f"Invalid JSON at {file_path}:{line_number}: {exc}"
                    ) from exc

                if not isinstance(data, dict):
                    continue

                normalized_event = normalize_claude_event(data, line_number=line_number)
                if normalized_event is not None:
                    normalized_events.append(normalized_event)
    except FileNotFoundError as exc:
        raise SessionParseError(f"Session file not found: {file_path}") from exc
    except OSError as exc:
        raise SessionParseError(f"Error reading file {file_path}: {exc}") from exc

    return normalized_events


def parse_jsonl_file_with_compact_events(
    file_path: Path,
    *,
    decoder_name: str | None = None,
) -> tuple[list[MessageRecord], list[CompactEvent]]:
    """Parse one JSONL file into messages and compact events via staged parser passes."""
    messages: list[MessageRecord] = []
    compact_events: list[CompactEvent] = []

    for event in iter_claude_normalized_events(file_path, decoder_name=decoder_name):
        if event.compact_event is not None:
            compact_events.append(event.compact_event.to_compact_event())
        message = event.to_message_record()
        if message is not None:
            messages.append(message)

    return messages, compact_events


_CLAUDE_RECORD_TYPES = {"user", "assistant", "file-history-snapshot", "summary"}
_CLAUDE_MESSAGE_ROLES = {"user", "assistant", "system"}


def _coerce_claude_role(raw_role: Any, raw_type: Any) -> Literal["user", "assistant", "system"]:
    if isinstance(raw_role, str):
        normalized_role = raw_role.strip().lower()
        if normalized_role == "user":
            return "user"
        if normalized_role == "assistant":
            return "assistant"
        if normalized_role == "system":
            return "system"
    if raw_type == "user":
        return "user"
    return "assistant"


def _coerce_claude_record_type(
    raw_type: Any, role: Literal["user", "assistant", "system"]
) -> Literal["user", "assistant", "file-history-snapshot", "summary"]:
    if isinstance(raw_type, str) and raw_type in _CLAUDE_RECORD_TYPES:
        if raw_type == "user":
            return "user"
        if raw_type == "assistant":
            return "assistant"
        if raw_type == "file-history-snapshot":
            return "file-history-snapshot"
        return "summary"
    return "user" if role == "user" else "assistant"


def _normalize_claude_message(
    raw_message: Any, role: Literal["user", "assistant", "system"]
) -> NormalizedMessageIR | None:
    if not isinstance(raw_message, dict):
        return None

    model = raw_message.get("model")
    msg_id = raw_message.get("id")
    msg_type = raw_message.get("type")
    stop_reason = raw_message.get("stop_reason")
    stop_sequence = raw_message.get("stop_sequence")

    return NormalizedMessageIR.model_construct(
        role=role,
        content=normalize_message_content(raw_message.get("content"), text_only=False),
        model=model if isinstance(model, str) else None,
        id=msg_id if isinstance(msg_id, str) else None,
        type=msg_type if isinstance(msg_type, str) else None,
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        stop_sequence=stop_sequence if isinstance(stop_sequence, str) else None,
        usage=build_usage_ir(raw_message.get("usage")),
    )


# ---------------------------------------------------------------------------
# Public module-level functions (backward compatibility)
# ---------------------------------------------------------------------------


@register_adapter
class ClaudeCodeEventAdapter(TrajectoryEventAdapter):
    """Canonical conversion adapter for Claude Code source events."""

    ecosystem_name = "claude_code"

    def to_canonical_event(
        self, raw_event: dict[str, Any], *, source_path: Path, line_number: int
    ) -> CanonicalEvent | None:
        normalized = normalize_claude_event(raw_event, line_number=line_number)
        timestamp = (
            normalized.timestamp
            if normalized is not None
            else coerce_timestamp(raw_event.get("timestamp"), line_number)
        )
        event_kind = (
            normalized.event_kind
            if normalized is not None
            else str(raw_event.get("type") or "message")
        )
        actor = (
            normalized.actor
            if normalized is not None
            else (raw_event.get("type") if isinstance(raw_event.get("type"), str) else None)
        )

        return CanonicalEvent(
            ecosystem=self.ecosystem_name,
            source_path=str(source_path),
            line_number=line_number,
            event_kind=event_kind,
            timestamp=timestamp,
            actor=actor,
            payload=raw_event,
        )

    def canonical_to_message(self, event: CanonicalEvent) -> MessageRecord | None:
        normalized = normalize_claude_event(event.payload, line_number=event.line_number)
        if normalized is None:
            return None
        return normalized.to_message_record()


def parse_jsonl_file(file_path: Path) -> list[MessageRecord]:
    """
    Parse a JSONL session file into MessageRecord objects.

    Args:
        file_path: Path to the .jsonl session file

    Returns:
        List of MessageRecord objects

    Raises:
        SessionParseError: If the file cannot be parsed
    """
    messages, _ = parse_jsonl_file_with_compact_events(file_path)
    return messages


def extract_session_metadata(
    messages: list[MessageRecord], session_id: str, file_path: Path
) -> SessionMetadata:
    """
    Extract metadata from session messages.

    Args:
        messages: List of message records
        session_id: Session identifier
        file_path: Path to the session file

    Returns:
        SessionMetadata object
    """
    if not messages:
        raise SessionParseError("Cannot extract metadata from empty message list")

    first_msg = messages[0]
    last_msg = messages[-1]

    # Extract project path from cwd if available
    project_path = first_msg.cwd or str(file_path.parent)

    # Calculate total tokens
    total_tokens = 0
    for msg in messages:
        if msg.message and msg.message.usage:
            total_tokens += msg.message.usage.total_tokens

    return SessionMetadata(
        session_id=session_id,
        physical_session_id=session_id,
        logical_session_id=session_id,
        project_path=project_path,
        git_branch=first_msg.gitBranch,
        version=first_msg.version or "unknown",
        created_at=first_msg.parsed_timestamp,
        updated_at=last_msg.parsed_timestamp,
        total_messages=len(messages),
        total_tokens=total_tokens,
        user_type=first_msg.userType,
    )


def extract_subagent_sessions(messages: list[MessageRecord]) -> list[SubagentSession]:
    """
    Extract and group subagent sessions from messages.

    Subagent sessions are identified by the agentId field and grouped together.
    This function analyzes the messages to find all subagent invocations and
    group them into separate SubagentSession objects.

    Args:
        messages: List of all message records

    Returns:
        List of SubagentSession objects
    """
    # Group messages by agent_id
    agent_messages: dict[str, list[MessageRecord]] = {}

    for msg in messages:
        if msg.is_subagent_message and msg.agentId:
            if msg.agentId not in agent_messages:
                agent_messages[msg.agentId] = []
            agent_messages[msg.agentId].append(msg)

    # Create SubagentSession objects
    subagent_sessions: list[SubagentSession] = []

    for agent_id, agent_msgs in agent_messages.items():
        if not agent_msgs:
            continue

        # Sort messages by timestamp
        agent_msgs.sort(key=lambda m: m.parsed_timestamp)

        # Determine agent type from context (this could be enhanced with more heuristics)
        agent_type = SubagentType.OTHER

        # Find parent message uuid (the message that spawned this subagent)
        parent_uuid = agent_msgs[0].parentUuid or ""

        subagent_session = SubagentSession(
            agent_id=agent_id,
            agent_type=agent_type,
            messages=agent_msgs,
            start_time=agent_msgs[0].parsed_timestamp,
            end_time=agent_msgs[-1].parsed_timestamp if len(agent_msgs) > 1 else None,
            parent_message_uuid=parent_uuid,
        )

        subagent_sessions.append(subagent_session)

    return subagent_sessions


def calculate_session_statistics(
    messages: list[MessageRecord],
    *,
    inactivity_threshold: float = 1800.0,
    model_timeout_threshold: float = 600.0,
    trajectory_file_size_bytes: int = 0,
    precomputed_subagent_sessions: list[SubagentSession] | None = None,
) -> SessionStatistics:
    """
    Calculate comprehensive statistics for a session.

    This function analyzes all messages in a session to provide detailed statistics including:
    - Message counts by role (user, assistant, system)
    - Token usage breakdown (input, output, cache)
    - Tool call statistics with success/error tracking and per-tool latency
    - Subagent invocation tracking by type
    - Session duration and timestamps
    - Time breakdown (model / tool / user)
    - Token breakdown (input / output / cache percentages)

    Args:
        messages: List of message records

    Returns:
        SessionStatistics object with comprehensive metrics
    """
    user_count = 0
    assistant_count = 0
    system_count = 0

    total_tokens = 0
    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    # Enhanced tool tracking: tool_name -> {count, tokens, success, error, total_latency}
    tool_stats: dict[str, dict[str, float]] = {}
    # Map tool_use_id to (tool_name, timestamp) for result tracking and latency
    tool_use_map: dict[str, tuple[str, datetime]] = {}
    # Track results that have no preceding tool_use block in the stream.
    implicit_tool_result_keys: set[str] = set()
    implicit_tool_result_counter = 0
    tool_error_records: list[ToolErrorRecord] = []
    tool_error_category_counts: Counter[str] = Counter()

    # Bash breakdown accumulators
    bash_command_counts: Counter[str] = Counter()
    bash_command_latency: Counter[str] = Counter()  # total latency per command (distributed)
    bash_command_output_chars: Counter[str] = Counter()  # total output chars per command
    bash_commands_per_call: list[int] = []
    # Map tool_use_id -> list of sub-command names (for distributing latency/output on result)
    bash_sub_cmds_map: dict[str, list[str]] = {}

    first_time: datetime | None = None
    last_time: datetime | None = None

    # Time attribution accumulators
    # Gaps exceeding the inactivity threshold are classified as "inactive"
    # (user closed app, sleeping, AFK) rather than model/tool/user time.
    total_model_time = 0.0
    total_tool_time = 0.0
    total_user_time = 0.0
    total_inactive_time = 0.0
    # Count genuine user interactions (user messages that are NOT tool_results)
    user_interaction_count = 0
    model_timeout_count = 0
    prev_timestamp: datetime | None = None
    user_chars = 0
    model_chars = 0
    tool_chars = 0
    cjk_chars = 0
    latin_chars = 0
    digit_chars = 0
    whitespace_chars = 0
    other_chars = 0

    for msg in messages:
        message = msg.message
        content = message.content if message is not None else None
        usage = message.usage if message is not None else None
        is_user_message = msg.is_user_message
        is_assistant_message = msg.is_assistant_message
        timestamp = msg.parsed_timestamp
        has_tool_result_content = False

        # Track timestamps
        if first_time is None or timestamp < first_time:
            first_time = timestamp
        if last_time is None or timestamp > last_time:
            last_time = timestamp

        # Count tokens
        if usage is not None:
            total_input_tokens += usage.input_tokens
            total_output_tokens += usage.output_tokens
            total_tokens += usage.total_tokens

            if usage.cache_read_input_tokens:
                cache_read_tokens += usage.cache_read_input_tokens
            if usage.cache_creation_input_tokens:
                cache_creation_tokens += usage.cache_creation_input_tokens

        # Process message content for tool calls, results, and character counts.
        if isinstance(content, list):
            for content_block in content:
                if not isinstance(content_block, dict):
                    continue

                block_type = content_block.get("type")

                # Track tool_use blocks
                if block_type == "tool_use":
                    tool_name = str(content_block.get("name", "unknown"))
                    raw_tool_id = content_block.get("id", "")
                    tool_id = str(raw_tool_id) if raw_tool_id is not None else ""

                    bucket = _ensure_tool_stats_bucket(tool_stats, tool_name)
                    bucket["count"] += 1
                    tool_use_map[tool_id] = (tool_name, timestamp)

                    # Bash breakdown: extract sub-commands
                    if tool_name == "Bash":
                        cmd_str = content_block.get("input", {}).get("command", "")
                        sub_cmds = _parse_bash_sub_commands(cmd_str)
                        bash_commands_per_call.append(len(sub_cmds))
                        for cmd in sub_cmds:
                            bash_command_counts[cmd] += 1
                        if sub_cmds:
                            bash_sub_cmds_map[tool_id] = sub_cmds

                    # Add token cost for this tool call (if available)
                    if usage is not None:
                        bucket["tokens"] += usage.total_tokens

                # Track tool_result blocks for success/error counting and latency
                elif block_type == "tool_result":
                    has_tool_result_content = True
                    raw_tool_use_id = content_block.get("tool_use_id", "")
                    tool_use_id = str(raw_tool_use_id) if raw_tool_use_id is not None else ""
                    is_error = _normalize_tool_result_error_flag(
                        content_block.get("is_error", False)
                    )
                    result_text = _extract_tool_result_text(content_block.get("content", ""))

                    use_timestamp: datetime | None = None
                    if tool_use_id in tool_use_map:
                        tool_name, use_timestamp = tool_use_map[tool_use_id]
                    else:
                        raw_tool_name = content_block.get("tool_name")
                        if isinstance(raw_tool_name, str) and raw_tool_name.strip():
                            tool_name = raw_tool_name.strip()
                        else:
                            tool_name = "unknown"
                        implicit_key = (
                            tool_use_id or f"anon:{msg.uuid}:{implicit_tool_result_counter}"
                        )
                        implicit_tool_result_counter += 1
                        dedupe_key = f"{tool_name}:{implicit_key}"
                        if dedupe_key not in implicit_tool_result_keys:
                            implicit_tool_result_keys.add(dedupe_key)
                            _ensure_tool_stats_bucket(tool_stats, tool_name)["count"] += 1

                    bucket = _ensure_tool_stats_bucket(tool_stats, tool_name)
                    if is_error is True:
                        bucket["error"] += 1
                        classification = classify_tool_error(result_text)
                        tool_error_category_counts[classification.category] += 1
                        summary = _tool_error_summary(result_text)
                        detail_snippet = _tool_error_detail_snippet(result_text)
                        tool_error_records.append(
                            ToolErrorRecord(
                                timestamp=timestamp.isoformat(),
                                tool_name=tool_name,
                                tool_call_id=tool_use_id or None,
                                category=classification.category,
                                matched_rule=classification.rule_id,
                                summary=summary,
                                preview=summary,
                                detail_snippet=detail_snippet,
                                detail=result_text,
                            )
                        )
                    elif is_error is False:
                        bucket["success"] += 1

                    if result_text:
                        (
                            cjk_delta,
                            latin_delta,
                            digit_delta,
                            whitespace_delta,
                            other_delta,
                        ) = _classify_characters(result_text)
                        tool_chars += len(result_text)
                        cjk_chars += cjk_delta
                        latin_chars += latin_delta
                        digit_chars += digit_delta
                        whitespace_chars += whitespace_delta
                        other_chars += other_delta

                    if use_timestamp is not None:
                        # Compute per-tool latency when matching tool_use exists.
                        latency = (timestamp - use_timestamp).total_seconds()
                        if latency >= 0:
                            bucket["total_latency"] += latency
                            bucket["latency_count"] += 1

                            # Distribute Bash latency equally among sub-commands.
                            if tool_name == "Bash" and tool_use_id in bash_sub_cmds_map:
                                sub_cmds = bash_sub_cmds_map[tool_use_id]
                                if sub_cmds:
                                    per_cmd = latency / len(sub_cmds)
                                    for cmd in sub_cmds:
                                        bash_command_latency[cmd] += per_cmd

                    # Distribute Bash result output chars among sub-commands.
                    if tool_name == "Bash" and tool_use_id in bash_sub_cmds_map:
                        sub_cmds = bash_sub_cmds_map[tool_use_id]
                        if sub_cmds:
                            result_content = content_block.get("content", "")
                            if isinstance(result_content, str):
                                result_chars = len(result_content)
                            elif isinstance(result_content, list):
                                result_chars = sum(
                                    (
                                        len(block.get("text", ""))
                                        if isinstance(block, dict)
                                        else len(str(block))
                                    )
                                    for block in result_content
                                )
                            else:
                                result_chars = 0
                            per_cmd_chars = result_chars // len(sub_cmds)
                            for cmd in sub_cmds:
                                bash_command_output_chars[cmd] += per_cmd_chars

                elif block_type in ("text", "thinking"):
                    text_value = (
                        content_block.get("thinking")
                        if block_type == "thinking"
                        else content_block.get("text")
                    )
                    if isinstance(text_value, str) and text_value:
                        (
                            cjk_delta,
                            latin_delta,
                            digit_delta,
                            whitespace_delta,
                            other_delta,
                        ) = _classify_characters(text_value)
                        if is_assistant_message:
                            model_chars += len(text_value)
                        elif is_user_message:
                            user_chars += len(text_value)
                        cjk_chars += cjk_delta
                        latin_chars += latin_delta
                        digit_chars += digit_delta
                        whitespace_chars += whitespace_delta
                        other_chars += other_delta
        elif isinstance(content, str) and content:
            (
                cjk_delta,
                latin_delta,
                digit_delta,
                whitespace_delta,
                other_delta,
            ) = _classify_characters(content)
            if is_assistant_message:
                model_chars += len(content)
            elif is_user_message:
                user_chars += len(content)
            cjk_chars += cjk_delta
            latin_chars += latin_delta
            digit_chars += digit_delta
            whitespace_chars += whitespace_delta
            other_chars += other_delta

        # Count message types
        if is_user_message:
            user_count += 1
            if not has_tool_result_content:
                user_interaction_count += 1
        elif is_assistant_message:
            assistant_count += 1
        else:
            system_count += 1

        # Time attribution: compute gap from previous message
        if prev_timestamp is not None:
            gap = (timestamp - prev_timestamp).total_seconds()
            if gap >= 0:
                if gap > inactivity_threshold:
                    # Gap exceeds threshold -> inactive (app closed, sleeping, AFK)
                    total_inactive_time += gap
                elif is_assistant_message:
                    # Gap before assistant message -> model inference time
                    total_model_time += gap
                    if gap > model_timeout_threshold:
                        model_timeout_count += 1
                elif is_user_message and has_tool_result_content:
                    # Gap before user message with tool_result -> tool execution time
                    total_tool_time += gap
                elif is_user_message:
                    # Gap before user message without tool_result -> user idle time
                    total_user_time += gap
        prev_timestamp = timestamp

    # Convert tool stats to ToolCallStatistics objects
    tool_call_list = []
    for tool_name, stats in tool_stats.items():
        latency_count = int(stats["latency_count"])
        total_latency = stats["total_latency"]
        avg_latency = total_latency / latency_count if latency_count > 0 else 0.0
        tool_call_list.append(
            ToolCallStatistics(
                tool_name=tool_name,
                count=int(stats["count"]),
                total_tokens=int(stats["tokens"]),
                success_count=int(stats["success"]),
                error_count=int(stats["error"]),
                total_latency_seconds=round(total_latency, 3),
                avg_latency_seconds=round(avg_latency, 3),
                tool_group=_parse_tool_group(tool_name),
            )
        )

    # Sort by count descending for easier consumption
    tool_call_list.sort(key=lambda x: x.count, reverse=True)

    # Build tool group statistics by aggregating tools that share a group
    group_agg: dict[str, dict] = {}
    for tc in tool_call_list:
        group_name = tc.tool_group
        if group_name not in group_agg:
            group_agg[group_name] = {
                "count": 0,
                "tokens": 0,
                "success": 0,
                "error": 0,
                "total_latency": 0.0,
                "latency_count": 0,
                "tools": [],
            }
        ga = group_agg[group_name]
        ga["count"] += tc.count
        ga["tokens"] += tc.total_tokens
        ga["success"] += tc.success_count
        ga["error"] += tc.error_count
        ga["total_latency"] += tc.total_latency_seconds
        if tc.avg_latency_seconds > 0:
            ga["latency_count"] += tc.count  # weight by call count
        ga["tools"].append(tc.tool_name)

    tool_group_list = []
    for group_name, ga in group_agg.items():
        total_lat = ga["total_latency"]
        tool_group_list.append(
            ToolGroupStatistics(
                group_name=group_name,
                count=ga["count"],
                total_tokens=ga["tokens"],
                success_count=ga["success"],
                error_count=ga["error"],
                total_latency_seconds=round(total_lat, 3),
                avg_latency_seconds=round(total_lat / ga["count"], 3) if ga["count"] > 0 else 0.0,
                tool_count=len(ga["tools"]),
                tools=ga["tools"],
            )
        )
    tool_group_list.sort(key=lambda x: x.count, reverse=True)

    # Extract subagent sessions and count by type
    subagent_sessions_list = (
        precomputed_subagent_sessions
        if precomputed_subagent_sessions is not None
        else extract_subagent_sessions(messages)
    )
    subagent_type_counts: dict[str, int] = {}

    for subagent in subagent_sessions_list:
        agent_type_str = subagent.agent_type.value
        subagent_type_counts[agent_type_str] = subagent_type_counts.get(agent_type_str, 0) + 1

    # Calculate duration
    duration_seconds = None
    if first_time and last_time:
        duration_seconds = (last_time - first_time).total_seconds()

    # Build TimeBreakdown
    # Percentages are computed over active time only (excluding inactive gaps).
    # Inactive time is reported separately so users see both the active breakdown
    # and how much of the session span was inactive (app closed / AFK).
    total_active_time = total_model_time + total_tool_time + total_user_time
    total_span_time = total_active_time + total_inactive_time
    active_hours = total_active_time / 3600.0
    interactions_per_hour = (
        round(user_interaction_count / active_hours, 1) if active_hours > 0 else 0.0
    )
    time_breakdown = None
    if total_span_time > 0:
        time_breakdown = TimeBreakdown(
            total_model_time_seconds=round(total_model_time, 2),
            total_tool_time_seconds=round(total_tool_time, 2),
            total_user_time_seconds=round(total_user_time, 2),
            total_inactive_time_seconds=round(total_inactive_time, 2),
            total_active_time_seconds=round(total_active_time, 2),
            model_time_percent=(
                round(total_model_time / total_active_time * 100, 1)
                if total_active_time > 0
                else 0.0
            ),
            tool_time_percent=(
                round(total_tool_time / total_active_time * 100, 1)
                if total_active_time > 0
                else 0.0
            ),
            user_time_percent=(
                round(total_user_time / total_active_time * 100, 1)
                if total_active_time > 0
                else 0.0
            ),
            inactive_time_percent=round(total_inactive_time / total_span_time * 100, 1),
            active_time_ratio=round(total_active_time / total_span_time, 4),
            inactivity_threshold_seconds=inactivity_threshold,
            user_interaction_count=user_interaction_count,
            interactions_per_hour=interactions_per_hour,
            model_timeout_count=model_timeout_count,
            model_timeout_threshold_seconds=model_timeout_threshold,
        )

    # Build TokenBreakdown
    # Use comprehensive total including cache tokens as denominator so all % sum to 100
    token_breakdown = None
    all_tokens = (
        total_input_tokens + total_output_tokens + cache_read_tokens + cache_creation_tokens
    )
    if all_tokens > 0:
        token_breakdown = TokenBreakdown(
            input_percent=round(total_input_tokens / all_tokens * 100, 1),
            output_percent=round(total_output_tokens / all_tokens * 100, 1),
            cache_read_percent=(
                round(cache_read_tokens / all_tokens * 100, 1) if cache_read_tokens else 0.0
            ),
            cache_creation_percent=(
                round(cache_creation_tokens / all_tokens * 100, 1) if cache_creation_tokens else 0.0
            ),
        )

    # Build BashBreakdown
    bash_breakdown = None
    if bash_commands_per_call:
        total_bash_calls = len(bash_commands_per_call)
        total_sub = sum(bash_commands_per_call)
        avg_per_call = round(total_sub / total_bash_calls, 2) if total_bash_calls > 0 else 0.0

        # Distribution: count of calls with N sub-commands
        dist: Counter[int] = Counter(bash_commands_per_call)

        # Top commands sorted by count desc, with latency and output chars
        sorted_cmds = [
            BashCommandStats(
                command_name=name,
                count=cnt,
                total_latency_seconds=round(bash_command_latency.get(name, 0.0), 2),
                avg_latency_seconds=(
                    round(bash_command_latency.get(name, 0.0) / cnt, 2) if cnt > 0 else 0.0
                ),
                total_output_chars=bash_command_output_chars.get(name, 0),
                avg_output_chars=(
                    round(bash_command_output_chars.get(name, 0) / cnt, 2) if cnt > 0 else 0.0
                ),
            )
            for name, cnt in bash_command_counts.most_common()
        ]

        bash_breakdown = BashBreakdown(
            total_calls=total_bash_calls,
            total_sub_commands=total_sub,
            avg_commands_per_call=avg_per_call,
            commands_per_call_distribution=dict(sorted(dist.items())),
            command_stats=sorted_cmds,
        )

    tool_token_total = sum(int(stats["tokens"]) for stats in tool_stats.values())
    user_yield_ratio_tokens = None
    if total_input_tokens > 0:
        user_yield_ratio_tokens = (total_output_tokens + tool_token_total) / total_input_tokens

    user_yield_ratio_chars = None
    if user_chars > 0:
        user_yield_ratio_chars = (model_chars + tool_chars) / user_chars

    avg_tokens_per_second = None
    read_tokens_per_second = None
    output_tokens_per_second = None
    cache_tokens_per_second = None
    cache_read_tokens_per_second = None
    cache_creation_tokens_per_second = None
    if total_model_time > 0:
        avg_tokens_per_second = total_tokens / total_model_time
        read_tokens_per_second = total_input_tokens / total_model_time
        output_tokens_per_second = total_output_tokens / total_model_time
        cache_read_tokens_per_second = cache_read_tokens / total_model_time
        cache_creation_tokens_per_second = cache_creation_tokens / total_model_time
        cache_tokens_per_second = (cache_read_tokens + cache_creation_tokens) / total_model_time

    return SessionStatistics(
        message_count=len(messages),
        user_message_count=user_count,
        assistant_message_count=assistant_count,
        system_message_count=system_count,
        total_tokens=total_tokens,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        trajectory_file_size_bytes=trajectory_file_size_bytes,
        character_breakdown=CharacterBreakdown(
            total_chars=user_chars + model_chars + tool_chars,
            user_chars=user_chars,
            model_chars=model_chars,
            tool_chars=tool_chars,
            cjk_chars=cjk_chars,
            latin_chars=latin_chars,
            digit_chars=digit_chars,
            whitespace_chars=whitespace_chars,
            other_chars=other_chars,
        ),
        user_yield_ratio_tokens=user_yield_ratio_tokens,
        user_yield_ratio_chars=user_yield_ratio_chars,
        avg_tokens_per_second=avg_tokens_per_second,
        read_tokens_per_second=read_tokens_per_second,
        output_tokens_per_second=output_tokens_per_second,
        cache_tokens_per_second=cache_tokens_per_second,
        cache_read_tokens_per_second=cache_read_tokens_per_second,
        cache_creation_tokens_per_second=cache_creation_tokens_per_second,
        tool_calls=tool_call_list,
        tool_groups=tool_group_list,
        total_tool_calls=sum(int(stats["count"]) for stats in tool_stats.values()),
        tool_error_records=tool_error_records,
        tool_error_category_counts=dict(tool_error_category_counts),
        error_taxonomy_version=ERROR_TAXONOMY_VERSION,
        subagent_count=len(subagent_sessions_list),
        subagent_sessions=subagent_type_counts,
        session_duration_seconds=duration_seconds,
        first_message_time=first_time,
        last_message_time=last_time,
        time_breakdown=time_breakdown,
        token_breakdown=token_breakdown,
        bash_breakdown=bash_breakdown,
    )


def extract_compact_events(file_path: Path) -> list[CompactEvent]:
    """
    Extract auto-compact (context summarization) events from a raw JSONL file.

    Compact events are system messages with ``subtype: "compact_boundary"`` and
    a ``compactMetadata`` dict containing ``trigger`` and ``preTokens``.
    These messages are not captured by the standard ``MessageRecord`` parser
    because ``type: "system"`` is not in the ``MessageType`` enum.

    Args:
        file_path: Path to the .jsonl session file.

    Returns:
        List of CompactEvent objects sorted by timestamp.
    """
    events: list[CompactEvent] = []
    decoder = get_json_line_decoder()
    open_mode = "rb" if decoder.read_mode == "binary" else "r"
    open_kwargs: dict[str, Any] = {} if open_mode == "rb" else {"encoding": "utf-8"}

    try:
        with open(file_path, open_mode, **open_kwargs) as f:
            for line in f:
                stripped = line.strip()
                compact_marker = (
                    b"compact_boundary" if isinstance(stripped, bytes) else "compact_boundary"
                )
                if not stripped or compact_marker not in stripped:
                    continue
                try:
                    data = decoder.decode(stripped)
                except ValueError:
                    continue
                if data.get("subtype") != "compact_boundary":
                    continue
                cm = data.get("compactMetadata", {})
                events.append(
                    CompactEvent(
                        timestamp=data.get("timestamp", ""),
                        trigger=cm.get("trigger", "unknown"),
                        pre_tokens=cm.get("preTokens", 0),
                    )
                )
    except OSError:
        pass
    return events


def parse_session_file(
    file_path: Path,
    *,
    inactivity_threshold: float = 1800.0,
    model_timeout_threshold: float = 600.0,
) -> Session:
    """
    Parse a single session file into a Session object.

    Args:
        file_path: Path to the .jsonl session file
        inactivity_threshold: Seconds of gap to classify as inactive.
        model_timeout_threshold: Seconds of model gap to count as timeout.

    Returns:
        Session object with complete data including subagent sessions

    Raises:
        SessionParseError: If parsing fails
    """
    # Extract session ID from filename (remove .jsonl extension)
    session_id = file_path.stem

    # Parse messages and compact events in one scan.
    messages, compact_events = parse_jsonl_file_with_compact_events(file_path)

    if not messages:
        raise SessionParseError(f"No valid messages found in {file_path}")

    # Extract metadata
    metadata = extract_session_metadata(messages, session_id, file_path)

    # Extract subagent sessions
    subagent_sessions = extract_subagent_sessions(messages)

    # Calculate statistics
    try:
        trajectory_file_size_bytes = file_path.stat().st_size
    except OSError:
        trajectory_file_size_bytes = 0

    statistics = calculate_session_statistics(
        messages,
        inactivity_threshold=inactivity_threshold,
        model_timeout_threshold=model_timeout_threshold,
        trajectory_file_size_bytes=trajectory_file_size_bytes,
        precomputed_subagent_sessions=subagent_sessions,
    )

    # Compact events were collected during the initial file scan.
    statistics.compact_count = len(compact_events)
    statistics.compact_events = compact_events

    # Create session object
    session = Session(
        metadata=metadata,
        messages=messages,
        subagent_sessions=subagent_sessions,
        statistics=statistics,
    )

    return session


def find_session_files(directory: Path) -> list[Path]:
    """
    Find all .jsonl session files in a directory recursively.

    This function searches for .jsonl files in the directory and all subdirectories.
    It excludes files in 'subagents' directories as those are handled separately.

    Args:
        directory: Path to the session directory

    Returns:
        List of Path objects for .jsonl files
    """
    if not directory.exists():
        raise SessionParseError(f"Directory does not exist: {directory}")

    if not directory.is_dir():
        raise SessionParseError(f"Path is not a directory: {directory}")

    # Find all .jsonl files recursively
    # Use rglob for recursive search
    all_jsonl_files = list(directory.rglob("*.jsonl"))

    # Filter out files in 'subagents' directories (they are handled as part of main sessions)
    # Also filter out history.jsonl which is a global history file
    session_files = [
        f for f in all_jsonl_files if "subagents" not in f.parts and f.name != "history.jsonl"
    ]

    return sorted(session_files)


def parse_session_directory(
    directory: Path,
    *,
    inactivity_threshold: float = 1800.0,
    model_timeout_threshold: float = 600.0,
) -> ParsedSessionData:
    """
    Parse all session files in a directory.

    Args:
        directory: Path to the session directory
        inactivity_threshold: Seconds of gap to classify as inactive.
        model_timeout_threshold: Seconds of model gap to count as timeout.

    Returns:
        ParsedSessionData object containing all sessions

    Raises:
        SessionParseError: If parsing fails
    """
    session_files = find_session_files(directory)

    if not session_files:
        raise SessionParseError(f"No session files found in {directory}")

    sessions: list[Session] = []
    errors: list[str] = []

    for file_path in session_files:
        try:
            session = parse_session_file(
                file_path,
                inactivity_threshold=inactivity_threshold,
                model_timeout_threshold=model_timeout_threshold,
            )
            sessions.append(session)
        except SessionParseError as e:
            errors.append(f"{file_path.name}: {e}")
            continue

    if not sessions and errors:
        raise SessionParseError("Failed to parse any sessions. Errors:\n" + "\n".join(errors))

    # Create parsed data container
    parsed_data = ParsedSessionData(
        sessions=sessions,
        source_path=str(directory),
    )

    return parsed_data


# ---------------------------------------------------------------------------
# ClaudeCodeParser class (wraps the above functions)
# ---------------------------------------------------------------------------


class ClaudeCodeParser(TrajectoryParser):
    """
    Parser for Claude Code session JSONL files.

    Wraps the module-level functions into the TrajectoryParser ABC interface.
    """

    def __init__(
        self,
        inactivity_threshold: float = 1800.0,
        model_timeout_threshold: float = 600.0,
    ) -> None:
        self.inactivity_threshold = inactivity_threshold
        self.model_timeout_threshold = model_timeout_threshold

    @property
    def ecosystem_name(self) -> str:
        return "claude_code"

    def parse_file(self, file_path: Path) -> list[MessageRecord]:
        return parse_jsonl_file(file_path)

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
        return find_session_files(directory)

    def _extract_subagent_sessions(self, messages: list[MessageRecord]) -> list[SubagentSession]:
        return extract_subagent_sessions(messages)

    def parse_session(self, file_path: Path) -> Session:
        """Override to include compact event extraction."""
        session = parse_session_file(
            file_path,
            inactivity_threshold=self.inactivity_threshold,
            model_timeout_threshold=self.model_timeout_threshold,
        )
        return session
