"""A complete token ledger does not establish request or human-input coverage."""

import base64
import hashlib
import json
from pathlib import Path

import pytest

from trajectory.product.contracts import Batch, SourceChunk
from trajectory.product.domain import INTERACTION_COUNTERS, Domain
from trajectory.product.semantic import SemanticStore, digest


def archive(store, ecosystem, raw):
    source = digest(ecosystem + raw.decode())
    result = store.ingest_source(
        "machine",
        SourceChunk.model_validate(
            {
                "schema_id": "trajectory-source-chunk/1",
                "mutation_id": digest("archive:" + source),
                "collector": "fixture",
                "source": source,
                "ecosystem": ecosystem,
                "generation": "first",
                "start": 0,
                "end": len(raw),
                "source_bytes": len(raw),
                "content": base64.b64encode(raw).decode(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_name": ecosystem + ".jsonl",
            }
        ),
    )
    source_value, _ = store.archive("owner", result["session_id"])
    return result["session_id"], source_value, digest("first:" + str(len(raw)))


def test_legacy_codex_missing_requests_is_unknown_in_all_session_views(tmp_path: Path):
    domain = Domain(tmp_path / "old.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)
    raw = (
        b'{"type":"session_meta","payload":{"id":"legacy","source":"vscode"}}\n'
        b'{"type":"response_item","payload":{"type":"message","role":"user",'
        b'"id":"native-user","content":[{"type":"input_text","text":"fixture input"}]}}\n'
        b'{"type":"event_msg","payload":{"type":"token_count"}}\n'
    )
    sid, source, revision = archive(store, "codex", raw)
    payload = Batch.model_validate(
        {
            "collector": "fixture",
            "source": source["source"],
            "mutation_id": digest("old-ledger"),
            "revision": 1,
            "source_bytes": len(raw),
            "read_bytes": len(raw),
            "parser_version": "sparkstead-trajectory/1",
            "records": [
                {
                    "id": digest("usage"),
                    "session": "legacy",
                    "task": "legacy-task",
                    "ecosystem": "codex",
                    "timestamp": "2026-10-18T12:00:00Z",
                    "kind": "usage",
                    "source_line": 3,
                    "input": 20,
                    "output": 3,
                    "cached": 4,
                    "input_includes_cache": True,
                }
            ],
        }
    )
    domain.ingest("machine", payload)
    # Request evidence on another source must not make this source available.
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "collector": "fixture",
                "source": "b" * 64,
                "mutation_id": digest("other-ledger"),
                "revision": 1,
                "source_bytes": 1,
                "read_bytes": 1,
                "parser_version": "sparkstead-trajectory/3",
                "records": [
                    {
                        "id": digest("other-request"),
                        "session": "other",
                        "task": "other-task",
                        "ecosystem": "codex",
                        "kind": "request",
                        "timestamp": "2026-10-18T12:00:00Z",
                        "source_line": 1,
                        "input_origin": "human",
                        "input_chars": 2,
                    }
                ],
            }
        ),
    )
    parsed = {
        "metadata": {"native_session_id": "legacy", "cwd": "/fixture/embodied"},
        "operations": [
            {
                "id": "prompt",
                "kind": "prompt",
                "text": "fixture input",
                "location": {"source_line": 2},
            },
            {"id": "reply", "kind": "llm", "location": {"source_line": 3}},
        ],
    }
    store.save_session("owner", sid, source, revision, parsed)
    analysis = store.save_analysis(
        "owner",
        sid,
        revision,
        {
            "tasks": [
                {
                    "id": "task",
                    "name": "Fixture task",
                    "parent_id": None,
                    "operation_ids": ["prompt", "reply"],
                }
            ]
        },
    )
    with domain.connect() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM events")]
    detail = store.detail("owner", sid)
    listing = next(row for row in store.sessions("owner")["sessions"] if row["id"] == sid)
    assert detail["analysis_revision"] == analysis
    assert detail["source_revision"] == revision
    coverage = detail["coverage"]["interaction_availability"]
    assert coverage == listing["interaction_availability"]
    assert coverage["available"] is False
    assert coverage["collector_parser"] == "sparkstead-trajectory/1"
    assert coverage["collection_complete"] is True
    assert coverage["request_records"] == 0
    assert any("请求交互测量" in warning for warning in detail["coverage"]["warnings"])
    for metrics in [
        detail["session"]["metrics"],
        listing["metrics"],
        *[op["metrics"] for op in detail["operations"]],
        *[task["metrics"] for task in detail["tasks"]],
    ]:
        assert all(metrics[key] is None for key in INTERACTION_COUNTERS)
    assert detail["session"]["metrics"]["calls"] == 1
    assert detail["session"]["metrics"]["recorded_tokens"] == 23
    summary = next(
        row
        for row in domain.session_summaries("owner")
        if row["record"]["source"] == source["source"]
    )
    assert summary["interaction_availability"] == coverage
    with domain.connect() as db:
        assert before == [tuple(row) for row in db.execute("SELECT * FROM events")]


