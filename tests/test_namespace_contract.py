"""Public namespace contract tests for the canonical package."""

import importlib
from pathlib import Path

import pytest

SYMBOL_EXPORT_MATRIX: dict[str, str] = {
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
    sorted(SYMBOL_EXPORT_MATRIX.items()),
)
def test_agent_vis_public_symbol_export(submodule: str, symbol: str) -> None:
    """Canonical namespace should expose expected public symbols."""
    module = importlib.import_module(f"agent_vis.{submodule}")
    assert hasattr(module, symbol)


def test_package_exports_parse_helpers() -> None:
    """Package-level parser exports should remain stable for callers."""
    parsers = importlib.import_module("agent_vis.parsers")

    assert parsers.parse_session_file is not None
    assert parsers.parse_session_directory is not None
    assert parsers.get_parser is not None


def test_legacy_claude_vis_namespace_removed() -> None:
    """Repository should not ship legacy namespace sources or CLI alias."""
    repo_root = Path(__file__).resolve().parents[1]

    assert not (repo_root / "claude_vis").exists()
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "claude-vis" not in pyproject
