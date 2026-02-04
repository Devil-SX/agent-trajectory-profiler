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


def calculate_session_statistics(messages: list[MessageRecord]) -> SessionStatistics:
    """
    Calculate comprehensive statistics for a session.

    Args:
        messages: List of message records

    Returns:
        SessionStatistics object
    """
    user_count = 0
    assistant_count = 0
    system_count = 0

    total_tokens = 0
    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    tool_call_counts: dict[str, int] = {}
    subagent_counts: dict[str, int] = {}

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

        # Count tool calls
        if msg.message and msg.message.content:
            if isinstance(msg.message.content, list):
                for content_block in msg.message.content:
                    if isinstance(content_block, dict) and content_block.get("type") == "tool_use":
                        tool_name = content_block.get("name", "unknown")
                        tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1

        # Count subagents
        if msg.is_subagent_message and msg.agentId:
            # Try to infer agent type from available data
            agent_type = "other"
            subagent_counts[agent_type] = subagent_counts.get(agent_type, 0) + 1

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
        total_tool_calls=sum(tool_call_counts.values()),
        subagent_count=sum(subagent_counts.values()),
        subagent_sessions=subagent_counts,
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
        Session object with complete data

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

    # Calculate statistics
    statistics = calculate_session_statistics(messages)

    # Create session object
    session = Session(
        metadata=metadata,
        messages=messages,
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
