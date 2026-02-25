"""
Backward-compatibility shim.

All parsing logic has moved to ``claude_vis.parsers.claude_code``.
This module re-exports every public name so that existing imports
like ``from claude_vis.parsers.session_parser import parse_jsonl_file``
continue to work.
"""

from claude_vis.exceptions import SessionParseError  # noqa: F401
from claude_vis.parsers.claude_code import (  # noqa: F401
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
