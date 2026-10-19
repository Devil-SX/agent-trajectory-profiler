"""Source-bound measurements use the canonical writer, never parser estimates."""

import base64
import hashlib
from pathlib import Path

import pytest

from trajectory.product.contracts import Batch, SourceChunk
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore


def fixture(tmp_path: Path):
    domain = Domain(tmp_path / "native.sqlite")
    domain.register("owner", "machine", "collector")
    store = SemanticStore(domain)
    return domain, store


def archived(store, source="pi-source-0000000001", response="response-1", parent=None):
    source = hashlib.sha256(source.encode()).hexdigest()
    raw = b'{"type":"session","id":"fixture"}\n'
    store.ingest_source(
        "machine",
        SourceChunk.model_validate(
            {
                "schema_id": "trajectory-source-chunk/1",
                "mutation_id": "source-mutation-" + source,
                "collector": "collector",
                "source": source,
                "ecosystem": "pi",
                "generation": "generation-1",
                "start": 0,
                "end": len(raw),
                "source_bytes": len(raw),
                "content": base64.b64encode(raw).decode(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_name": source + ".jsonl",
            }
        ),
    )
    source_value, _ = store.archive("owner", store.session_id("collector", source))
    revision = hashlib.sha256(f"generation-1:{len(raw)}".encode()).hexdigest()
    parsed = {
        "source_id": source,
        "worker_version": "0.1.3",
        "recorded_measurement_schema": "trajectory.recorded-measurements/1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "complete_bytes": len(raw),
        "coverage": {"quarantined_records": 0},
        "metadata": {
            "native_session_id": source,
            "cwd": "/home/user/embodied",
            "parent_session_id": parent,
        },
        "source_records": [
            {
                "role": "user",
                "native_id": "u1",
                "event_id": "event-u1",
                "timestamp_ms": 1790848800000,
                "source_line": 1,
                "input_text": " 研究 AI + CPM\n",
                "human_origin": None,
            },
            {
                "role": "assistant",
                "native_id": "a1",
                "event_id": "event-a1",
                "timestamp_ms": 1790848801000,
                "source_line": 2,
                "provider": "fixture",
                "response_id": response,
                "model": "fixture-model",
                "measured_usage": {
                    "input": 10,
                    "output": 4,
                    "cached": 3,
                    "cache_write": 2,
                    "reasoning": 1,
                },
            },
        ],
    }
    return source_value, revision, parsed


def ingest(domain, source, revision, parsed, owner="owner"):
    with domain.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        return domain.import_native_measurements(db, owner, source, revision, parsed)


def events(domain):
    import json

    with domain.connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY id")]


def test_native_usage_exact_request_text_unknown_origin_and_replay(tmp_path):
    domain, store = fixture(tmp_path)
    source, revision, parsed = archived(store)
    domain.overview("owner")  # warm cache before the canonical ledger mutation
    result = ingest(domain, source, revision, parsed)
    assert ingest(domain, source, revision, parsed) == result
    records = events(domain)
    usage = next(r for r in records if r["kind"] == "usage")
    request = next(r for r in records if r["kind"] == "request")
    assert (usage["input"], usage["cached"], usage["cache_write"], usage["output"]) == (10, 3, 2, 4)
    assert usage["input_includes_cache"] is False
    assert request["input_origin"] == "unknown"
    assert request["input_chars"] == 8
    assert result["gaps"]["unknown_origins"] == 1
    overview = domain.overview("owner")
    assert overview["projects"][0]["input"] == 10
    assert overview["projects"][0]["unknown_origin_interactions"] == 1
    assert overview["projects"][0]["human_interactions"] == 0
    assert len(records) == 2


def test_unknown_counters_and_missing_text_are_not_zero(tmp_path):
    domain, store = fixture(tmp_path)
    source, revision, parsed = archived(store)
    parsed["source_records"][0].update(input_text=None, human_origin="human")
    parsed["source_records"][1]["measured_usage"] = {"input": 5, "output": True, "cached": -1}
    result = ingest(domain, source, revision, parsed)
    usage = next(r for r in events(domain) if r["kind"] == "usage")
    assert usage["input"] == 5
    assert all(usage[key] is None for key in ("output", "cached", "cache_write", "reasoning"))
    assert result["gaps"]["invalid_counters"] == 2
    assert result["gaps"]["missing_text"] == 1
    project = domain.overview("owner")["projects"][0]
    assert project["human_interactions"] == 1
    assert project["missing_human_input_chars"] == 1


def test_native_import_enforces_owner_archive_revision_hash_and_atomicity(tmp_path):
    domain, store = fixture(tmp_path)
    source, revision, parsed = archived(store)
    with pytest.raises(PermissionError):
        ingest(domain, source, revision, parsed, owner="other")
    with pytest.raises(ValueError, match="Source changed"):
        ingest(domain, source, "stale", parsed)
    parsed["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="archived source"):
        ingest(domain, source, revision, parsed)
    assert events(domain) == []
    with domain.connect() as db:
        with pytest.raises(ValueError, match="transaction"):
            domain.import_native_measurements(db, "owner", source, revision, parsed)


def test_provider_response_dedup_and_session_scoped_unknown_identity(tmp_path):
    domain, store = fixture(tmp_path)
    first = archived(store)
    second = archived(store, "pi-source-0000000002", parent="pi-source-0000000001")
    ingest(domain, *first)
    ingest(domain, *second)
    result = domain.overview("owner")
    assert result["coverage"]["deduplicated_usage_records"] == 1
    # Removing global response identities keeps both source-native measurements.
    for source, revision, parsed in (first, second):
        parsed["source_records"][1]["response_id"] = None
        receipt = ingest(domain, source, revision, parsed)
        assert receipt["gaps"]["scoped_consumption_identity"] == 1
    assert domain.overview("owner")["coverage"]["deduplicated_usage_records"] == 0


def test_external_and_native_measurement_writers_cannot_overlap(tmp_path):
    domain, store = fixture(tmp_path)
    source, revision, parsed = archived(store)
    external = Batch.model_validate(
        {
            "mutation_id": "external-mutation-0001",
            "collector": "collector",
            "source": source["source"],
            "revision": 1,
            "source_bytes": 100,
            "read_bytes": 100,
            "parser_version": "external/1",
            "records": [],
        }
    )
    domain.ingest("machine", external)
    with pytest.raises(ValueError, match="statistical ledger"):
        ingest(domain, source, revision, parsed)
    other = archived(store, "pi-source-0000000002")
    ingest(domain, *other)
    external = external.model_copy(
        update={
            "source": other[0]["source"],
            "mutation_id": "external-mutation-0002",
            "revision": 2,
        }
    )
    with pytest.raises(ValueError, match="owned by the native"):
        domain.ingest("machine", external)


def test_old_parser_snapshots_cannot_be_imported_as_empty_measurements(tmp_path):
    domain, store = fixture(tmp_path)
    source, revision, parsed = archived(store)
    parsed.pop("recorded_measurement_schema")
    with pytest.raises(ValueError, match="reparsed"):
        ingest(domain, source, revision, parsed)
    assert events(domain) == []


def test_archive_append_replaces_projection_without_recounting_prior_events(tmp_path):
    from copy import deepcopy

    domain, store = fixture(tmp_path)
    source, revision, parsed = archived(store)
    ingest(domain, source, revision, parsed)
    start = parsed["complete_bytes"]
    suffix = b'{"type":"message"}\n'
    store.ingest_source(
        "machine",
        SourceChunk.model_validate(
            {
                "schema_id": "trajectory-source-chunk/1",
                "mutation_id": "append-measurement-mutation",
                "collector": "collector",
                "source": source["source"],
                "ecosystem": "pi",
                "generation": "generation-1",
                "start": start,
                "end": start + len(suffix),
                "source_bytes": start + len(suffix),
                "content": base64.b64encode(suffix).decode(),
                "sha256": hashlib.sha256(suffix).hexdigest(),
                "source_name": source["source_name"],
            }
        ),
    )
    latest, chunks = store.archive("owner", store.session_id("collector", source["source"]))
    changed = deepcopy(parsed)
    changed["complete_bytes"] = start + len(suffix)
    changed["source_sha256"] = hashlib.sha256(b"".join(chunks)).hexdigest()
    extra = deepcopy(changed["source_records"][1])
    extra.update(native_id="a2", event_id="event-a2", response_id="response-2", source_line=3)
    changed["source_records"].append(extra)
    new_revision = hashlib.sha256(f"generation-1:{start+len(suffix)}".encode()).hexdigest()
    receipt = ingest(domain, latest, new_revision, changed)
    assert len(events(domain)) == 3
    assert ingest(domain, latest, new_revision, changed) == receipt
    assert domain.overview("owner")["projects"][0]["input"] == 20
    with pytest.raises(ValueError, match="Source changed"):
        ingest(domain, source, revision, parsed)
