"""Session data parsers for Claude Code Session Visualizer."""

from claude_vis.exceptions import SessionParseError
from claude_vis.parsers.base import TrajectoryParser
from claude_vis.parsers.canonical import (
    CanonicalEvent,
    CanonicalSession,
    TrajectoryEventAdapter,
    get_adapter,
    list_adapters,
    register_adapter,
)
from claude_vis.parsers.claude_code import (
    ClaudeCodeParser,
    parse_session_directory,
    parse_session_file,
)
from claude_vis.parsers.registry import get_parser, list_ecosystems, register_parser

__all__ = [
    "CanonicalEvent",
    "CanonicalSession",
    "ClaudeCodeParser",
    "SessionParseError",
    "TrajectoryParser",
    "TrajectoryEventAdapter",
    "get_adapter",
    "list_adapters",
    "get_parser",
    "list_ecosystems",
    "parse_session_directory",
    "parse_session_file",
    "register_adapter",
    "register_parser",
]
