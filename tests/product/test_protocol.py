from pathlib import Path

from fastapi.testclient import TestClient

from trajectory.product.contracts import Batch
from trajectory.product.server import Principal, create_app


def test_native_machine_sync_idempotency_scope_revocation_and_server_attribution(
    tmp_path: Path,
) -> None:
    active = {"machine": True}

    def authorize(request, scope):
        from fastapi import HTTPException

        token = request.headers.get("authorization")
        if token == "Bearer machine" and active["machine"] and scope in (None, "upload"):
            return Principal("machine", "native-client", "test-key", ("upload",))
        if token == "Bearer human" and scope in (None, "read", "configure"):
            return Principal("human", scopes=("read", "configure"))
        raise HTTPException(403, "Denied")

    app = create_app(tmp_path / "domain.db", authorize, lambda account, client: True)
    app.state.domain.register("human", "machine", "fixture")
    client = TestClient(app)
    payload = {
        "mutation_id": "mutation-00000001",
        "collector": "fixture",
        "source": "source-000000001",
        "revision": 1,
        "source_bytes": 100,
        "read_bytes": 100,
        "parser_version": "fixture/1",
        "records": [
            {
                "id": "request-000000001",
                "session": "session",
                "task": "task",
                "ecosystem": "codex",
                "timestamp": "2026-10-06T00:00:00Z",
                "kind": "request",
                "source_line": 1,
                "references": ["BatCave-Ops"],
            },
            {
                "id": "usage-00000000001",
                "session": "session",
                "task": "task",
                "ecosystem": "codex",
                "timestamp": "2026-10-06T00:00:10Z",
                "kind": "usage",
                "source_line": 2,
                "input": 10,
                "output": 5,
            },
        ],
    }
    Batch.model_validate(payload)
    first = client.post(
        "/trajectory/api/batches",
        json=payload,
        headers={"Authorization": "Bearer machine"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["durable"] is True
    assert (
        client.post(
            "/trajectory/api/batches",
            json=payload,
            headers={"Authorization": "Bearer machine"},
        ).json()
        == first.json()
    )
    metrics = client.get(
        "/trajectory/api/overview", headers={"Authorization": "Bearer human"}
    ).json()
    assert metrics["projects"][0]["id"] == "ops"
    assert metrics["projects"][0]["input"] == 10
    assert metrics["projects"][0]["unpriced_calls"] == 1
    assert client.get("/trajectory/api/overview").status_code == 403
    assert (
        client.post(
            "/trajectory/api/batches",
            json=payload,
            headers={"Authorization": "Bearer human"},
        ).status_code
        == 403
    )
    active["machine"] = False
    assert (
        client.post(
            "/trajectory/api/batches",
            json=payload,
            headers={"Authorization": "Bearer machine"},
        ).status_code
        == 403
    )
    assert client.get("/trajectory/help").status_code == 200
    assert client.get("/trajectory/help").json()["tools"] == []
    active["machine"] = True
    help_response = client.get(
        "/trajectory/help", headers={"Authorization": "Bearer machine"}
    ).json()
    assert [tool["name"] for tool in help_response["tools"]] == ["ingest"]
    assert (
        "project" not in client.get("/trajectory/protocol").json()["$defs"]["Record"]["properties"]
    )


def test_protocol_rejects_raw_prompts_and_nonfinite_prices(tmp_path: Path) -> None:
    import pytest
    from pydantic import ValidationError

    from trajectory.product.contracts import Price, Record

    record = {
        "id": "record-000000001",
        "session": "session",
        "task": "task",
        "ecosystem": "codex",
        "timestamp": None,
        "kind": "usage",
        "source_line": 1,
        "input": None,
    }
    parsed = Record.model_validate(record)
    assert parsed.input is None and parsed.timestamp is None
    with pytest.raises(ValidationError):
        Record.model_validate({**record, "prompt": "private source text"})
    with pytest.raises(ValidationError):
        Price.model_validate(
            {
                "mutation_id": "mutation-000000001",
                "model": "example",
                "input": float("inf"),
                "output": 0,
                "cached": 0,
                "cache_write": 0,
                "effective_from": "2026-10-06T00:00:00Z",
                "source_url": "https://example.com/pricing",
            }
        )


def test_conflicting_retransmission_does_not_change_persisted_data(
    tmp_path: Path,
) -> None:
    import pytest

    from trajectory.product.domain import Domain

    domain = Domain(tmp_path / "state.db")
    domain.register("owner", "machine", "fixture")
    batch = Batch.model_validate(
        {
            "mutation_id": "mutation-000000001",
            "collector": "fixture",
            "source": "source-000000001",
            "revision": 1,
            "source_bytes": 1,
            "read_bytes": 1,
            "parser_version": "fixture/1",
            "records": [],
        }
    )
    receipt = domain.ingest("machine", batch)
    with pytest.raises(ValueError):
        domain.ingest("machine", batch.model_copy(update={"source_bytes": 2}))
    assert domain.ingest("machine", batch) == receipt
    assert domain.overview("owner")["coverage"]["source_bytes"] == 1


def test_unknown_cached_usage_is_not_zero_cost_and_corrections_are_owner_scoped(
    tmp_path: Path,
) -> None:
    import pytest

    from trajectory.product.contracts import Correction, Price
    from trajectory.product.domain import Domain

    domain = Domain(tmp_path / "cost.db")
    domain.register("owner", "machine", "fixture")
    batch = Batch.model_validate(
        {
            "mutation_id": "mutation-000000002",
            "collector": "fixture",
            "source": "source-000000002",
            "revision": 1,
            "source_bytes": 10,
            "read_bytes": 10,
            "parser_version": "fixture/1",
            "records": [
                {
                    "id": "usage-00000000002",
                    "session": "session",
                    "task": "task",
                    "ecosystem": "codex",
                    "timestamp": "2026-10-06T00:00:10Z",
                    "kind": "usage",
                    "model": "example",
                    "source_line": 1,
                    "input": 10,
                    "output": 5,
                    "cached": None,
                    "workspace": "BatCave-Ops",
                }
            ],
        }
    )
    domain.ingest("machine", batch)
    domain.price(
        "owner",
        Price.model_validate(
            {
                "mutation_id": "price-00000000001",
                "model": "example",
                "input": 1,
                "output": 2,
                "cached": 0.1,
                "cache_write": 0,
                "effective_from": "2026-10-01T00:00:00Z",
                "source_url": "https://example.com/prices",
            }
        ),
    )
    row = domain.overview("owner")["projects"][0]
    assert row["unpriced_calls"] == 1
    assert row["missing_counters"]["cached"] == 1
    correction = Correction(
        mutation_id="correct-000000001", task="task", project="trajectory", project_name="行迹"
    )
    with pytest.raises(ValueError, match="Task not found in this account"):
        domain.correct("other-owner", correction)
    receipt = domain.correct("owner", correction)
    assert domain.correct("owner", correction) == receipt
    assert domain.overview("owner")["projects"][0]["id"] == "trajectory"
    backup = tmp_path / "backup.db"
    domain.backup(backup)
    assert Domain(backup).overview("owner")["projects"][0]["id"] == "trajectory"


def test_revision_gap_is_rejected_without_advancing_durable_progress(tmp_path: Path) -> None:
    import pytest

    from trajectory.product.domain import Domain

    domain = Domain(tmp_path / "revision.db")
    domain.register("owner", "machine", "fixture")
    batch = Batch.model_validate(
        {
            "mutation_id": "mutation-000000003",
            "collector": "fixture",
            "source": "source-000000003",
            "revision": 1,
            "source_bytes": 10,
            "read_bytes": 5,
            "parser_version": "fixture/1",
            "records": [],
        }
    )
    domain.ingest("machine", batch, "native-key-id", "native-client-id")
    with pytest.raises(ValueError, match="Missing source revision"):
        domain.ingest(
            "machine", batch.model_copy(update={"revision": 3, "mutation_id": "mutation-000000004"})
        )
    with domain.connect() as db:
        import json

        assert db.execute("SELECT revision FROM sources").fetchone()[0] == 1
        audit = json.loads(db.execute("SELECT body FROM audit").fetchone()[0])
        assert audit["key_id"] == "native-key-id"
        assert audit["machine_client"] == "native-client-id"


def test_daily_time_splits_midnight_and_new_request_does_not_charge_previous_work(
    tmp_path: Path,
) -> None:
    from trajectory.product.domain import Domain

    domain = Domain(tmp_path / "time.db")
    domain.register("owner", "machine", "fixture")

    def event(number, stamp, kind, task="task-one", references=None):
        return {
            "id": f"event-{number:020d}",
            "session": "session",
            "task": task,
            "ecosystem": "codex",
            "timestamp": stamp,
            "kind": kind,
            "source_line": number,
            "references": references or [],
            "call": "call-one",
            "tool": "command",
        }

    records = [
        event(1, "2026-10-06T15:59:50Z", "request", references=["BatCave-Ops"]),
        event(2, "2026-10-06T16:00:10Z", "tool_start"),
        event(3, "2026-10-06T16:01:20Z", "tool_end"),
        event(
            4, "2026-10-06T16:10:20Z", "request", task="task-two", references=["BatCave-Trajectory"]
        ),
    ]
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": "mutation-000000005",
                "collector": "fixture",
                "source": "source-000000005",
                "revision": 1,
                "source_bytes": 10,
                "read_bytes": 10,
                "parser_version": "fixture/1",
                "records": records,
            }
        ),
    )
    data = domain.overview("owner")
    days = {row["id"]: row for row in data["daily"]}
    assert days["2026-10-06"]["active_seconds_estimate"] == 10
    assert days["2026-10-07"]["active_seconds_estimate"] == 80
    assert days["2026-10-07"]["tool_seconds"] == 70
    projects = {row["id"]: row for row in data["projects"]}
    assert projects["ops"]["active_seconds_estimate"] == 90
    assert projects["trajectory"]["active_seconds_estimate"] == 0
    assert data["anomalies"][0]["kind"] == "slow_tool"
    assert data["anomalies"][0]["cause"] == "unknown"
    filtered = domain.overview("owner", since="2026-10-07", until="2026-10-07")
    assert filtered["daily"][0]["active_seconds_estimate"] == 80


def test_collector_binding_requires_administrator_permission_in_addition_to_configure(
    tmp_path: Path,
) -> None:
    from fastapi import HTTPException

    def ordinary_member(request, scope):
        if scope in (None, "read", "configure"):
            return Principal("ordinary-member", scopes=("read", "configure"))
        raise HTTPException(403, "Administrator permission denied")

    app = create_app(tmp_path / "binding.db", ordinary_member, lambda account, client: True)
    client = TestClient(app)
    result = client.post(
        "/trajectory/api/collectors",
        json={
            "machine": "11111111-1111-4111-8111-111111111111",
            "machine_client": "native-fixture",
            "collector": "fixture",
        },
    )
    assert result.status_code == 403
    with app.state.domain.connect() as db:
        assert db.execute("SELECT count(*) FROM collectors").fetchone()[0] == 0
    help_value = client.get(
        "/trajectory/help", headers={"Authorization": "Bearer ordinary-member"}
    ).json()
    assert "bind" not in [tool["name"] for tool in help_value["tools"]]
