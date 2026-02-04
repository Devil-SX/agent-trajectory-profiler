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
    ToolCallStatistics,
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


def calculate_session_statistics(messages: list[MessageRecord]) -> SessionStatistics:
    """
    Calculate comprehensive statistics for a session.

    This function analyzes all messages in a session to provide detailed statistics including:
    - Message counts by role (user, assistant, system)
    - Token usage breakdown (input, output, cache)
    - Tool call statistics with success/error tracking
    - Subagent invocation tracking by type
    - Session duration and timestamps

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

    # Enhanced tool tracking: tool_name -> {count, tokens, success, error}
    tool_stats: dict[str, dict[str, int]] = {}
    # Map tool_use_id to tool_name for result tracking
    tool_use_map: dict[str, str] = {}
    # Track subagent sessions by agent_id to deduplicate
    subagent_sessions_map: dict[str, str] = {}

    first_time: datetime | None = None
    last_time: datetime | None = None

    for msg in messages:
        # Count message types
        if msg.is_user_message:
            user_count += 1
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
                                }

                            tool_stats[tool_name]["count"] += 1
                            tool_use_map[tool_id] = tool_name

                            # Add token cost for this tool call (if available)
                            if msg.message.usage:
                                tool_stats[tool_name]["tokens"] += msg.message.usage.total_tokens

                        # Track tool_result blocks for success/error counting
                        elif block_type == "tool_result":
                            tool_use_id = content_block.get("tool_use_id", "")
                            is_error = content_block.get("is_error", False)

                            if tool_use_id in tool_use_map:
                                tool_name = tool_use_map[tool_use_id]
                                if tool_name in tool_stats:
                                    if is_error:
                                        tool_stats[tool_name]["error"] += 1
                                    else:
                                        tool_stats[tool_name]["success"] += 1

        # Track subagent sessions
        if msg.is_subagent_message and msg.agentId:
            subagent_sessions_map[msg.agentId] = msg.agentId

    # Convert tool stats to ToolCallStatistics objects
    tool_call_list = [
        ToolCallStatistics(
            tool_name=tool_name,
            count=stats["count"],
            total_tokens=stats["tokens"],
            success_count=stats["success"],
            error_count=stats["error"],
        )
        for tool_name, stats in tool_stats.items()
    ]

    # Sort by count descending for easier consumption
    tool_call_list.sort(key=lambda x: x.count, reverse=True)

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
        total_tool_calls=sum(tool_stats[t]["count"] for t in tool_stats),
        subagent_count=len(subagent_sessions_list),
        subagent_sessions=subagent_type_counts,
        session_duration_seconds=duration_seconds,
        first_message_time=first_time,
        last_message_time=last_time,
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
    Find all .jsonl session files in a directory.

    Args:
        directory: Path to the session directory

    Returns:
        List of Path objects for .jsonl files
    """
    if not directory.exists():
        raise SessionParseError(f"Directory does not exist: {directory}")

    if not directory.is_dir():
        raise SessionParseError(f"Path is not a directory: {directory}")

    # Find all .jsonl files
    jsonl_files = list(directory.glob("*.jsonl"))

    return sorted(jsonl_files)


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
