from pathlib import Path

import pytest
from pydantic import ValidationError

from trajectory.product.contracts import Batch, Record
from trajectory.product.domain import Domain


def record(index: int, **changes: object) -> dict:
    return {
        "id": f"human-input-{index:016}",
        "session": "session",
        "task": "task",
        "ecosystem": "codex",
        "timestamp": "2026-10-12T00:00:00Z",
        "kind": "request",
        "source_line": index + 1,
        "references": ["BatCave-Ops"],
        **changes,
    }


def batch(
    records: list[dict],
    revision: int = 1,
    collector: str = "fixture",
    source: str = "human-source-000001",
    replace: bool = False,
) -> Batch:
    return Batch.model_validate(
        {
            "mutation_id": f"human-input-batch-{collector}-{source}-{revision}",
            "collector": collector,
            "source": source,
            "revision": revision,
            "source_bytes": 100,
            "read_bytes": 100,
            "parser_version": "fixture/1",
            "records": records,
            "replace": replace,
        }
    )


def test_human_origin_and_character_coverage_without_usage_records(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "human.db")
    domain.register("owner", "machine", "fixture")
    records = [
        record(0, input_origin="human", input_chars=12),
        record(1, input_origin="human", input_chars=0),
        record(2, input_origin="human"),
        record(3),
        record(4, input_origin="unknown", input_chars=999),
        record(5, input_origin="agent", input_chars=120),
        record(6, input_origin="system", input_chars=30),
        record(7, kind="usage", input=100, output=10, cached=0),
    ]
    payload = batch(records)
    receipt = domain.ingest("machine", payload)
    assert domain.ingest("machine", payload) == receipt
    result = domain.overview("owner")
    expected = {
        "human_interactions": 3,
        "human_input_chars": 12,
        "missing_human_input_chars": 1,
        "unknown_origin_interactions": 2,
        "agent_interactions": 1,
        "system_interactions": 1,
    }
    for row in (result["projects"][0], result["daily"][0], result["tasks"][0]):
        assert {key: row[key] for key in expected} == expected
    domain.ingest("machine", batch(records, revision=2, replace=True))
    assert domain.overview("owner")["projects"][0]["human_interactions"] == 3


def test_date_filters_and_unknown_timestamps_apply_to_human_counters(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "dates.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest(
        "machine",
        batch(
            [
                record(0, timestamp="2026-10-11T15:59:59Z", input_origin="human", input_chars=1),
                record(1, timestamp="2026-10-11T16:00:00Z", input_origin="human", input_chars=2),
                record(2, timestamp=None, input_origin="human", input_chars=3),
            ]
        ),
    )
    result = domain.overview("owner", since="2026-10-12", until="2026-10-12")
    assert result["projects"][0]["human_interactions"] == 2
    assert result["projects"][0]["human_input_chars"] == 5
    assert {row["id"]: row["human_input_chars"] for row in result["daily"]} == {
        "2026-10-12": 2,
        "unknown": 3,
    }


def test_cross_source_copies_are_not_claimed_as_proven_duplicates(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "copies.db")
    domain.register("owner", "machine", "fixture")
    domain.register("owner", "machine", "other")
    records = [record(0, input_origin="human", input_chars=5)]
    domain.ingest("machine", batch(records))
    domain.ingest("machine", batch(records, collector="other", source="human-source-000002"))
    result = domain.overview("owner")
    assert result["projects"][0]["human_interactions"] == 2
    assert "not deduplicated" in result["coverage"]["request_deduplication"]


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "usage", "input_origin": "human"},
        {"kind": "notice", "input_chars": 0},
        {"kind": "usage", "interaction_id": "provider-message-000001"},
        {"input_chars": -1},
        {"input_chars": True},
        {"input_chars": 2.5},
        {"input_chars": 9_007_199_254_740_992},
        {"input_origin": "user"},
        {"prompt": "must never be transported"},
    ],
)
def test_invalid_input_fields_are_rejected(changes: dict) -> None:
    with pytest.raises(ValidationError):
        Record.model_validate(record(0, **changes))


