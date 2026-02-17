"""
Session file parser for Claude Code session JSONL files.

This module provides functionality to parse Claude Code session directories,
reading JSONL session files and extracting structured data.
"""

import json
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from claude_vis.models import (
    MessageRecord,
    ParsedSessionData,
    Session,
    SessionMetadata,
    SessionStatistics,
    SubagentSession,
    SubagentType,
    TimeBreakdown,
    TokenBreakdown,
    ToolCallStatistics,
    ToolGroupStatistics,
)


class SessionParseError(Exception):
    """Exception raised when session parsing fails."""

    pass


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
    messages: list[MessageRecord] = []

    try:
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    message = MessageRecord(**data)
                    messages.append(message)
                except json.JSONDecodeError as e:
                    raise SessionParseError(
                        f"Invalid JSON at {file_path}:{line_num}: {e}"
                    ) from e
                except ValidationError:
                    # Log validation error but continue parsing
                    # Some fields may be optional or have unknown formats
                    continue
    except FileNotFoundError as e:
        raise SessionParseError(f"Session file not found: {file_path}") from e
    except OSError as e:
        raise SessionParseError(f"Error reading file {file_path}: {e}") from e

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


def calculate_session_statistics(messages: list[MessageRecord]) -> SessionStatistics:
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
    # Track subagent sessions by agent_id to deduplicate
    subagent_sessions_map: dict[str, str] = {}

    first_time: datetime | None = None
    last_time: datetime | None = None

    # Time attribution accumulators
    # Gaps exceeding the inactivity threshold are classified as "inactive"
    # (user closed app, sleeping, AFK) rather than model/tool/user time.
    inactivity_threshold = 1800.0  # 30 minutes
    total_model_time = 0.0
    total_tool_time = 0.0
    total_user_time = 0.0
    total_inactive_time = 0.0
    # Count genuine user interactions (user messages that are NOT tool_results)
    user_interaction_count = 0
    prev_timestamp: datetime | None = None

    for msg in messages:
        # Count message types
        if msg.is_user_message:
            user_count += 1
            # Count genuine user interactions (not tool_result messages)
            if not _has_tool_result_content(msg):
                user_interaction_count += 1
        elif msg.is_assistant_message:
            assistant_count += 1
        else:
            system_count += 1

        # Track timestamps
        timestamp = msg.parsed_timestamp
        if first_time is None or timestamp < first_time:
            first_time = timestamp
        if last_time is None or timestamp > last_time:
            last_time = timestamp

        # Time attribution: compute gap from previous message
        if prev_timestamp is not None:
            gap = (timestamp - prev_timestamp).total_seconds()
            if gap >= 0:
                if gap > inactivity_threshold:
                    # Gap exceeds threshold → inactive (app closed, sleeping, AFK)
                    total_inactive_time += gap
                elif msg.is_assistant_message:
                    # Gap before assistant message → model inference time
                    total_model_time += gap
                elif msg.is_user_message and _has_tool_result_content(msg):
                    # Gap before user message with tool_result → tool execution time
                    total_tool_time += gap
                elif msg.is_user_message:
                    # Gap before user message without tool_result → user idle time
                    total_user_time += gap
        prev_timestamp = timestamp

        # Count tokens
        if msg.message and msg.message.usage:
            usage = msg.message.usage
            total_input_tokens += usage.input_tokens
            total_output_tokens += usage.output_tokens
            total_tokens += usage.total_tokens

            if usage.cache_read_input_tokens:
                cache_read_tokens += usage.cache_read_input_tokens
            if usage.cache_creation_input_tokens:
                cache_creation_tokens += usage.cache_creation_input_tokens

        # Process message content for tool calls and results
        if msg.message and msg.message.content:
            if isinstance(msg.message.content, list):
                for content_block in msg.message.content:
                    if isinstance(content_block, dict):
                        block_type = content_block.get("type")

                        # Track tool_use blocks
                        if block_type == "tool_use":
                            tool_name = content_block.get("name", "unknown")
                            tool_id = content_block.get("id", "")

                            # Initialize tool stats if not present
                            if tool_name not in tool_stats:
                                tool_stats[tool_name] = {
                                    "count": 0,
                                    "tokens": 0,
                                    "success": 0,
                                    "error": 0,
                                    "total_latency": 0.0,
                                    "latency_count": 0,
                                }

                            tool_stats[tool_name]["count"] += 1
                            tool_use_map[tool_id] = (tool_name, timestamp)

                            # Add token cost for this tool call (if available)
                            if msg.message.usage:
                                tool_stats[tool_name]["tokens"] += msg.message.usage.total_tokens

                        # Track tool_result blocks for success/error counting and latency
                        elif block_type == "tool_result":
                            tool_use_id = content_block.get("tool_use_id", "")
                            is_error = content_block.get("is_error", False)

                            if tool_use_id in tool_use_map:
                                tool_name, use_timestamp = tool_use_map[tool_use_id]
                                if tool_name in tool_stats:
                                    if is_error:
                                        tool_stats[tool_name]["error"] += 1
                                    else:
                                        tool_stats[tool_name]["success"] += 1

                                    # Compute per-tool latency
                                    latency = (timestamp - use_timestamp).total_seconds()
                                    if latency >= 0:
                                        tool_stats[tool_name]["total_latency"] += latency
                                        tool_stats[tool_name]["latency_count"] += 1

        # Track subagent sessions
        if msg.is_subagent_message and msg.agentId:
            subagent_sessions_map[msg.agentId] = msg.agentId

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
        g = tc.tool_group
        if g not in group_agg:
            group_agg[g] = {
                "count": 0, "tokens": 0, "success": 0, "error": 0,
                "total_latency": 0.0, "latency_count": 0, "tools": [],
            }
        ga = group_agg[g]
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
        lat_count = ga["latency_count"]
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
    subagent_sessions_list = extract_subagent_sessions(messages)
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
    interactions_per_hour = round(user_interaction_count / active_hours, 1) if active_hours > 0 else 0.0
    time_breakdown = None
    if total_span_time > 0:
        time_breakdown = TimeBreakdown(
            total_model_time_seconds=round(total_model_time, 2),
            total_tool_time_seconds=round(total_tool_time, 2),
            total_user_time_seconds=round(total_user_time, 2),
            total_inactive_time_seconds=round(total_inactive_time, 2),
            total_active_time_seconds=round(total_active_time, 2),
            model_time_percent=round(total_model_time / total_active_time * 100, 1) if total_active_time > 0 else 0.0,
            tool_time_percent=round(total_tool_time / total_active_time * 100, 1) if total_active_time > 0 else 0.0,
            user_time_percent=round(total_user_time / total_active_time * 100, 1) if total_active_time > 0 else 0.0,
            inactive_time_percent=round(total_inactive_time / total_span_time * 100, 1),
            inactivity_threshold_seconds=inactivity_threshold,
            user_interaction_count=user_interaction_count,
            interactions_per_hour=interactions_per_hour,
        )

    # Build TokenBreakdown
    # Use comprehensive total including cache tokens as denominator so all % sum to 100
    token_breakdown = None
    all_tokens = total_input_tokens + total_output_tokens + cache_read_tokens + cache_creation_tokens
    if all_tokens > 0:
        token_breakdown = TokenBreakdown(
            input_percent=round(total_input_tokens / all_tokens * 100, 1),
            output_percent=round(total_output_tokens / all_tokens * 100, 1),
            cache_read_percent=round(cache_read_tokens / all_tokens * 100, 1) if cache_read_tokens else 0.0,
            cache_creation_percent=round(cache_creation_tokens / all_tokens * 100, 1) if cache_creation_tokens else 0.0,
        )

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
        tool_calls=tool_call_list,
        tool_groups=tool_group_list,
        total_tool_calls=sum(int(tool_stats[t]["count"]) for t in tool_stats),
        subagent_count=len(subagent_sessions_list),
        subagent_sessions=subagent_type_counts,
        session_duration_seconds=duration_seconds,
        first_message_time=first_time,
        last_message_time=last_time,
        time_breakdown=time_breakdown,
        token_breakdown=token_breakdown,
    )


