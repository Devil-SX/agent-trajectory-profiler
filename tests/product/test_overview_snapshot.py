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
