"""Shared summaries must never hide a committed ledger or pricing mutation."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from trajectory.product.contracts import Batch, Price
from trajectory.product.domain import Domain


def batch(revision, tokens):
    return Batch.model_validate(
        {
            "mutation_id": uuid.uuid4().hex,
            "collector": "fixture",
            "source": "source-000000001",
            "revision": revision,
            "source_bytes": 100,
            "read_bytes": 100,
            "parser_version": "fixture/1",
            "replace": True,
            "records": [
                {
                    "id": "usage-00000000001",
                    "session": "session",
                    "task": "task",
                    "ecosystem": "codex",
                    "timestamp": "2026-10-01T00:00:00Z",
                    "kind": "usage",
                    "model": "model",
                    "source_line": 1,
                    "input": tokens,
                    "output": 0,
                    "cached": 0,
                    "cache_write": 0,
                }
            ],
        }
    )


def test_public_and_semantic_views_share_snapshot_and_refresh_committed_writes(
    tmp_path: Path, monkeypatch
):
    domain = Domain(tmp_path / "domain.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest("machine", batch(1, 10))
    original = domain._calculate_overview
    calls = []

    def calculate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(domain, "_calculate_overview", calculate)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: domain.session_summaries("owner"), range(4)))
    assert len(calls) == 1
    assert all(r[0]["input"] == 10 for r in results)
    assert "event_contributions" not in domain.overview("owner")
    assert len(calls) == 1
    domain.ingest("machine", batch(2, 20))
    assert domain.overview("owner")["projects"][0]["input"] == 20
    assert len(calls) == 2
    domain.price(
        "owner",
        Price.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "model": "model",
                "input": 1,
                "output": 1,
                "cached": 0,
                "cache_write": 0,
                "effective_from": "2026-01-01T00:00:00Z",
                "source_url": "https://example.org/price",
            }
        ),
    )
    assert domain.overview("owner")["projects"][0]["known_subtotal_usd"] == 20 / 1_000_000
    assert len(calls) == 3
    assert domain.overview("stranger")["projects"] == []


def test_two_compact_slots_isolate_global_account_and_filters(tmp_path, monkeypatch):
    domain = Domain(tmp_path / "domain.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest("machine", batch(1, 10))
    domain.register("second-owner", "second-machine", "fixture")
    domain.ingest("second-machine", batch(1, 50))
    original = domain._calculate_overview
    calls = []

    def calculate(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(domain, "_calculate_overview", calculate)
    owner = domain.overview("owner")
    global_view = domain.overview(None)
    assert owner["projects"][0]["input"] == 10
    assert global_view["projects"][0]["input"] == 60
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(domain.overview, ["owner", None] * 8))
    assert results[::2] == [owner] * 8
    assert results[1::2] == [global_view] * 8
    assert len(calls) == 2
    assert len(domain._overview_cache) == 2
    assert domain.overview(None) == global_view
    assert domain.overview("stranger")["projects"] == []
    assert len(calls) == 3
    # The third owner evicts least-recently-used owner, never leaks another owner.
    assert domain.overview(None) == global_view
    assert len(calls) == 3
    domain.overview("owner", since="2026-10-02")
    assert len(domain._overview_cache) == 2
    assert domain.overview("owner", since="2026-10-02")["projects"] == []
    domain.overview("owner", until="2026-10-01")
    assert len(domain._overview_cache) == 2
    assert all("event_contributions" not in value for value in domain._overview_cache.values())


def test_both_slots_refresh_ingest_price_and_correction(tmp_path):
    from trajectory.product.contracts import Correction

    domain = Domain(tmp_path / "domain.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest("machine", batch(1, 10))
    for owner in (None, "owner"):
        assert domain.overview(owner)["projects"][0]["input"] == 10
    domain.ingest("machine", batch(2, 20))
    for owner in (None, "owner"):
        assert domain.overview(owner)["projects"][0]["input"] == 20
    domain.price(
        "owner",
        Price.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "model": "model",
                "input": 1,
                "output": 1,
                "cached": 0,
                "cache_write": 0,
                "effective_from": "2026-01-01T00:00:00Z",
                "source_url": "https://example.org/price",
            }
        ),
    )
    for owner in (None, "owner"):
        assert domain.overview(owner)["projects"][0]["known_subtotal_usd"] == 20 / 1_000_000
    domain.correct(
        "owner",
        Correction(
            mutation_id=uuid.uuid4().hex, task="task", project="corrected", project_name="Corrected"
        ),
    )
    for owner in (None, "owner"):
        assert domain.overview(owner)["projects"][0]["id"] == "corrected"
    assert len(domain._overview_cache) == 2


def test_slots_keep_only_compact_outputs_and_source_reads_do_not_cache_raw_events(tmp_path):
    import json

    domain = Domain(tmp_path / "domain.db")
    domain.register("owner", "machine", "fixture")
    value = batch(1, 10)
    value.records[0].references = ["x" * 256_000]
    domain.ingest("machine", value)
    domain.overview("owner")
    domain.overview(None)
    before = list(domain._overview_cache)
    assert len(domain.source_contributions("owner", "fixture", "source-000000001")) == 1
    assert list(domain._overview_cache) == before
    assert len(domain._overview_cache) == 2
    encoded = json.dumps(list(domain._overview_cache.values()))
    assert "x" * 1000 not in encoded
    assert len(encoded) < 32_000
    for owner in (None, "owner"):
        direct = domain._calculate_overview(owner)
        cached = domain._snapshot(owner)
        assert {k: v for k, v in direct.items() if k != "generated_at"} == {
            k: v for k, v in cached.items() if k != "generated_at"
        }
