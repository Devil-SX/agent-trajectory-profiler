"""Compatibility tests for canonical and legacy package namespaces."""

import importlib

import pytest

SYMBOL_COMPAT_MATRIX: dict[str, str] = {
    "api.app": "app",
    "api.config": "get_settings",
    "api.models": "SessionListResponse",
    "api.service": "SessionService",
    "cli.main": "main",
    "db.connection": "get_connection",
    "db.repository": "SessionRepository",
    "db.schema": "create_tables",
    "db.sync": "SyncEngine",
    "exceptions": "SessionParseError",
    "formatters.human": "format_session_stats",
    "models": "SessionStatistics",
    "parsers.base": "TrajectoryParser",
    "parsers.claude_code": "ClaudeCodeParser",
    "parsers.registry": "get_parser",
    "parsers.session_parser": "parse_session_file",
    "prompts.analyze": "build_analyze_prompt",
}


@pytest.mark.parametrize(
    ("submodule", "symbol"),
    sorted(SYMBOL_COMPAT_MATRIX.items()),
)
def test_agent_vis_symbol_matches_claude_vis(submodule: str, symbol: str) -> None:
    """Canonical namespace should expose the same symbol objects as legacy namespace."""
    canonical_module = importlib.import_module(f"agent_vis.{submodule}")
    legacy_module = importlib.import_module(f"claude_vis.{submodule}")

    assert getattr(canonical_module, symbol) is getattr(legacy_module, symbol)


def test_package_level_version_compatibility() -> None:
    """Version metadata should remain consistent between namespaces."""
    canonical_pkg = importlib.import_module("agent_vis")
    legacy_pkg = importlib.import_module("claude_vis")

    assert canonical_pkg.__version__ == legacy_pkg.__version__


def test_parsers_package_compatibility_exports() -> None:
    """Package-level parser exports should remain equivalent for migration safety."""
    canonical_parsers = importlib.import_module("agent_vis.parsers")
    legacy_parsers = importlib.import_module("claude_vis.parsers")

    assert canonical_parsers.parse_session_file is legacy_parsers.parse_session_file
    assert canonical_parsers.parse_session_directory is legacy_parsers.parse_session_directory
    assert canonical_parsers.get_parser is legacy_parsers.get_parser
