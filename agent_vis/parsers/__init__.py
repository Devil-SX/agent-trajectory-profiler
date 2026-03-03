"""Session data parsers for Agent Trajectory Profiler."""

from agent_vis.exceptions import SessionParseError
from agent_vis.parsers.base import TrajectoryParser
from agent_vis.parsers.canonical import (
    CanonicalEvent,
    CanonicalSession,
    TrajectoryEventAdapter,
    get_adapter,
    list_adapters,
    register_adapter,
)
from agent_vis.parsers.capabilities import (
    CapabilityManifest,
    get_capability_warnings,
    list_capability_manifests,
    load_capability_manifest,
    validate_registered_capabilities,
)
from agent_vis.parsers.claude_code import (
    ClaudeCodeParser,
    parse_session_directory,
    parse_session_file,
)
from agent_vis.parsers.codex import (
    CODEX_EVENT_COVERAGE_MATRIX,
    CodexParser,
    parse_codex_jsonl_file,
    parse_codex_jsonl_file_with_diagnostics,
    parse_codex_session_directory,
    parse_codex_session_file,
)
from agent_vis.parsers.registry import get_parser, list_ecosystems, register_parser

__all__ = [
    "CanonicalEvent",
    "CanonicalSession",
    "CapabilityManifest",
    "CODEX_EVENT_COVERAGE_MATRIX",
    "ClaudeCodeParser",
    "CodexParser",
    "SessionParseError",
    "TrajectoryParser",
    "TrajectoryEventAdapter",
    "get_adapter",
    "list_adapters",
    "list_capability_manifests",
    "get_parser",
    "get_capability_warnings",
    "list_ecosystems",
    "load_capability_manifest",
    "parse_codex_jsonl_file",
    "parse_codex_jsonl_file_with_diagnostics",
    "parse_codex_session_directory",
    "parse_codex_session_file",
    "parse_session_directory",
    "parse_session_file",
    "register_adapter",
    "register_parser",
    "validate_registered_capabilities",
]
