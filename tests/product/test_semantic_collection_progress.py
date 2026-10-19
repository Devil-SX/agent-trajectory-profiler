"""Price completeness and source collection completeness are independent."""

import base64
import hashlib
import uuid
from pathlib import Path

import pytest

from trajectory.product.contracts import Batch, Price, SourceChunk
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, digest


def test_fully_priced_usage_does_not_claim_complete_collection(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "collection.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)
    source_id, content = "c" * 64, b"source\n"
    sid = store.ingest_source(
        "machine",
        SourceChunk.model_validate(
            {
                "schema_id": "trajectory-source-chunk/1",
                "mutation_id": uuid.uuid4().hex,
                "collector": "fixture",
                "source": source_id,
                "ecosystem": "codex",
                "generation": "one",
                "start": 0,
                "end": len(content),
                "source_bytes": len(content),
                "content": base64.b64encode(content).decode(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ),
    )["session_id"]
    archive, _ = store.archive("owner", sid)
    revision = digest("one:" + str(len(content)))
    store.save_session(
        "owner",
        sid,
        archive,
        revision,
        {"operations": [{"id": "op", "kind": "llm", "location": {"source_line": 1}}]},
    )
    batch = Batch.model_validate(
        {
            "mutation_id": uuid.uuid4().hex,
            "collector": "fixture",
            "source": source_id,
            "revision": 1,
            "source_bytes": 100,
            "read_bytes": 40,
            "parser_version": "fixture/1",
            "records": [
                {
                    "id": "usage-record-0000001",
                    "kind": "usage",
                    "session": "session",
                    "task": "task",
                    "ecosystem": "codex",
                    "timestamp": "2026-10-19T00:00:00Z",
                    "source_line": 1,
                    "model": "example",
                    "input": 10,
                    "output": 5,
                    "cached": 0,
                    "cache_write": 0,
                }
            ],
        }
    )
    domain.ingest("machine", batch)
    domain.price(
        "owner",
        Price.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "model": "example",
                "input": 1,
                "output": 2,
                "cached": 0,
                "cache_write": 0,
                "effective_from": "2026-01-01T00:00:00Z",
                "source_url": "https://example.com/prices",
            }
        ),
    )
    store.save_analysis(
        "owner",
        sid,
        revision,
        {"tasks": [{"id": "task", "title": "执行", "parent_id": None, "operation_ids": ["op"]}]},
    )
    detail = store.detail("owner", sid)
    metrics = detail["session"]["metrics"]
    assert metrics["cost_status"] == "complete"
    assert metrics["collection_status"] == "partial"
    assert metrics["known_subtotal_usd"] == pytest.approx(0.00002)
    assert metrics["recorded_tokens"] == 15
    assert metrics["unpriced_calls"] == 0
    assert detail["coverage"]["collection"] == {
        "status": "partial",
        "read_bytes": 40,
        "source_bytes": 100,
        "parse_errors": 0,
        "unknown_events": 0,
    }
    assert detail["tasks"][0]["metrics"]["collection_status"] == "partial"
    listed = store.sessions("owner")["sessions"][0]
    assert listed["collection"]["status"] == "partial"
    assert listed["metrics"]["recorded_tokens"] == 15
    # Catching up changes collection status, without changing recorded usage or price.
    domain.ingest(
        "machine",
        batch.model_copy(
            update={
                "mutation_id": uuid.uuid4().hex,
                "revision": 2,
                "read_bytes": 100,
                "records": [],
            }
        ),
    )
    complete = store.detail("owner", sid)
    assert complete["coverage"]["collection"]["status"] == "complete"
    assert complete["session"]["metrics"]["known_subtotal_usd"] == metrics["known_subtotal_usd"]
    assert complete["session"]["metrics"]["recorded_tokens"] == 15


def test_stat_only_collection_progress_and_parser_errors_are_not_hidden(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "historical.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "collector": "fixture",
                "source": "historical-source-0001",
                "revision": 1,
                "source_bytes": 100,
                "read_bytes": 100,
                "parser_version": "fixture/1",
                "parse_errors": 2,
                "unknown_events": 3,
                "records": [
                    {
                        "id": "usage-record-0000002",
                        "kind": "usage",
                        "session": "session",
                        "task": "task",
                        "ecosystem": "codex",
                        "timestamp": "2026-10-19T00:00:00Z",
                        "source_line": 1,
                        "input": 10,
                        "output": 5,
                    }
                ],
            }
        ),
    )
    store = SemanticStore(domain)
    session = store.sessions("owner")["sessions"][0]
    detail = store.detail("owner", session["id"])
    assert detail["coverage"]["content_available"] is False
    assert detail["coverage"]["collection"] == {
        "status": "partial",
        "read_bytes": 100,
        "source_bytes": 100,
        "parse_errors": 2,
        "unknown_events": 3,
    }
    assert detail["session"]["metrics"]["collection_status"] == "partial"
    assert detail["session"]["metrics"]["recorded_tokens"] == 15
