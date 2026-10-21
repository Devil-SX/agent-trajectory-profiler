"""Streaming source attribution retains global deduplication and price context."""

import json
import uuid

import pytest

from trajectory.product.contracts import Batch, Correction, Price
from trajectory.product.domain import Domain
from trajectory.product.semantic import SemanticStore, total_metrics


def event(identity, kind, second, **extra):
    return {
        "id": identity.ljust(16, "0"),
        "session": "shared-session",
        "task": "shared-task",
        "ecosystem": "codex",
        "kind": kind,
        "timestamp": f"2026-10-01T00:00:{second:02d}Z",
        "source_line": second + 1,
        "model": "model",
        "input": 0,
        "output": 0,
        "cached": 0,
        "cache_write": 0,
        "reasoning": 0,
        **extra,
    }


def ingest(domain, source, events):
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": uuid.uuid4().hex,
                "collector": "fixture",
                "source": source,
                "revision": 1,
                "source_bytes": 100,
                "read_bytes": 100,
                "parser_version": "isolated/1",
                "records": events,
            }
        ),
    )


def test_source_scans_preserve_global_usage_request_dedup_corrections_and_session_price(tmp_path):
    domain = Domain(tmp_path / "fixture.sqlite")
    domain.register("owner", "machine", "fixture")
    first = "source-0000000001"
    second = "source-0000000002"
    ingest(
        domain,
        first,
        [
            event(
                "human",
                "request",
                0,
                input_origin="human",
                input_chars=20,
                interaction_id="shared-interaction",
                references=["BatCave-Ops"],
            ),
            event("own-usage", "usage", 1, input=20, consumption="own"),
            event("copied-early", "usage", 2, input=40, consumption="copied"),
            event("start", "tool_start", 3, call="shared-call", tool="fixture"),
        ],
    )
    ingest(
        domain,
        second,
        [
            event(
                "agent-copy",
                "request",
                0,
                input_origin="agent",
                input_chars=99,
                interaction_id="shared-interaction",
                references=["Wenshu"],
            ),
            event(
                "copied-late",
                "usage",
                5,
                input=40,
                consumption="copied",
                timestamp="2026-10-02T00:00:05Z",
            ),
            event(
                "large-context",
                "usage",
                6,
                input=200,
                consumption="large",
                timestamp="2026-10-02T00:00:06Z",
            ),
            event("end", "tool_end", 8, call="shared-call"),
        ],
    )
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
                "source_url": "https://example.org/fixture-pricing",
                "context_scope": "session",
                "long_context_threshold": 100,
                "long_context": {"input": 10, "output": 10, "cached": 0, "cache_write": 0},
            }
        ),
    )
    domain.correct(
        "owner",
        Correction(
            mutation_id=uuid.uuid4().hex,
            task="shared-task",
            project="corrected",
            project_name="Fixture",
        ),
    )
    result = domain.overview("owner")
    assert "event_contributions" not in result
    assert not hasattr(domain, "_overview_cache")
    assert result["projects"][0]["id"] == "corrected"
    assert result["projects"][0]["input"] == 260
    assert result["projects"][0]["human_interactions"] == 1
    assert result["projects"][0]["agent_interactions"] == 0
    assert result["projects"][0]["known_subtotal_usd"] == pytest.approx(0.0026)
    assert result["coverage"]["deduplicated_usage_records"] == 1
    assert result["coverage"]["deduplicated_request_records"] == 1
    for source, calls, inputs in ((first, 1, 20), (second, 2, 240)):
        selected = domain.source_contributions("owner", "fixture", source)
        assert all(item["record"]["source"] == source for item in selected)
        metrics = total_metrics(selected)
        assert metrics["calls"] == calls and metrics["input"] == inputs
        summary = next(
            item for item in domain.session_summaries("owner") if item["record"]["source"] == source
        )
        assert total_metrics([summary]) == metrics
    assert (
        total_metrics(domain.source_contributions("owner", "fixture", first))["tool_seconds"] == 5
    )
    filtered = domain.overview("owner", "2026-10-01", "2026-10-01")
    assert filtered["projects"][0]["calls"] == 1
    assert filtered["projects"][0]["known_subtotal_usd"] == pytest.approx(0.0002)
    assert domain.source_contributions("stranger", "fixture", first) == []


def test_batch_names_read_only_lightweight_metadata_without_overview_or_ir(tmp_path, monkeypatch):
    from trajectory.product.contracts import AnalysisBatchRequest

    store = SemanticStore(Domain(tmp_path / "fixture.sqlite"))
    with store.domain.connect() as db:
        db.execute(
            "INSERT INTO semantic_sessions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "owner",
                "sid",
                "fixture",
                "source",
                "Named session",
                "codex",
                "rev",
                "INVALID IR MUST NOT BE READ",
                "now",
            ),
        )
        db.execute(
            "INSERT INTO semantic_session_metadata VALUES(?,?,?,?)",
            (
                "owner",
                "sid",
                json.dumps(
                    {
                        "display_title": "CPM progress",
                        "first_user_message": "CPM progress",
                        "cwd": "/embodied",
                        "started_at": "2026-10-01",
                    }
                ),
                "now",
            ),
        )
    monkeypatch.setattr(
        store.domain, "overview", lambda *a, **k: pytest.fail("No global overview for batch names")
    )
    receipt = store.request_batch(
        "owner", AnalysisBatchRequest(mutation_id=uuid.uuid4().hex, session_ids=["sid"])
    )
    session = store.batch_detail("owner", receipt["batch_id"])["items"][0]["session"]
    assert session["title"] == "Named session" and session["display_title"] == "CPM progress"
    assert session["cwd"] == "/embodied" and session["id"] == "sid"


def test_normalization_adapter_identity_is_visible_without_analyzing(tmp_path):
    store = SemanticStore(Domain(tmp_path / "fixture.sqlite"))
    body = {
        "session": {},
        "operations": [],
        "worker_version": "0.1.3",
        "schema": "trajectory.agent-session/1",
        "recorded_measurement_schema": "trajectory.recorded-measurements/1",
    }
    with store.domain.connect() as db:
        db.execute(
            "INSERT INTO semantic_sessions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "owner",
                "sid",
                "fixture",
                "source",
                "Named session",
                "pi",
                "rev",
                json.dumps(body),
                "now",
            ),
        )
    normalization = store.detail("owner", "sid", contributions=[])["coverage"]["normalization"]
    assert normalization == {
        key: body[key] for key in ("worker_version", "schema", "recorded_measurement_schema")
    }
