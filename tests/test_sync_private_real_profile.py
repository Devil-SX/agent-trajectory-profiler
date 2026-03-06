"""Local privacy-preserving sync profile smoke test."""

from __future__ import annotations

import pytest

from agent_vis.perf.sync_profiler import profile_sync_directory, resolve_private_sync_root


def test_profile_private_real_sync_root_smoke() -> None:
    root = resolve_private_sync_root()
    if not root.exists():
        pytest.skip(f"Private sync root missing: {root}")

    payload, _, _ = profile_sync_directory(root, max_files=1, top_n=1)

    assert payload["summary"]["parsed_files"] == 1
    assert payload["summary"]["total_sync_ms"] > 0
    assert payload["stage_breakdown"]
    assert payload["slow_files"]
    assert any(item["stage"] == "parse_jsonl_file_ms" for item in payload["stage_breakdown"])
