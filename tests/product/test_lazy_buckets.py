"""Repeated ledger passes allocate metrics once while retaining first-record metadata."""

import sys
import uuid
from collections import Counter

from trajectory.product.contracts import Batch
from trajectory.product.domain import Domain


def test_repeated_source_metrics_scale_with_distinct_buckets_and_keep_first_record(tmp_path):
    domain = Domain(tmp_path / "fixture.sqlite")
    domain.register("owner", "machine", "fixture")
    records = []
    for index in range(60):
        records.append(
            {
                "id": f"event-{index:010d}",
                "session": "session",
                "task": "task",
                "ecosystem": "codex",
                "kind": "usage",
                "timestamp": f"2026-10-01T00:00:{index:02d}Z",
                "source_line": index + 1,
                "model": "unpriced",
                "input": index,
                "output": 1,
                "cached": 0,
                "cache_write": 0,
            }
        )
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "collector": "fixture",
                "source": "source-0000000001",
                "revision": 1,
                "source_bytes": 100,
                "read_bytes": 100,
                "parser_version": "isolated/1",
                "records": records,
            }
        ),
    )
    allocations = Counter()

    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "bucket":
            allocations[(frame.f_locals["key"], frame.f_locals["name"])] += 1

    prior = sys.getprofile()
    try:
        sys.setprofile(profile)
        summary = domain.session_summaries("owner")
    finally:
        sys.setprofile(prior)
    # One project, one day and one source, regardless of the usage/chronological passes.
    assert sum(allocations.values()) == 3
    assert all(count == 1 for count in allocations.values())
    source = summary[0]
    # Usage dedup scans newest first; keep that first source metadata intact.
    assert source["record"]["timestamp"] == "2026-10-01T00:00:59Z"
    assert source["last_timestamp"] == "2026-10-01T00:00:59Z"
    assert source["recorded_tokens"] == sum(range(60)) + 60
    assert source["input"] == sum(range(60)) and source["calls"] == 60
    assert source["active_seconds_estimate"] == 59
    assert source["estimated_usd"] is None and source["cost_status"] == "unknown"
    task = domain.overview("owner")["tasks"][0]
    assert task["started"] == "2026-10-01T00:00:00Z"
    assert task["ended"] == "2026-10-01T00:00:59Z"
    assert task["source_line"] == 1 and task["calls"] == 60

    allocations.clear()
    try:
        sys.setprofile(profile)
        contributions = domain.source_contributions("owner", "fixture", "source-0000000001")
    finally:
        sys.setprofile(prior)
    # Source detail retains one metric per event even when active time revisits it.
    assert sum(allocations.values()) == 62
    assert all(count == 1 for count in allocations.values())
    assert len(contributions) == 60
    assert [item["record"]["source_line"] for item in contributions] == list(range(60, 0, -1))
    assert sum(item["active_seconds_estimate"] for item in contributions) == 59
    assert sum(item["input"] for item in contributions) == sum(range(60))