def parse_session_file(file_path: Path) -> Session:
    """
    Parse a single session file into a Session object.

    Args:
        file_path: Path to the .jsonl session file

    Returns:
        Session object with complete data including subagent sessions

    Raises:
        SessionParseError: If parsing fails
    """
    # Extract session ID from filename (remove .jsonl extension)
    session_id = file_path.stem

    # Parse messages
    messages = parse_jsonl_file(file_path)

    if not messages:
        raise SessionParseError(f"No valid messages found in {file_path}")

    # Extract metadata
    metadata = extract_session_metadata(messages, session_id, file_path)

    # Extract subagent sessions
    subagent_sessions = extract_subagent_sessions(messages)

    # Calculate statistics
    statistics = calculate_session_statistics(messages)

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
        f for f in all_jsonl_files
        if "subagents" not in f.parts and f.name != "history.jsonl"
    ]

    return sorted(session_files)


def parse_session_directory(directory: Path) -> ParsedSessionData:
    """
    Parse all session files in a directory.

    Args:
        directory: Path to the session directory

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
            session = parse_session_file(file_path)
            sessions.append(session)
        except SessionParseError as e:
            errors.append(f"{file_path.name}: {e}")
            continue

    if not sessions and errors:
        raise SessionParseError(
            "Failed to parse any sessions. Errors:\n" + "\n".join(errors)
        )

    # Create parsed data container
    parsed_data = ParsedSessionData(
        sessions=sessions,
        source_path=str(directory),
    )

    return parsed_data
