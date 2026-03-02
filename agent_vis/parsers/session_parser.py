"""
Backward-compatibility shim.

All parsing logic has moved to ``agent_vis.parsers.claude_code``.
This module re-exports every public name so that existing imports
like ``from agent_vis.parsers.session_parser import parse_jsonl_file``
continue to work.
"""

from agent_vis.exceptions import SessionParseError  # noqa: F401
from agent_vis.parsers.claude_code import (  # noqa: F401
    ClaudeCodeParser,
    calculate_session_statistics,
    extract_compact_events,
    extract_session_metadata,
    extract_subagent_sessions,
    find_session_files,
    parse_jsonl_file,
    parse_session_directory,
    parse_session_file,
)