def test_provider_request_identity_deduplicates_copies_across_collectors(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "identity.db")
    domain.register("owner", "machine", "fixture")
    domain.register("owner", "machine", "other")
    records = [
        record(0, input_origin="human", input_chars=5, interaction_id="provider-message-000001")
    ]
    domain.ingest("machine", batch(records))
    domain.ingest("machine", batch(records, collector="other", source="human-source-000002"))
    result = domain.overview("owner")
    assert result["projects"][0]["human_interactions"] == 1
    assert result["projects"][0]["human_input_chars"] == 5
    assert result["coverage"]["deduplicated_request_records"] == 1


def test_inherited_copy_does_not_replace_original_human_interaction(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "inherited.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest(
        "machine",
        batch(
            [
                record(
                    0, input_origin="human", input_chars=5, interaction_id="provider-message-000001"
                ),
                record(
                    1,
                    input_origin="system",
                    input_chars=5,
                    interaction_id="provider-message-000001",
                    timestamp="2026-10-12T00:01:00Z",
                    task="child",
                ),
            ]
        ),
    )
    result = domain.overview("owner")
    assert result["projects"][0]["human_interactions"] == 1
    assert result["projects"][0]["system_interactions"] == 0
    assert {r["id"]: r["human_interactions"] for r in result["tasks"]} == {"task": 1, "child": 0}


def test_runtime_protocol_discovers_request_input_fields(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from trajectory.product.server import Principal, create_app

    app = create_app(tmp_path / "protocol.db", lambda request, scope: Principal("owner"))
    client = TestClient(app)
    response = client.get("/trajectory/protocol")
    assert response.status_code == 200
    properties = response.json()["$defs"]["Record"]["properties"]
    assert {"input_origin", "input_chars", "interaction_id"} <= properties.keys()
    assert properties["input_chars"]["anyOf"][0]["minimum"] == 0


@pytest.mark.parametrize(
    "origins,expected,status",
    [
        (["unknown"], None, "unknown"),
        (["agent", "system"], 0, "observed"),
        (["human", "unknown"], 2, "partial"),
    ],
)
def test_unknown_origin_is_not_human_zero(tmp_path, origins, expected, status):
    domain = Domain(tmp_path / "coverage.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest(
        "machine",
        batch(
            [
                record(index, input_origin=origin, input_chars=2)
                for index, origin in enumerate(origins)
            ]
        ),
    )
    overview = domain.overview("owner")
    for metrics in (overview["projects"][0], overview["daily"][0], overview["tasks"][0]):
        assert metrics["human_input_chars"] == expected
        assert metrics["human_input_coverage"]["status"] == status
        assert metrics["human_input_coverage"]["origin_unknown_requests"] == origins.count(
            "unknown"
        )


def test_all_human_text_missing_is_unknown_with_observed_interactions(tmp_path):
    domain = Domain(tmp_path / "missing-text.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest("machine", batch([record(0, input_origin="human")]))
    metrics = domain.overview("owner")["projects"][0]
    assert metrics["human_interactions"] == 1
    assert metrics["human_input_chars"] is None
    assert metrics["human_input_coverage"]["known_human_input_chars"] == 0
    assert metrics["human_input_coverage"]["known_human_text_requests"] == 0


def test_human_coverage_is_idempotent_and_survives_parent_aggregation():
    from trajectory.product.semantic import total_metrics

    values = dict(
        human_interactions=0,
        human_input_chars=0,
        missing_human_input_chars=0,
        unknown_origin_interactions=2,
        agent_interactions=0,
        system_interactions=0,
    )
    Domain.apply_human_input_coverage(values)
    first = dict(values)
    Domain.apply_human_input_coverage(values)
    assert values == first
    parent = total_metrics([total_metrics([values])])
    assert parent["human_interactions"] is None
    assert parent["human_input_chars"] is None
    assert parent["human_input_coverage"]["confirmed_human_requests"] == 0
    assert parent["unknown_origin_interactions"] == 2
