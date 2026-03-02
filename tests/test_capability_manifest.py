"""Capability manifest validation and consistency tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_vis.parsers.capabilities import (
    CapabilityManifest,
    get_capability_warnings,
    list_capability_manifests,
    load_capability_manifest,
    validate_registered_capabilities,
)
from agent_vis.parsers.registry import list_ecosystems


def test_manifest_schema_loads_for_builtin_ecosystems() -> None:
    claude = load_capability_manifest("claude_code")
    codex = load_capability_manifest("codex")

    assert isinstance(claude, CapabilityManifest)
    assert isinstance(codex, CapabilityManifest)
    assert claude.ecosystem == "claude_code"
    assert codex.ecosystem == "codex"
    assert claude.capabilities.token_field_support.input_tokens is True
    assert codex.capabilities.event_shape_support.parent_child_session_links is True


def test_validate_registered_ecosystems_have_manifests() -> None:
    manifests = validate_registered_capabilities(list_ecosystems())
    loaded = {item.ecosystem for item in manifests}
    assert {"claude_code", "codex"}.issubset(loaded)


def test_list_capability_manifests_regression() -> None:
    manifests = list_capability_manifests()
    ecosystems = {item.ecosystem for item in manifests}
    assert "claude_code" in ecosystems
    assert "codex" in ecosystems


def test_capability_warning_consistency_check() -> None:
    warnings = get_capability_warnings(
        "claude_code",
        total_tool_calls=5,
        cache_read_tokens=100,
        cache_creation_tokens=20,
        has_tool_error_records=True,
        has_subagent_sessions=True,
    )
    assert any("subagent_events=false" in message for message in warnings)


def test_manifest_missing_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("agent_vis.parsers.capabilities._MANIFEST_DIR", tmp_path)
    with pytest.raises(ValueError, match="not found"):
        load_capability_manifest.cache_clear()
        try:
            load_capability_manifest("claude_code")
        finally:
            load_capability_manifest.cache_clear()