@pytest.mark.parametrize("requests", [11, 45])
def test_pi_unknown_origins_preserve_known_subtotal_without_claiming_human_zero(
    tmp_path: Path, requests
):
    domain = Domain(tmp_path / "pi.db")
    domain.register("owner", "machine", "fixture")
    store = SemanticStore(domain)
    native_id = f"pi-fixture-{requests}"
    native = [{"type": "session", "id": native_id, "cwd": "/fixture/embodied"}]
    records = []
    operations = []
    for index in range(requests):
        native.append(
            {
                "type": "message",
                "id": f"u{index}",
                "message": {"role": "user", "content": [{"type": "text", "text": "fixture input"}]},
            }
        )
        records.append(
            {
                "role": "user",
                "native_id": f"u{index}",
                "event_id": f"event-{index}",
                "timestamp_ms": 1792324800000 + index,
                "source_line": index + 2,
                "input_text": "fixture input",
                "human_origin": None,
            }
        )
        operations.append(
            {"id": f"prompt-{index}", "kind": "prompt", "location": {"source_line": index + 2}}
        )
    raw = ("\n".join(json.dumps(record) for record in native) + "\n").encode()
    sid, source, revision = archive(store, "pi", raw)
    parsed = {
        "source_id": source["source"],
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "worker_version": "0.1.3",
        "recorded_measurement_schema": "trajectory.recorded-measurements/1",
        "complete_bytes": len(raw),
        "metadata": {"native_session_id": native_id, "cwd": "/fixture/embodied"},
        "source_records": records,
        "operations": operations,
        "coverage": {"quarantined_records": 0},
    }
    store.save_session("owner", sid, source, revision, parsed)
    detail = store.detail("owner", sid)
    listing = store.sessions("owner")["sessions"][0]
    coverage = detail["coverage"]["interaction_availability"]
    assert coverage == listing["interaction_availability"]
    assert coverage["available"] is True and coverage["request_records"] == requests
    for metrics in [detail["session"]["metrics"], listing["metrics"]]:
        assert metrics["human_interactions"] is None
        assert metrics["human_input_chars"] is None
        assert metrics["unknown_origin_interactions"] == requests
    assert (
        sum(op["metrics"]["unknown_origin_interactions"] for op in detail["operations"]) == requests
    )
    assert not any("请求交互测量" in warning for warning in detail["coverage"]["warnings"])


def test_legacy_request_evidence_does_not_claim_complete_collection():
    coverage = Domain.interaction_availability(
        1, {"parser": "sparkstead-trajectory/1", "read_bytes": 10, "source_bytes": 10, "errors": 0}
    )
    assert coverage["available"] is True
    assert coverage["coverage_status"] == "partial"
    assert coverage["reason"] == "request_collection_coverage_unverified"


def test_empty_current_parser_does_not_guess_observed_zero():
    coverage = Domain.interaction_availability(
        0, {"parser": "sparkstead-trajectory/3", "read_bytes": 10, "source_bytes": 10, "errors": 0}
    )
    assert coverage["available"] is False
    assert coverage["coverage_status"] == "unknown"
